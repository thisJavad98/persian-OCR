package cursor

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/javad-moghofei/persian-ocr/back/internal/config"
	"github.com/javad-moghofei/persian-ocr/back/internal/handwriting"
	"github.com/javad-moghofei/persian-ocr/back/internal/ocr"
)

const ocrPrompt = `OCR this image file (relative to workspace): %s

Transcribe ALL visible text exactly (Persian/Arabic logical order, keep digits and Latin).

If the image is a TABLE (spreadsheet, form grid, printed table):
- set "is_table": true
- fill "table":{"headers":[...],"rows":[["cell",...],...]} with every row/column in reading order (top-to-bottom, right-to-left for Persian tables)
- also set "text" as a plain fallback transcript

If NOT a table: "is_table": false and "table": null

Return ONLY JSON:
{"is_table":false,"text":"","lines":[],"words":[],"sentences":[],"confidence":0.0,"table":null}
`

// Fast prompt: compact but table-first (tables are common in this app).
const ocrPromptFast = `OCR image: %s
Persian/Arabic RTL, exact transcription.
If the image is a table, spreadsheet, form grid, or Excel screenshot:
  "is_table": true
  "table": {"headers":["..."] or omit,"rows":[["cell","..."],...]} — one string per cell, row-major, top→bottom, each row RTL column order.
  "text": plain fallback (rows joined).
Otherwise: "is_table": false, "table": null.
Return ONLY JSON: {"is_table":false,"text":"","lines":[],"confidence":0.0,"table":null}
Do not include words/sentences.`

// Table prompt: headers + grid, kept short for latency.
const ocrPromptTable = `TABLE OCR %s — Persian RTL, exact cells.
headers[]=top row only (RTL: headers[0]=rightmost column). rows[]=data only (no header duplicate). Empty="".
JSON only: {"is_table":true,"text":"","lines":[],"confidence":0.0,"table":{"headers":[],"rows":[[]]}}`

type Result struct {
	Text       string        `json:"text"`
	Lines      []string      `json:"lines"`
	Words      []string      `json:"words"`
	Sentences  []string      `json:"sentences"`
	Confidence float64       `json:"confidence"`
	Engine     string        `json:"engine"`
	Raw        string        `json:"raw,omitempty"`
	IsTable    bool          `json:"is_table"`
	Table      *parsedTable  `json:"table,omitempty"`
}

type parsedTable struct {
	Headers []string   `json:"headers"`
	Rows    [][]string `json:"rows"`
}

type Status struct {
	Ready      bool   `json:"ready"`
	Engine     string `json:"engine"`
	AuthVia    string `json:"auth_via"`
	Model      string `json:"model"`
	Error      string `json:"error,omitempty"`
}

type Service struct {
	cfg       *config.Config
	workspace string

	mu            sync.Mutex
	loggedInCache *bool
	agentPath     string
}

func NewService(cfg *config.Config, workspace string) *Service {
	return &Service{cfg: cfg, workspace: workspace}
}

func (s *Service) EngineLabel() string {
	return "cursor:" + s.cfg.OCRModel()
}

func (s *Service) Available() bool {
	if !s.cfg.OCRUseCursor {
		return false
	}
	bin := s.agentBinary()
	if bin == "" || !agentRunnable(bin) {
		return false
	}
	if s.cfg.CursorAPIKey != "" {
		return true
	}
	return s.loggedIn()
}

// Connected is true when the API key is configured (serverless) or the agent CLI can run (local/Render).
func (s *Service) Connected() bool {
	if strings.TrimSpace(s.cfg.CursorAPIKey) != "" {
		return true
	}
	return s.Available()
}

func (s *Service) Status() Status {
	st := Status{
		Ready: s.Available(),
		Model: s.cfg.OCRModel(),
	}
	if s.cfg.CursorAPIKey != "" {
		st.AuthVia = "api_key"
	} else if s.agentBinary() != "" {
		st.AuthVia = "cli"
	} else {
		st.AuthVia = "none"
	}
	if st.Ready {
		st.Engine = s.EngineLabel()
	} else {
		st.Error = s.InitError()
	}
	return st
}

func (s *Service) InitError() string {
	if s.Available() {
		return ""
	}
	if !s.cfg.OCRUseCursor {
		return "OCR_USE_CURSOR=0"
	}
	if s.agentBinary() == "" {
		if s.cfg.CursorAPIKey != "" && onVercel() {
			if lastBundleErr != "" {
				return lastBundleErr
			}
			return "cursor-agent در حال نصب است؛ حدود یک دقیقه بعد دوباره تلاش کنید"
		}
		if s.cfg.CursorAPIKey != "" {
			return "CURSOR_API_KEY is set; waiting for cursor-agent runtime"
		}
		return "cursor-agent CLI not found on PATH"
	}
	if s.cfg.CursorAPIKey != "" {
		return "cursor-agent bundle not ready"
	}
	return "cursor-agent not logged in (run cursor-agent login) or set CURSOR_API_KEY"
}

func (s *Service) Engines() []string {
	if s.Available() {
		return []string{s.EngineLabel()}
	}
	return nil
}

func (s *Service) InvalidateAuthCache() {
	s.mu.Lock()
	s.loggedInCache = nil
	s.mu.Unlock()
}

func (s *Service) Extract(parent context.Context, imagePath string, profile *handwriting.Profile, tableLayout bool) (*Result, error) {
	return s.extractWithRetry(parent, imagePath, s.cfg.CursorOCRRetries, profile, tableLayout)
}

// StudyHandwriting runs a short calibration pass on the user's sample + Excel reference.
func (s *Service) StudyHandwriting(ctx context.Context, imagePath, referenceGrid string) (string, error) {
	binary := s.agentBinary()
	if binary == "" {
		return "", fmt.Errorf("cursor-agent CLI not found on PATH")
	}
	root, err := filepath.Abs(s.workspace)
	if err != nil {
		return "", err
	}
	rel, err := filepath.Rel(root, imagePath)
	if err != nil {
		rel = imagePath
	}
	rel = filepath.ToSlash(rel)
	prompt := buildStudyPrompt(rel, referenceGrid)
	cmd := s.buildCommand(ctx, binary, root, prompt, s.cfg.OCRModel())
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	cmd.Dir = root
	if err := cmd.Run(); err != nil {
		if ctx.Err() != nil {
			return "", friendlyError(ctx.Err())
		}
		out := strings.TrimSpace(stdout.String())
		if out == "" {
			return "", fmt.Errorf("calibration failed: %s", trim(stderr.String(), 400))
		}
	}
	out := strings.TrimSpace(stdout.String())
	if notes := parseStudyNotes(out); notes != "" {
		return trim(notes, 2000), nil
	}
	return "handwriting profile active", nil
}

func parseStudyNotes(text string) string {
	cleaned := stripNoise(text)
	var raw map[string]json.RawMessage
	if err := json.Unmarshal([]byte(cleaned), &raw); err != nil {
		return ""
	}
	var notes string
	_ = json.Unmarshal(raw["style_notes"], &notes)
	notes = strings.TrimSpace(notes)
	if notes != "" {
		return notes
	}
	var fallback string
	_ = json.Unmarshal(raw["text"], &fallback)
	return strings.TrimSpace(fallback)
}

func (s *Service) extractWithRetry(parent context.Context, imagePath string, retries int, profile *handwriting.Profile, tableLayout bool) (*Result, error) {
	var last error
	attempts := retries + 1
	if attempts < 1 {
		attempts = 1
	}
	perAttempt := time.Duration(s.cfg.CursorTimeoutForUpload(tableLayout) * float64(time.Second))

	for attempt := 0; attempt < attempts; attempt++ {
		if attempt > 0 {
			select {
			case <-parent.Done():
				return nil, friendlyError(parent.Err())
			case <-time.After(400 * time.Millisecond):
			}
		}
		attemptCtx, cancel := context.WithTimeout(parent, perAttempt)
		res, err := s.extractOnce(attemptCtx, imagePath, profile, tableLayout)
		cancel()
		if err == nil {
			return res, nil
		}
		last = err
		if !isRetryable(err) || attempt == attempts-1 {
			break
		}
		s.InvalidateAuthCache()
	}
	return nil, friendlyError(last)
}

func (s *Service) extractOnce(ctx context.Context, imagePath string, profile *handwriting.Profile, tableLayout bool) (*Result, error) {
	binary := s.agentBinary()
	if binary == "" {
		return nil, fmt.Errorf("cursor-agent CLI not found on PATH")
	}

	root, err := filepath.Abs(s.workspace)
	if err != nil {
		return nil, err
	}

	rel, err := filepath.Rel(root, imagePath)
	if err != nil {
		rel = imagePath
	}
	rel = filepath.ToSlash(rel)

	prompt := buildOCRPrompt(rel, profile, s.cfg.OCRFast, tableLayout)
	cmd := s.buildCommand(ctx, binary, root, prompt, s.cfg.ModelForUpload(tableLayout))

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	cmd.Dir = root

	runErr := cmd.Run()
	out := strings.TrimSpace(stdout.String())
	errText := strings.TrimSpace(stderr.String())

	if runErr != nil {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		if out == "" {
			combined := errText
			if combined == "" {
				combined = runErr.Error()
			}
			return nil, fmt.Errorf("%s", combined)
		}
	}

	data := parseAgentJSON(out)
	if data.Text == "" && len(data.Lines) == 0 {
		cleaned := stripNoise(out)
		if cleaned == "" {
			msg := trim(out, 400)
			if msg == "" && errText != "" {
				msg = trim(errText, 400)
			}
			return nil, fmt.Errorf("cursor-agent returned no OCR payload: %s", msg)
		}
		data = &Result{
			Text:       cleaned,
			Lines:      nonEmptyLines(cleaned),
			Confidence: 0.75,
		}
		enrichResult(data)
	} else {
		enrichResult(data)
	}

	data.Engine = s.EngineLabel()
	data.Raw = trim(out, 8000)
	return data, nil
}

func (s *Service) agentEnv(root string) []string {
	home := root
	if onVercel() {
		home = filepath.Join(os.TempDir(), "persian-ocr-cursor-home")
		_ = os.MkdirAll(home, 0o700)
	}
	cfg := filepath.Join(home, ".config")
	_ = os.MkdirAll(cfg, 0o700)
	env := append(os.Environ(),
		"HOME="+home,
		"XDG_CONFIG_HOME="+cfg,
		"CURSOR_HOME="+home,
		"AGENT_CLI_CREDENTIAL_STORE=file",
		"CURSOR_AGENT_DISABLE_DEBUG_LOG=1",
		"CI=1",
		"TERM=dumb",
	)
	if onVercel() {
		env = append(env,
			"BROWSER=/bin/false",
			"DISPLAY=",
			"CURSOR_AGENT_HEADLESS=1",
		)
	}
	return env
}

func (s *Service) buildCommand(ctx context.Context, binary, root, prompt, model string) *exec.Cmd {
	if strings.TrimSpace(model) == "" {
		model = s.cfg.OCRModel()
	}
	flags := []string{
		"--mode", "ask",
		"-p",
		"--output-format", "text",
		"--model", model,
		"--trust",
		"--workspace", root,
	}
	if s.cfg.CursorAPIKey != "" {
		flags = append(flags, "--api-key", s.cfg.CursorAPIKey)
	}
	flags = append(flags, prompt)

	var cmd *exec.Cmd
	if strings.HasSuffix(binary, "index.js") {
		node := resolveNodeForIndex(binary)
		if node == "" {
			return exec.CommandContext(ctx, "false")
		}
		args := append([]string{binary}, flags...)
		cmd = exec.CommandContext(ctx, node, args...)
	} else {
		cmd = exec.CommandContext(ctx, binary, flags...)
	}
	cmd.Env = s.agentEnv(root)
	cmd.Dir = root
	return cmd
}

func isRetryable(err error) bool {
	if err == nil {
		return false
	}
	if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
		return true
	}
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "timeout") ||
		strings.Contains(msg, "temporarily") ||
		strings.Contains(msg, "503") ||
		strings.Contains(msg, "no ocr payload")
}

func friendlyError(err error) error {
	if err == nil {
		return nil
	}
	if errors.Is(err, context.DeadlineExceeded) {
		return fmt.Errorf("زمان OCR تمام شد؛ تصویر کوچک‌تر بفرستید یا CURSOR_OCR_TIMEOUT را بالا ببرید")
	}
	if errors.Is(err, context.Canceled) {
		return fmt.Errorf("OCR لغو شد")
	}
	return err
}

func (s *Service) agentBinary() string {
	if s.agentPath != "" {
		if agentRunnable(s.agentPath) {
			return s.agentPath
		}
		s.agentPath = ""
	}
	if onVercel() {
		if p := installCursorBundle(); p != "" {
			s.agentPath = p
			return p
		}
	}
	if p := s.resolveAgentPath(); p != "" && agentRunnable(p) {
		s.agentPath = p
		return p
	}
	for _, name := range []string{"cursor-agent", "agent"} {
		if p, err := exec.LookPath(name); err == nil {
			if resolved := resolveAgentPath(p); resolved != "" && agentRunnable(resolved) {
				s.agentPath = resolved
				return resolved
			}
		}
	}
	return ""
}

func agentRunnable(binary string) bool {
	if binary == "" {
		return false
	}
	if strings.HasSuffix(binary, "index.js") {
		if st, err := os.Stat(binary); err != nil || st.IsDir() {
			return false
		}
		return resolveNodeForIndex(binary) != ""
	}
	if strings.HasSuffix(binary, "cursor-agent-sea") || strings.HasSuffix(binary, "cursor-agent") {
		st, err := os.Stat(binary)
		return err == nil && !st.IsDir()
	}
	dir := filepath.Dir(binary)
	info, err := os.Stat(filepath.Join(dir, "node"))
	return err == nil && !info.IsDir()
}

func (s *Service) resolveAgentPath() string {
	if s.agentPath != "" {
		return s.agentPath
	}
	tmpHome := filepath.Join(os.TempDir(), "persian-ocr-cursor-home", ".local", "bin", "cursor-agent")
	for _, p := range []string{
		filepath.Join(s.workspace, "cursor-agent"),
		filepath.Join(s.workspace, ".local", "bin", "cursor-agent"),
		tmpHome,
	} {
		if st, err := os.Stat(p); err == nil && !st.IsDir() {
			s.agentPath = p
			return p
		}
	}
	return ""
}

func (s *Service) loggedIn() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.loggedInCache != nil {
		return *s.loggedInCache
	}
	binary := s.agentBinary()
	if binary == "" {
		f := false
		s.loggedInCache = &f
		return false
	}
	statusCtx, cancel := context.WithTimeout(context.Background(), 12*time.Second)
	defer cancel()
	proc := exec.CommandContext(statusCtx, binary, "status")
	out, err := proc.CombinedOutput()
	ok := false
	if err == nil {
		lower := strings.ToLower(string(out))
		ok = strings.Contains(lower, "logged in") || strings.Contains(string(out), "✓")
	}
	s.loggedInCache = &ok
	return ok
}

var jsonObjectRe = regexp.MustCompile(`\{[\s\S]*\}`)

func parseAgentJSON(text string) *Result {
	cleaned := stripNoise(text)
	if data := decodeResult(cleaned); data != nil {
		return data
	}
	matches := jsonObjectRe.FindAllString(cleaned, -1)
	var fallback *Result
	for i := len(matches) - 1; i >= 0; i-- {
		data := decodeResult(matches[i])
		if data == nil {
			continue
		}
		if data.Table != nil && len(data.Table.Rows) > 0 {
			return data
		}
		if fallback == nil && (data.Text != "" || len(data.Lines) > 0) {
			fallback = data
		}
	}
	if fallback != nil {
		return fallback
	}
	return &Result{}
}

func decodeResult(s string) *Result {
	var raw map[string]json.RawMessage
	if err := json.Unmarshal([]byte(s), &raw); err != nil {
		return nil
	}
	res := &Result{}
	_ = json.Unmarshal(raw["text"], &res.Text)
	_ = json.Unmarshal(raw["lines"], &res.Lines)
	_ = json.Unmarshal(raw["words"], &res.Words)
	_ = json.Unmarshal(raw["sentences"], &res.Sentences)
	_ = json.Unmarshal(raw["confidence"], &res.Confidence)
	var isTable bool
	_ = json.Unmarshal(raw["is_table"], &isTable)
	res.IsTable = isTable
	if tbl, ok := raw["table"]; ok && tbl != nil {
		res.Table = parseTableJSON(tbl)
	}
	if res.Table != nil {
		norm := ocr.NormalizeTable(res.IsTable || true, res.Table.Headers, res.Table.Rows)
		if norm != nil {
			res.IsTable = true
			res.Table = &parsedTable{Headers: norm.Headers, Rows: norm.Rows}
		} else {
			res.Table = nil
		}
	}
	if res.Text == "" && len(res.Lines) == 0 && res.Table == nil {
		return nil
	}
	if res.Words == nil {
		res.Words = []string{}
	}
	if res.Sentences == nil {
		res.Sentences = []string{}
	}
	if res.Lines == nil {
		res.Lines = []string{}
	}
	return res
}

func stripNoise(text string) string {
	cleaned := strings.TrimSpace(text)
	if strings.HasPrefix(cleaned, "```") {
		re := regexp.MustCompile(`(?s)^` + "```" + `(?:json)?\s*`)
		cleaned = re.ReplaceAllString(cleaned, "")
		cleaned = regexp.MustCompile(`(?s)\s*` + "```" + `$`).ReplaceAllString(cleaned, "")
	}
	return strings.TrimSpace(cleaned)
}

func enrichResult(res *Result) {
	if res == nil {
		return
	}
	if res.Table == nil {
		if inferred := ocr.InferTableFromText(res.Text, res.Lines); inferred != nil {
			res.IsTable = true
			res.Table = &parsedTable{Headers: inferred.Headers, Rows: inferred.Rows}
		}
	}
	if res.Table != nil && len(res.Table.Rows) > 0 {
		if strings.TrimSpace(res.Text) == "" {
			res.Text = ocr.TablePlainText(res.Table.Headers, res.Table.Rows)
		}
		if len(res.Lines) == 0 {
			for _, row := range res.Table.Rows {
				res.Lines = append(res.Lines, strings.Join(row, " | "))
			}
		}
	}
	if len(res.Words) == 0 {
		for _, ln := range res.Lines {
			ln = strings.TrimSpace(ln)
			if ln == "" {
				continue
			}
			res.Words = append(res.Words, strings.Fields(ln)...)
		}
		if len(res.Words) == 0 && res.Text != "" {
			res.Words = strings.Fields(res.Text)
		}
	}
	if len(res.Sentences) == 0 {
		if res.Text != "" {
			res.Sentences = splitSentences(res.Text)
		} else if len(res.Lines) > 0 {
			res.Sentences = append(res.Sentences, res.Lines...)
		}
	}
	if res.Lines == nil {
		res.Lines = []string{}
	}
	if res.Words == nil {
		res.Words = []string{}
	}
	if res.Sentences == nil {
		res.Sentences = []string{}
	}
}

func splitSentences(text string) []string {
	text = strings.TrimSpace(text)
	if text == "" {
		return nil
	}
	re := regexp.MustCompile(`[.!?؟\n]+`)
	parts := re.Split(text, -1)
	var out []string
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			out = append(out, p)
		}
	}
	if len(out) == 0 {
		return []string{text}
	}
	return out
}

func nonEmptyLines(text string) []string {
	var lines []string
	for _, ln := range strings.Split(text, "\n") {
		if strings.TrimSpace(ln) != "" {
			lines = append(lines, ln)
		}
	}
	return lines
}

func parseTableJSON(raw json.RawMessage) *parsedTable {
	if len(raw) == 0 || string(raw) == "null" {
		return nil
	}
	var obj parsedTable
	if err := json.Unmarshal(raw, &obj); err == nil && len(obj.Rows) > 0 {
		return &obj
	}
	var rows [][]string
	if err := json.Unmarshal(raw, &rows); err == nil && len(rows) > 0 {
		return &parsedTable{Rows: rows}
	}
	return nil
}

func trim(s string, n int) string {
	s = strings.TrimSpace(s)
	if len(s) <= n {
		return s
	}
	return s[:n]
}
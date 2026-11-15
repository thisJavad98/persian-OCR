package cursor

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
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
	return "cursor:" + s.cfg.CursorOCRModel
}

func (s *Service) Available() bool {
	if !s.cfg.OCRUseCursor {
		return false
	}
	if s.agentBinary() == "" {
		return false
	}
	if s.cfg.CursorAPIKey != "" {
		return true
	}
	return s.loggedIn()
}

func (s *Service) Status() Status {
	st := Status{
		Ready: s.Available(),
		Model: s.cfg.CursorOCRModel,
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
		return "cursor-agent CLI not found on PATH"
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

func (s *Service) Extract(parent context.Context, imagePath string, profile *handwriting.Profile) (*Result, error) {
	return s.extractWithRetry(parent, imagePath, s.cfg.CursorOCRRetries, profile)
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
	cmd := s.buildCommand(ctx, binary, root, prompt)
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

func (s *Service) extractWithRetry(parent context.Context, imagePath string, retries int, profile *handwriting.Profile) (*Result, error) {
	var last error
	attempts := retries + 1
	if attempts < 1 {
		attempts = 1
	}
	perAttempt := time.Duration(s.cfg.CursorOCRTimeout * float64(time.Second))

	for attempt := 0; attempt < attempts; attempt++ {
		if attempt > 0 {
			select {
			case <-parent.Done():
				return nil, friendlyError(parent.Err())
			case <-time.After(1500 * time.Millisecond):
			}
		}
		attemptCtx, cancel := context.WithTimeout(parent, perAttempt)
		res, err := s.extractOnce(attemptCtx, imagePath, profile)
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

func (s *Service) extractOnce(ctx context.Context, imagePath string, profile *handwriting.Profile) (*Result, error) {
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

	prompt := buildOCRPrompt(rel, profile)
	cmd := s.buildCommand(ctx, binary, root, prompt)

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
	}

	data.Engine = s.EngineLabel()
	data.Raw = trim(out, 8000)
	return data, nil
}

func (s *Service) buildCommand(ctx context.Context, binary, root, prompt string) *exec.Cmd {
	args := []string{
		"--mode", "ask",
		"-p",
		"--output-format", "text",
		"--model", s.cfg.CursorOCRModel,
		"--trust",
		"--workspace", root,
	}
	if s.cfg.CursorAPIKey != "" {
		args = append(args, "--api-key", s.cfg.CursorAPIKey)
	}
	args = append(args, prompt)
	return exec.CommandContext(ctx, binary, args...)
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
		return s.agentPath
	}
	for _, name := range []string{"cursor-agent", "agent"} {
		if p, err := exec.LookPath(name); err == nil {
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
	for i := len(matches) - 1; i >= 0; i-- {
		if data := decodeResult(matches[i]); data != nil && (data.Text != "" || len(data.Lines) > 0) {
			return data
		}
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
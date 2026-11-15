package cursor

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/javad-moghofei/persian-ocr/back/internal/config"
)

const ocrPrompt = `You are a world-class OCR engine for Persian/Farsi (including Nasta'liq), Arabic, and any document image.

Open and carefully read this image file:
%s

Transcribe EVERY visible character, word, digit, and punctuation exactly as written.
Do not summarize. Do not invent. Do not skip faint or edge text.

Return ONLY valid JSON (no markdown fences, no commentary):
{
  "text": "full page transcript with natural line breaks",
  "lines": ["line 1", "line 2"],
  "words": ["word1", "word2"],
  "sentences": ["sentence 1"],
  "confidence": 0.0
}

Rules:
- Persian/Arabic in LOGICAL reading order.
- Keep numbers, IDs, dates, Latin, and punctuation.
- lines = every visual text line top-to-bottom.
- words = tokens in reading order.
- sentences = grammatical sentences or clear phrases from the page.
- confidence is 0..1.
`

type Result struct {
	Text       string   `json:"text"`
	Lines      []string `json:"lines"`
	Words      []string `json:"words"`
	Sentences  []string `json:"sentences"`
	Confidence float64  `json:"confidence"`
	Engine     string   `json:"engine"`
	Raw        string   `json:"raw,omitempty"`
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

func (s *Service) Extract(ctx context.Context, imagePath string) (*Result, error) {
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

	prompt := fmt.Sprintf(ocrPrompt, rel)
	timeout := time.Duration(s.cfg.CursorOCRTimeout * float64(time.Second))
	cmd := s.buildCommand(ctx, binary, root, prompt, timeout)

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	cmd.Dir = root

	if err := cmd.Run(); err != nil {
		out := strings.TrimSpace(stdout.String())
		if out == "" {
			return nil, fmt.Errorf("cursor-agent failed: %s", trim(stderr.String(), 500))
		}
	}

	out := strings.TrimSpace(stdout.String())
	data := parseAgentJSON(out)
	if data.Text == "" && len(data.Lines) == 0 {
		cleaned := stripNoise(out)
		if cleaned == "" {
			return nil, fmt.Errorf("cursor-agent returned no OCR payload: %s", trim(out, 400))
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

func (s *Service) buildCommand(ctx context.Context, binary, root, prompt string, timeout time.Duration) *exec.Cmd {
	ctx, _ = context.WithTimeout(ctx, timeout)
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
	proc := exec.Command(binary, "status")
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
	if res.Text == "" && len(res.Lines) == 0 {
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
		cleaned = regexp.MustCompile(`(?s)\s*`+"```"+`$`).ReplaceAllString(cleaned, "")
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

func trim(s string, n int) string {
	s = strings.TrimSpace(s)
	if len(s) <= n {
		return s
	}
	return s[:n]
}

package cursor

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// TableStructure is the phase-1 layout hint (headers / grid detection).
type TableStructure struct {
	IsTable  bool     `json:"is_table"`
	Headers  []string `json:"headers"`
	ColCount int      `json:"col_count"`
}

const ocrPromptTableDetect = `Analyze image: %s (Persian/Arabic). Image was contrast-enhanced for OCR.
Phase 1 ONLY — do NOT transcribe data cells.

Decide: table / spreadsheet / printed grid / form with columns?
- If NO: {"is_table":false,"headers":[],"col_count":0}
- If YES: read TOP header row only; RTL visual order → headers[0] = rightmost column title.
  Exact header text (نام، تاریخ، مبلغ، ردیف، …). Set col_count = number of columns.

Return ONLY JSON: {"is_table":false,"headers":[],"col_count":0}`

const ocrPromptTableExtractPhase2 = `Phase 2 TABLE OCR image: %s — Persian RTL.

You already know the column structure (headers below). Transcribe ALL data rows into table.rows; empty="".
Do NOT change header spellings. rows must align with headers (same column count).

Return ONLY JSON:
{"is_table":true,"text":"","lines":[],"confidence":0.0,"table":{"headers":[],"rows":[[]]}}`

func (s *Service) tableTwoPhaseEnabled() bool {
	if v := strings.TrimSpace(os.Getenv("OCR_TABLE_TWO_PHASE")); v == "0" || strings.EqualFold(v, "false") {
		return false
	}
	return true
}

func (s *Service) detectTableStructure(ctx context.Context, imagePath string) (*TableStructure, error) {
	binary := s.agentBinary()
	if binary == "" {
		return nil, fmt.Errorf("cursor-agent not ready")
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
	prompt := fmt.Sprintf(ocrPromptTableDetect, rel)
	cmd := s.buildCommand(ctx, binary, root, prompt, s.cfg.OCRModel())
	cmd.Dir = root
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		if stdout.Len() == 0 {
			return nil, fmt.Errorf("%s", strings.TrimSpace(stderr.String()))
		}
	}
	out := stripNoise(stdout.String())
	var hint TableStructure
	if err := json.Unmarshal([]byte(out), &hint); err != nil {
		if parsed := parseTableDetectFromAgent(out); parsed != nil {
			return parsed, nil
		}
		return nil, fmt.Errorf("table detect parse failed")
	}
	cleanTableStructure(&hint)
	return &hint, nil
}

func parseTableDetectFromAgent(text string) *TableStructure {
	cleaned := stripNoise(text)
	matches := jsonObjectRe.FindAllString(cleaned, -1)
	for i := len(matches) - 1; i >= 0; i-- {
		var hint TableStructure
		if json.Unmarshal([]byte(matches[i]), &hint) == nil {
			cleanTableStructure(&hint)
			if hint.IsTable || len(hint.Headers) > 0 {
				return &hint
			}
		}
	}
	return nil
}

func cleanTableStructure(h *TableStructure) {
	if h == nil {
		return
	}
	var headers []string
	for _, c := range h.Headers {
		c = strings.TrimSpace(c)
		if c != "" {
			headers = append(headers, c)
		}
	}
	h.Headers = headers
	if h.ColCount < len(headers) {
		h.ColCount = len(headers)
	}
	if len(headers) >= 2 {
		h.IsTable = true
	}
}

func (s *Service) detectTimeout() time.Duration {
	sec := 28.0
	if onVercel() {
		sec = 22.0
	}
	if s.cfg.CursorOCRTimeout > 0 && s.cfg.CursorOCRTimeout*0.35 < sec {
		sec = s.cfg.CursorOCRTimeout * 0.35
	}
	if sec < 18 {
		sec = 18
	}
	return time.Duration(sec * float64(time.Second))
}
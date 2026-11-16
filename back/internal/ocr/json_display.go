package ocr

import (
	"encoding/json"
	"strings"
)

// LooksLikeAgentJSON reports raw agent dumps shown to users by mistake.
func LooksLikeAgentJSON(text string) bool {
	text = strings.TrimSpace(text)
	if text == "" || !strings.HasPrefix(text, "{") {
		return false
	}
	var raw map[string]json.RawMessage
	if err := json.Unmarshal([]byte(text), &raw); err != nil {
		return false
	}
	_, hasTable := raw["table"]
	_, hasLines := raw["lines"]
	_, hasIsTable := raw["is_table"]
	return hasTable || hasLines || hasIsTable
}

// PlainTextFromAgentJSON returns human-readable text from a JSON OCR blob.
func PlainTextFromAgentJSON(text string) string {
	text = strings.TrimSpace(text)
	if text == "" {
		return ""
	}
	var raw map[string]json.RawMessage
	if err := json.Unmarshal([]byte(text), &raw); err != nil {
		return ""
	}
	var plain string
	_ = json.Unmarshal(raw["text"], &plain)
	plain = strings.TrimSpace(plain)
	if plain != "" && !LooksLikeAgentJSON(plain) {
		return plain
	}
	if tbl, ok := raw["table"]; ok && tbl != nil {
		var headers []string
		var rows [][]string
		var obj struct {
			Headers []string   `json:"headers"`
			Rows    [][]string `json:"rows"`
		}
		if err := json.Unmarshal(tbl, &obj); err == nil {
			headers, rows = obj.Headers, obj.Rows
		}
		if len(rows) > 0 {
			if norm := FinalizeTable(headers, rows); norm != nil {
				return TablePlainText(norm.Headers, norm.Rows)
			}
		}
	}
	var lines []string
	_ = json.Unmarshal(raw["lines"], &lines)
	if len(lines) > 0 {
		return strings.Join(lines, "\n")
	}
	return ""
}
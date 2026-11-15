package ocr

import "strings"

// TableData is structured grid OCR when the source image is tabular.
type TableData struct {
	IsTable bool       `json:"is_table"`
	Headers []string   `json:"headers,omitempty"`
	Rows    [][]string `json:"rows"`
}

// NormalizeTable coerces Cursor JSON into a grid; returns nil if empty.
func NormalizeTable(isTable bool, headers []string, rows [][]string) *TableData {
	cleaned := cleanRows(rows)
	if len(cleaned) == 0 {
		return nil
	}
	h := cleanCells(headers)
	if !isTable && !looksTabular(cleaned) {
		return nil
	}
	return &TableData{
		IsTable: true,
		Headers: h,
		Rows:    cleaned,
	}
}

func looksTabular(rows [][]string) bool {
	if len(rows) < 2 {
		return len(rows) == 1 && len(rows[0]) > 1
	}
	widths := map[int]int{}
	for _, row := range rows {
		if len(row) < 2 {
			continue
		}
		widths[len(row)]++
	}
	for _, n := range widths {
		if n >= 2 {
			return true
		}
	}
	return len(rows[0]) >= 2 && len(rows) >= 2
}

func cleanRows(rows [][]string) [][]string {
	var out [][]string
	for _, row := range rows {
		cells := cleanCells(row)
		if len(cells) == 0 {
			continue
		}
		if allEmpty(cells) {
			continue
		}
		out = append(out, cells)
	}
	return out
}

func cleanCells(cells []string) []string {
	out := make([]string, 0, len(cells))
	for _, c := range cells {
		c = strings.TrimSpace(c)
		out = append(out, c)
	}
	return out
}

func allEmpty(cells []string) bool {
	for _, c := range cells {
		if c != "" {
			return false
		}
	}
	return true
}
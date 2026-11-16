package ocr

import (
	"regexp"
	"strings"
	"unicode"
)

// InferTableFromText builds a grid when the model returned lines/text but omitted table JSON.
func InferTableFromText(text string, lines []string) *TableData {
	if len(lines) == 0 && strings.TrimSpace(text) != "" {
		lines = splitNonEmpty(text)
	}
	if len(lines) < 1 {
		return nil
	}
	rows := make([][]string, 0, len(lines))
	colCounts := map[int]int{}
	for _, ln := range lines {
		cells := splitTableLine(ln)
		if len(cells) < 2 {
			continue
		}
		rows = append(rows, cells)
		colCounts[len(cells)]++
	}
	if len(rows) < 1 {
		return nil
	}
	bestCols, bestN := 0, 0
	for cols, n := range colCounts {
		if n > bestN || (n == bestN && cols > bestCols) {
			bestCols, bestN = cols, n
		}
	}
	if bestCols < 2 || bestN < 1 {
		return nil
	}
	// Need at least 2 rows with similar width, or one header + 2 data rows.
	if bestN < 2 && len(rows) < 2 {
		return nil
	}
	normalized := make([][]string, 0, len(rows))
	for _, row := range rows {
		if len(row) < 2 {
			continue
		}
		if len(row) != bestCols && len(row) > bestCols {
			row = row[:bestCols]
		}
		for len(row) < bestCols {
			row = append(row, "")
		}
		if len(row) == bestCols {
			normalized = append(normalized, row)
		}
	}
	if len(normalized) == 0 {
		return nil
	}
	var headers []string
	data := normalized
	if len(normalized) >= 1 && RowLikelyHeaderRow(normalized[0], normalized[1:]) {
		headers = append([]string(nil), normalized[0]...)
		data = normalized[1:]
	}
	return NormalizeTable(true, headers, data)
}

func splitNonEmpty(text string) []string {
	var out []string
	for _, ln := range strings.Split(text, "\n") {
		if t := strings.TrimSpace(ln); t != "" {
			out = append(out, t)
		}
	}
	return out
}

var multiSpace = regexp.MustCompile(`\s{2,}`)

func splitTableLine(line string) []string {
	line = strings.TrimSpace(line)
	if line == "" {
		return nil
	}
	if strings.Contains(line, "\t") {
		return cleanCells(strings.Split(line, "\t"))
	}
	if strings.Contains(line, "|") {
		parts := strings.Split(line, "|")
		var cells []string
		for _, p := range parts {
			p = strings.TrimSpace(p)
			if p != "" {
				cells = append(cells, p)
			}
		}
		if len(cells) >= 2 {
			return cells
		}
	}
	if strings.Contains(line, "؛") && strings.Count(line, "؛") >= 1 {
		parts := strings.Split(line, "؛")
		if len(parts) >= 2 {
			return cleanCells(parts)
		}
	}
	if multiSpace.MatchString(line) {
		return cleanCells(multiSpace.Split(line, -1))
	}
	return nil
}

func TablePlainText(headers []string, rows [][]string) string {
	var b strings.Builder
	if len(headers) > 0 {
		b.WriteString(strings.Join(headers, " | "))
		b.WriteByte('\n')
	}
	for _, row := range rows {
		b.WriteString(strings.Join(row, " | "))
		b.WriteByte('\n')
	}
	return strings.TrimSpace(b.String())
}

func StripTableSeparators(s string) string {
	return strings.Map(func(r rune) rune {
		if unicode.IsControl(r) && r != '\n' && r != '\t' {
			return -1
		}
		return r
	}, s)
}
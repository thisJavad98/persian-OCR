package ocr

import (
	"regexp"
	"strings"
	"unicode"
)

var headerKeywordRe = regexp.MustCompile(`(?i)(ردیف|رديف|نام|کد|كد|تاریخ|تاريخ|مبلغ|قیمت|قيمت|شماره|شهر|سن|جنسیت|جنسيت|وضعیت|وضعيت|شرح|توضیح|توضيح|unit|id|#)`)

// FinalizeTable aligns columns, extracts headers, and removes duplicate header rows.
func FinalizeTable(headers []string, rows [][]string) *TableData {
	rows = cleanRows(rows)
	h := cleanCells(headers)

	if len(h) == 0 && len(rows) > 0 {
		if RowLikelyHeaderRow(rows[0], rows[1:]) {
			h = cleanCells(rows[0])
			rows = rows[1:]
		}
	}
	if len(h) > 0 && len(rows) > 0 && rowsSimilar(h, rows[0]) {
		rows = rows[1:]
	}

	ncol := columnTarget(h, rows)
	if ncol < 2 && len(rows) > 0 {
		ncol = maxRowWidth(rows)
	}
	if ncol < 2 {
		return nil
	}

	h = padOrTrimRow(h, ncol)
	aligned := make([][]string, 0, len(rows))
	for _, row := range rows {
		row = padOrTrimRow(cleanCells(row), ncol)
		if !allEmpty(row) {
			aligned = append(aligned, row)
		}
	}
	if len(aligned) == 0 && len(h) == 0 {
		return nil
	}

	return &TableData{IsTable: true, Headers: h, Rows: aligned}
}

func NormalizeTable(isTable bool, headers []string, rows [][]string) *TableData {
	t := FinalizeTable(headers, rows)
	if t == nil {
		return nil
	}
	if !isTable && len(t.Headers) == 0 && !looksTabular(t.Rows) {
		return nil
	}
	return t
}

func columnTarget(headers []string, rows [][]string) int {
	if len(headers) > 0 {
		return len(headers)
	}
	return dominantWidth(rows)
}

func dominantWidth(rows [][]string) int {
	counts := map[int]int{}
	best, bestN := 0, 0
	for _, row := range rows {
		n := len(cleanCells(row))
		if n < 2 {
			continue
		}
		counts[n]++
		if counts[n] > bestN {
			bestN = counts[n]
			best = n
		}
	}
	if best > 0 {
		return best
	}
	return maxRowWidth(rows)
}

func maxRowWidth(rows [][]string) int {
	m := 0
	for _, row := range rows {
		if n := len(row); n > m {
			m = n
		}
	}
	return m
}

func padOrTrimRow(row []string, ncol int) []string {
	if ncol <= 0 {
		return row
	}
	if len(row) > ncol {
		row = row[:ncol]
	}
	for len(row) < ncol {
		row = append(row, "")
	}
	return row
}

func rowsSimilar(a, b []string) bool {
	if len(a) == 0 || len(b) == 0 {
		return false
	}
	n := len(a)
	if len(b) < n {
		n = len(b)
	}
	same := 0
	for i := 0; i < n; i++ {
		if strings.EqualFold(strings.TrimSpace(a[i]), strings.TrimSpace(b[i])) {
			same++
		}
	}
	return same >= n-1 && same >= 2
}

// RowLikelyHeaderRow scores the first row as column titles vs data.
func RowLikelyHeaderRow(header []string, data [][]string) bool {
	cells := cleanCells(header)
	if len(cells) < 2 {
		return false
	}
	nonEmpty := 0
	keywordHits := 0
	longCells := 0
	numeric := 0
	for _, c := range cells {
		c = strings.TrimSpace(c)
		if c == "" {
			continue
		}
		nonEmpty++
		if headerKeywordRe.MatchString(c) {
			keywordHits++
		}
		if len([]rune(c)) > 40 {
			longCells++
		}
		if mostlyDigits(c) {
			numeric++
		}
	}
	if nonEmpty < 2 {
		return false
	}
	if keywordHits >= 1 {
		return true
	}
	if longCells > 0 {
		return false
	}
	if numeric >= nonEmpty {
		return false
	}
	if len(data) == 0 {
		return nonEmpty >= 2 && numeric == 0
	}
	return headerRowShorterThanData(cells, data)
}

func headerRowShorterThanData(header []string, data [][]string) bool {
	avgH := avgRuneLen(header)
	var sum float64
	var n int
	for _, row := range data {
		if len(row) < 2 {
			continue
		}
		sum += avgRuneLen(row)
		n++
	}
	if n == 0 {
		return avgH <= 24
	}
	return avgH+6 < sum/float64(n)
}

func avgRuneLen(cells []string) float64 {
	var sum, n int
	for _, c := range cells {
		c = strings.TrimSpace(c)
		if c == "" {
			continue
		}
		sum += len([]rune(c))
		n++
	}
	if n == 0 {
		return 0
	}
	return float64(sum) / float64(n)
}

func mostlyDigits(s string) bool {
	s = strings.TrimSpace(s)
	if s == "" {
		return false
	}
	var digits, other int
	for _, r := range s {
		if unicode.IsDigit(r) || r == '.' || r == ',' || r == '-' || r == '/' {
			digits++
		} else if !unicode.IsSpace(r) {
			other++
		}
	}
	return digits > 0 && other <= 1
}
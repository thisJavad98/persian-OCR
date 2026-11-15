package handwriting

import (
	"bytes"
	"fmt"
	"strings"

	"github.com/xuri/excelize/v2"
)

// ParseReferenceGrid reads the first sheet into a compact text grid for prompts.
func ParseReferenceGrid(data []byte) (string, error) {
	f, err := excelize.OpenReader(bytes.NewReader(data))
	if err != nil {
		return "", fmt.Errorf("فایل اکسل خوانده نشد")
	}
	defer func() { _ = f.Close() }()
	sheets := f.GetSheetList()
	if len(sheets) == 0 {
		return "", fmt.Errorf("اکسل بدون شیت است")
	}
	rows, err := f.GetRows(sheets[0])
	if err != nil {
		return "", err
	}
	var b strings.Builder
	limit := 80
	for i, row := range rows {
		if i >= limit {
			b.WriteString("…\n")
			break
		}
		cells := make([]string, 0, len(row))
		empty := true
		for _, c := range row {
			c = strings.TrimSpace(c)
			if c != "" {
				empty = false
			}
			cells = append(cells, c)
		}
		if empty {
			continue
		}
		b.WriteString(strings.Join(cells, " | "))
		b.WriteByte('\n')
	}
	out := strings.TrimSpace(b.String())
	if out == "" {
		return "", fmt.Errorf("اکسل مرجع خالی است")
	}
	if len(out) > 12000 {
		out = out[:12000] + "\n…"
	}
	return out, nil
}
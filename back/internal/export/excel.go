package export

import (
	"bytes"
	"fmt"
	"math"

	"github.com/javad-moghofei/persian-ocr/back/internal/ocr"
	"github.com/xuri/excelize/v2"
)

func BuildExcel(filename, fullText string, lines []map[string]any, words []map[string]any, sentences []string, table *ocr.TableData, confidence *float64, engine string) ([]byte, error) {
	f := excelize.NewFile()
	defer func() { _ = f.Close() }()

	firstSheet := "متن"
	sheetIndex := 0
	if table != nil && len(table.Rows) > 0 {
		tableSheet := "جدول"
		_ = f.SetSheetName("Sheet1", tableSheet)
		_ = f.SetSheetView(tableSheet, 0, &excelize.ViewOptions{RightToLeft: boolPtr(true)})
		writeTableSheet(f, tableSheet, table)
		firstSheet = tableSheet
		sheetIndex = 1
	} else {
		_ = f.SetSheetName("Sheet1", firstSheet)
	}

	textSheet := "متن"
	if sheetIndex == 0 {
		_ = f.SetSheetName("Sheet1", textSheet)
	} else {
		_, _ = f.NewSheet(textSheet)
	}
	_ = f.SetSheetView(textSheet, 0, &excelize.ViewOptions{RightToLeft: boolPtr(true)})
	_ = f.SetCellValue(textSheet, "A1", "فایل")
	_ = f.SetCellValue(textSheet, "B1", filename)
	_ = f.SetCellValue(textSheet, "A2", "موتور")
	_ = f.SetCellValue(textSheet, "B2", engine)
	_ = f.SetCellValue(textSheet, "A3", "اطمینان")
	if confidence != nil {
		_ = f.SetCellValue(textSheet, "B3", fmt.Sprintf("%d%%", int(math.Round(*confidence*100))))
	}
	_ = f.SetCellValue(textSheet, "A5", "متن کامل")
	_ = f.SetCellValue(textSheet, "A6", fullText)
	_ = f.SetColWidth(textSheet, "A", "A", 18)
	_ = f.SetColWidth(textSheet, "B", "B", 80)

	lineSheet := "خطوط"
	_, _ = f.NewSheet(lineSheet)
	_ = f.SetSheetView(lineSheet, 0, &excelize.ViewOptions{RightToLeft: boolPtr(true)})
	_ = f.SetSheetRow(lineSheet, "A1", &[]interface{}{"#", "خط", "اطمینان"})
	row := 2
	for i, item := range lines {
		text, _ := item["text"].(string)
		if text == "" {
			continue
		}
		conf := ""
		if c, ok := item["confidence"].(float64); ok {
			conf = fmt.Sprintf("%d%%", int(math.Round(c*100)))
		}
		cell := fmt.Sprintf("A%d", row)
		_ = f.SetSheetRow(lineSheet, cell, &[]interface{}{i + 1, text, conf})
		row++
	}
	_ = f.SetColWidth(lineSheet, "B", "B", 80)

	sentSheet := "جملات"
	_, _ = f.NewSheet(sentSheet)
	_ = f.SetSheetView(sentSheet, 0, &excelize.ViewOptions{RightToLeft: boolPtr(true)})
	_ = f.SetSheetRow(sentSheet, "A1", &[]interface{}{"#", "جمله"})
	srow := 2
	for i, s := range sentences {
		if s == "" {
			continue
		}
		cell := fmt.Sprintf("A%d", srow)
		_ = f.SetSheetRow(sentSheet, cell, &[]interface{}{i + 1, s})
		srow++
	}
	_ = f.SetColWidth(sentSheet, "B", "B", 80)

	wordSheet := "واژه‌ها"
	_, _ = f.NewSheet(wordSheet)
	_ = f.SetSheetView(wordSheet, 0, &excelize.ViewOptions{RightToLeft: boolPtr(true)})
	_ = f.SetSheetRow(wordSheet, "A1", &[]interface{}{"#", "واژه", "اطمینان"})
	wrow := 2
	for i, item := range words {
		text, _ := item["text"].(string)
		if text == "" {
			continue
		}
		conf := ""
		if c, ok := item["confidence"].(float64); ok {
			conf = fmt.Sprintf("%d%%", int(math.Round(c*100)))
		}
		cell := fmt.Sprintf("A%d", wrow)
		_ = f.SetSheetRow(wordSheet, cell, &[]interface{}{i + 1, text, conf})
		wrow++
	}
	_ = f.SetColWidth(wordSheet, "B", "B", 40)

	if idx, err := f.GetSheetIndex(firstSheet); err == nil && idx >= 0 {
		f.SetActiveSheet(idx)
	}

	buf, err := f.WriteToBuffer()
	if err != nil {
		return nil, err
	}
	return bytes.Clone(buf.Bytes()), nil
}

func writeTableSheet(f *excelize.File, sheet string, table *ocr.TableData) {
	row := 1
	if len(table.Headers) > 0 {
		hdr := make([]interface{}, len(table.Headers))
		for i, h := range table.Headers {
			hdr[i] = h
		}
		_ = f.SetSheetRow(sheet, fmt.Sprintf("A%d", row), &hdr)
		row++
	}
	for _, dataRow := range table.Rows {
		cells := make([]interface{}, len(dataRow))
		for i, c := range dataRow {
			cells[i] = c
		}
		_ = f.SetSheetRow(sheet, fmt.Sprintf("A%d", row), &cells)
		row++
	}
	cols := 1
	if len(table.Headers) > 0 {
		cols = len(table.Headers)
	} else if len(table.Rows) > 0 {
		cols = len(table.Rows[0])
	}
	if cols > 0 {
		endCol, _ := excelize.ColumnNumberToName(cols)
		_ = f.SetColWidth(sheet, "A", endCol, 22)
	}
}

func boolPtr(b bool) *bool { return &b }
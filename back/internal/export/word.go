package export

import (
	"archive/zip"
	"bytes"
	"fmt"
	"math"
	"strings"
)

// Minimal Word 2007+ document (RTL-friendly paragraphs).
func BuildWord(filename, fullText string, lines, words, sentences []string, engine string, confidence *float64) ([]byte, error) {
	var meta []string
	meta = append(meta, "خروجی OCR — خط‌خوان")
	meta = append(meta, fmt.Sprintf("فایل: %s", filename))
	if engine != "" {
		meta = append(meta, fmt.Sprintf("موتور: %s", engine))
	}
	if confidence != nil {
		meta = append(meta, fmt.Sprintf("اطمینان: %d٪", int(math.Round(*confidence*100))))
	}

	body := fullText
	if body == "" {
		body = strings.Join(lines, "\n")
	}
	if body == "" {
		body = "متنی یافت نشد"
	}

	var paras []string
	for _, m := range meta {
		paras = append(paras, m)
	}
	paras = append(paras, "")
	paras = append(paras, "متن کامل")
	for _, block := range strings.Split(body, "\n") {
		if strings.TrimSpace(block) != "" {
			paras = append(paras, block)
		}
	}
	if len(sentences) > 0 {
		paras = append(paras, "", "جملات")
		for _, s := range sentences {
			if strings.TrimSpace(s) != "" {
				paras = append(paras, s)
			}
		}
	}
	if len(words) > 0 {
		paras = append(paras, "", "واژه‌ها", strings.Join(words, "، "))
	}

	documentXML := buildDocumentXML(paras)
	contentTypes := `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>`
	rels := `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>`
	docRels := `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>`

	buf := new(bytes.Buffer)
	zw := zip.NewWriter(buf)
	for name, data := range map[string]string{
		"[Content_Types].xml":          contentTypes,
		"_rels/.rels":                  rels,
		"word/document.xml":            documentXML,
		"word/_rels/document.xml.rels": docRels,
	} {
		w, err := zw.Create(name)
		if err != nil {
			return nil, err
		}
		if _, err := w.Write([]byte(data)); err != nil {
			return nil, err
		}
	}
	if err := zw.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

func buildDocumentXML(paragraphs []string) string {
	var b strings.Builder
	b.WriteString(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>`)
	b.WriteString(`<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">`)
	b.WriteString(`<w:body>`)
	for _, p := range paragraphs {
		b.WriteString(`<w:p><w:pPr><w:bidi/><w:jc w:val="right"/></w:pPr><w:r><w:rPr><w:rtl/></w:rPr><w:t>`)
		b.WriteString(xmlEscape(p))
		b.WriteString(`</w:t></w:r></w:p>`)
	}
	b.WriteString(`</w:body></w:document>`)
	return b.String()
}

func xmlEscape(s string) string {
	s = strings.ReplaceAll(s, "&", "&amp;")
	s = strings.ReplaceAll(s, "<", "&lt;")
	s = strings.ReplaceAll(s, ">", "&gt;")
	s = strings.ReplaceAll(s, `"`, "&quot;")
	return s
}

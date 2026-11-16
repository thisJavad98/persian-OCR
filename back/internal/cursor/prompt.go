package cursor

import (
	"fmt"
	"strings"

	"github.com/javad-moghofei/persian-ocr/back/internal/handwriting"
)

func buildOCRPrompt(imageRel string, profile *handwriting.Profile, fast bool, tableLayout bool) string {
	var base string
	if tableLayout {
		base = fmt.Sprintf(ocrPromptTable, imageRel)
	} else if fast {
		base = fmt.Sprintf(ocrPromptFast, imageRel)
	} else {
		base = fmt.Sprintf(ocrPrompt, imageRel)
	}
	if profile == nil || !profile.Active {
		return base
	}
	var b strings.Builder
	b.WriteString(base)
	b.WriteByte('\n')
	b.WriteString("Handwriting profile—match reference style:\n")
	if profile.ImageRelPath != "" {
		b.WriteString("ref_image: ")
		b.WriteString(profile.ImageRelPath)
		b.WriteByte('\n')
	}
	grid := profile.ReferenceGrid
	limit := 6000
	if fast || tableLayout {
		limit = 900
	}
	if len(grid) > limit {
		grid = grid[:limit] + "…"
	}
	if grid != "" {
		b.WriteString("ref_excel:\n")
		b.WriteString(grid)
		b.WriteByte('\n')
	}
	notes := profile.StyleNotes
	noteLimit := 600
	if fast || tableLayout {
		noteLimit = 280
	}
	if len(notes) > noteLimit {
		notes = notes[:noteLimit] + "…"
	}
	if notes != "" {
		b.WriteString("style_notes: ")
		b.WriteString(notes)
		b.WriteByte('\n')
	}
	return b.String()
}

const studyPromptTpl = `You are calibrating OCR for one user's handwriting.

Open and study this sample image:
%s

The user says this Excel is the CORRECT extraction for that sample:
%s

Return ONLY JSON:
{"ready":true,"style_notes":"short notes: letter forms, slant, dot placement, common confusions, table layout habits"}`

func buildStudyPrompt(sampleRel, referenceGrid string) string {
	grid := referenceGrid
	if len(grid) > 6000 {
		grid = grid[:6000] + "\n…"
	}
	return fmt.Sprintf(studyPromptTpl, sampleRel, grid)
}
package cursor

import (
	"fmt"
	"strings"

	"github.com/javad-moghofei/persian-ocr/back/internal/handwriting"
)

func buildOCRPrompt(imageRel string, profile *handwriting.Profile) string {
	base := fmt.Sprintf(ocrPrompt, imageRel)
	if profile == nil || !profile.Active {
		return base
	}
	var b strings.Builder
	b.WriteString(base)
	b.WriteString("\n\n")
	b.WriteString("USER HANDWRITING PROFILE (trained; match this style precisely):\n")
	if profile.ImageRelPath != "" {
		b.WriteString("Reference handwriting sample image: ")
		b.WriteString(profile.ImageRelPath)
		b.WriteByte('\n')
	}
	if profile.ReferenceGrid != "" {
		b.WriteString("Reference expected extraction (from user's Excel):\n")
		b.WriteString(profile.ReferenceGrid)
		b.WriteByte('\n')
	}
	if profile.StyleNotes != "" {
		b.WriteString("Style notes:\n")
		b.WriteString(profile.StyleNotes)
		b.WriteByte('\n')
	}
	b.WriteString("Transcribe new images in the same letter shapes, spacing, and vocabulary habits as the reference. Prefer the reference Excel structure when the page layout matches.")
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
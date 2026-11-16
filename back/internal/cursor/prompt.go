package cursor

import (
	"fmt"
	"strings"

	"github.com/javad-moghofei/persian-ocr/back/internal/handwriting"
)

func buildOCRPrompt(imageRel string, profile *handwriting.Profile, fast bool, tableLayout bool, structure *TableStructure) string {
	var base string
	if tableLayout && structure != nil && (structure.IsTable || len(structure.Headers) > 0) {
		base = fmt.Sprintf(ocrPromptTableExtractPhase2, imageRel)
		base += formatStructureHint(structure)
	} else if tableLayout {
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
	if tableLayout {
		b.WriteString("Handwriting phase: transcribe cells matching the user's script (style_notes + ref_excel).\n")
	} else {
		b.WriteString("Handwriting profile—match reference style:\n")
	}
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

func formatStructureHint(structure *TableStructure) string {
	if structure == nil {
		return ""
	}
	var b strings.Builder
	b.WriteString("\nLOCKED STRUCTURE (from phase 1):\n")
	b.WriteString(fmt.Sprintf("is_table=%v col_count=%d\n", structure.IsTable, structure.ColCount))
	if len(structure.Headers) > 0 {
		b.WriteString("headers: ")
		for i, h := range structure.Headers {
			if i > 0 {
				b.WriteString(" | ")
			}
			b.WriteString(h)
		}
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
package imageutil

import (
	"image"

	"github.com/disintegration/imaging"
)

// enhanceForOCR improves legibility for AI (forms/tables benefit most).
func enhanceForOCR(img image.Image, tableMode bool) image.Image {
	out := imaging.Clone(img)
	out = imaging.AdjustContrast(out, 22)
	if tableMode {
		out = imaging.AdjustContrast(out, 8)
		out = imaging.Sharpen(out, 1.05)
		out = imaging.AdjustGamma(out, 0.92)
	} else {
		out = imaging.Sharpen(out, 0.65)
	}
	return out
}

func resizeForOCR(img image.Image, w, h, maxSide int, tableMode bool) image.Image {
	if w <= 0 || h <= 0 {
		return img
	}
	maxDim := w
	if h > maxDim {
		maxDim = h
	}
	scale := float64(maxSide) / float64(maxDim)
	if tableMode {
		if scale > 2.5 {
			scale = 2.5
		}
		if scale < 1 && maxDim < maxSide {
			scale = float64(maxSide) / float64(maxDim)
		}
	} else if scale > 1 {
		scale = 1
	}
	if scale <= 1.001 && scale >= 0.999 {
		return img
	}
	nw := max(1, int(float64(w)*scale+0.5))
	nh := max(1, int(float64(h)*scale+0.5))
	filter := imaging.Lanczos
	if !tableMode && scale < 1 {
		filter = imaging.Box
	}
	return imaging.Resize(img, nw, nh, filter)
}
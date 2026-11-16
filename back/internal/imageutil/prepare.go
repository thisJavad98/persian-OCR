package imageutil

import (
	"bytes"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	_ "image/png"
	"os"
	"path/filepath"

	"github.com/disintegration/imaging"
	_ "golang.org/x/image/bmp"
	_ "golang.org/x/image/tiff"
	_ "golang.org/x/image/webp"
)

// PrepareToTemp decodes image bytes, enhances for OCR, resizes, writes a temp JPEG.
func PrepareToTemp(workspace string, raw []byte, maxSide, jpegQuality int, tableMode bool) (path string, cleanup func(), err error) {
	if jpegQuality < 50 || jpegQuality > 95 {
		jpegQuality = 78
	}
	if tableMode && jpegQuality < 82 {
		jpegQuality = 82
	}
	img, _, err := image.Decode(bytes.NewReader(raw))
	if err != nil {
		return "", nil, err
	}

	bounds := img.Bounds()
	w, h := bounds.Dx(), bounds.Dy()
	if minSide := 640; tableMode && max(w, h) < minSide && maxSide < minSide {
		maxSide = minSide
	}
	img = resizeForOCR(img, w, h, maxSide, tableMode)
	img = enhanceForOCR(img, tableMode)

	scratch := filepath.Join(workspace, ".scratch")
	if err := os.MkdirAll(scratch, 0o700); err != nil {
		return "", nil, err
	}
	f, err := os.CreateTemp(scratch, "ocr-*.jpg")
	if err != nil {
		return "", nil, err
	}
	path = f.Name()
	if err := imaging.Encode(f, img, imaging.JPEG, imaging.JPEGQuality(jpegQuality)); err != nil {
		_ = f.Close()
		_ = os.Remove(path)
		return "", nil, err
	}
	_ = f.Close()
	cleanup = func() { _ = os.Remove(path) }
	return path, cleanup, nil
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func min(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}
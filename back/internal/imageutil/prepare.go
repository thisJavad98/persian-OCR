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

// PrepareToTemp decodes image bytes, resizes, writes a temporary JPEG under workspace/.scratch, and returns cleanup.
func PrepareToTemp(workspace string, raw []byte, maxSide int) (path string, cleanup func(), err error) {
	img, _, err := image.Decode(bytes.NewReader(raw))
	if err != nil {
		return "", nil, err
	}

	bounds := img.Bounds()
	w, h := bounds.Dx(), bounds.Dy()
	scale := min(1.0, float64(maxSide)/float64(max(w, h)))
	if scale < 1.0 {
		nw := max(1, int(float64(w)*scale))
		nh := max(1, int(float64(h)*scale))
		filter := imaging.Lanczos
		if scale < 0.75 {
			filter = imaging.Linear
		}
		img = imaging.Resize(img, nw, nh, filter)
	}

	scratch := filepath.Join(workspace, ".scratch")
	if err := os.MkdirAll(scratch, 0o700); err != nil {
		return "", nil, err
	}
	f, err := os.CreateTemp(scratch, "ocr-*.jpg")
	if err != nil {
		return "", nil, err
	}
	path = f.Name()
	if err := imaging.Encode(f, img, imaging.JPEG, imaging.JPEGQuality(85)); err != nil {
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
package config

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/javad-moghofei/persian-ocr/back/internal/runtime"
	"github.com/joho/godotenv"
)

type Config struct {
	CORSOrigins      []string
	OCRMaxImageSide  int
	OCRFastMaxSide   int
	OCRTableMaxSide  int
	OCRJPEGQuality   int
	OCRTableJPEGQuality int
	OCRFast          bool
	Host             string
	Port             string
	OCRUseCursor     bool
	CursorOCRModel      string
	CursorOCRFastModel  string
	CursorOCRTimeout float64
	CursorOCRRetries int
	CursorAPIKey     string
	AuthUsername     string
	AuthPassword     string
	SessionSecret    string
	HandwritingDB    string
	DatabaseURL      string
}

func Load() (*Config, error) {
	_ = godotenv.Load()

	useCursor := os.Getenv("OCR_USE_CURSOR")
	if useCursor == "" {
		useCursor = "1"
	}

	maxSide := 1024
	if v := strings.TrimSpace(os.Getenv("OCR_MAX_IMAGE_SIDE")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			maxSide = n
		}
	}

	fastMaxSide := 1024
	if v := strings.TrimSpace(os.Getenv("OCR_FAST_MAX_SIDE")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			fastMaxSide = n
		}
	}

	tableMaxSide := 1120
	if v := strings.TrimSpace(os.Getenv("OCR_TABLE_MAX_SIDE")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			tableMaxSide = n
		}
	}

	jpegQ := 78
	tableJpegQ := 84
	if v := strings.TrimSpace(os.Getenv("OCR_JPEG_QUALITY")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n >= 50 && n <= 95 {
			jpegQ = n
		}
	}
	if v := strings.TrimSpace(os.Getenv("OCR_TABLE_JPEG_QUALITY")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n >= 50 && n <= 95 {
			tableJpegQ = n
		}
	}

	ocrFast := os.Getenv("OCR_FAST") != "0"

	timeout := 420.0
	if v := strings.TrimSpace(os.Getenv("CURSOR_OCR_TIMEOUT")); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil && f > 0 {
			timeout = f
		}
	}

	retries := 1
	if v := strings.TrimSpace(os.Getenv("CURSOR_OCR_RETRIES")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n >= 0 {
			retries = n
		}
	}

	model := strings.TrimSpace(os.Getenv("CURSOR_OCR_MODEL"))
	if model == "" {
		model = strings.TrimSpace(os.Getenv("CURSOR_MODEL"))
	}
	if model == "" {
		model = "composer-2.5"
	}
	fastModel := strings.TrimSpace(os.Getenv("CURSOR_OCR_FAST_MODEL"))

	origins := strings.TrimSpace(os.Getenv("CORS_ORIGINS"))
	if origins == "" {
		origins = "http://localhost:5173,http://127.0.0.1:5173"
	}

	hwDB := strings.TrimSpace(os.Getenv("HANDWRITING_DB_PATH"))
	dbURL := strings.TrimSpace(os.Getenv("DATABASE_URL"))

	if runtime.Serverless() {
		ocrFast = true
		if retries > 0 {
			retries = 0
		}
		if timeout > 200 {
			timeout = 200
		}
		if maxSide > 768 {
			maxSide = 768
		}
		if fastMaxSide > 768 {
			fastMaxSide = 768
		}
		if tableMaxSide > 896 {
			tableMaxSide = 896
		}
		if jpegQ > 72 {
			jpegQ = 72
		}
		if tableJpegQ > 80 {
			tableJpegQ = 80
		}
	}

	return &Config{
		CORSOrigins:      splitCSV(origins),
		OCRMaxImageSide:     maxSide,
		OCRFastMaxSide:      fastMaxSide,
		OCRTableMaxSide:     tableMaxSide,
		OCRJPEGQuality:      jpegQ,
		OCRTableJPEGQuality: tableJpegQ,
		OCRFast:             ocrFast,
		CursorOCRFastModel:  fastModel,
		Host:             envOr("HOST", "0.0.0.0"),
		Port:             envOr("PORT", "8000"),
		OCRUseCursor:     useCursor != "0",
		CursorOCRModel:   model,
		CursorOCRTimeout: timeout,
		CursorOCRRetries: retries,
		CursorAPIKey:     strings.TrimSpace(os.Getenv("CURSOR_API_KEY")),
		AuthUsername:     envOr("AUTH_USERNAME", "alifaghihi123"),
		AuthPassword:     envOr("AUTH_PASSWORD", "AliFaghihi@123"),
		SessionSecret:    envOr("SESSION_SECRET", ""),
		HandwritingDB:    hwDB,
		DatabaseURL:      dbURL,
	}, nil
}

func (c *Config) OCRModel() string {
	if c.OCRFast && c.CursorOCRFastModel != "" {
		return c.CursorOCRFastModel
	}
	return c.CursorOCRModel
}

// ModelForUpload prefers the fast model; set CURSOR_OCR_TABLE_MODEL for slower table quality.
func (c *Config) ModelForUpload(tableLayout bool) string {
	if tableLayout {
		if m := strings.TrimSpace(os.Getenv("CURSOR_OCR_TABLE_MODEL")); m != "" {
			return m
		}
	}
	return c.OCRModel()
}

func (c *Config) CursorTimeoutForUpload(tableLayout bool) float64 {
	t := c.CursorOCRTimeout
	if tableLayout {
		if t > 200 {
			t = 200
		}
	} else if t > 120 {
		t = 120
	}
	return t
}

func (c *Config) EffectiveOCRMaxSide() int {
	side := c.OCRMaxImageSide
	if c.OCRFast && c.OCRFastMaxSide > 0 && side > c.OCRFastMaxSide {
		side = c.OCRFastMaxSide
	}
	if side < 640 {
		side = 640
	}
	return side
}

// EffectiveMaxSideForUpload picks resolution: table uploads may use a slightly higher cap for cell clarity.
func (c *Config) EffectiveMaxSideForUpload(tableLayout bool) int {
	side := c.EffectiveOCRMaxSide()
	if tableLayout && c.OCRTableMaxSide > side {
		side = c.OCRTableMaxSide
	}
	if side < 640 {
		side = 640
	}
	return side
}

func (c *Config) JPEGQualityForUpload(tableLayout bool) int {
	if tableLayout {
		return c.OCRTableJPEGQuality
	}
	return c.OCRJPEGQuality
}

func (c *Config) HandwritingDBPath(workspace string) string {
	if c.HandwritingDB != "" {
		return c.HandwritingDB
	}
	if os.Getenv("VERCEL") == "1" && c.DatabaseURL == "" {
		return filepath.Join(os.TempDir(), "handwriting.db")
	}
	return filepath.Join(workspace, ".data", "handwriting.db")
}

func envOr(key, fallback string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return fallback
}

func splitCSV(s string) []string {
	var out []string
	for _, part := range strings.Split(s, ",") {
		if p := strings.TrimSpace(part); p != "" {
			out = append(out, p)
		}
	}
	return out
}
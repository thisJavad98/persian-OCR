package config

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/joho/godotenv"
)

type Config struct {
	CORSOrigins      []string
	OCRMaxImageSide  int
	OCRFastMaxSide   int
	OCRJPEGQuality   int
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

	jpegQ := 78
	if v := strings.TrimSpace(os.Getenv("OCR_JPEG_QUALITY")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n >= 50 && n <= 95 {
			jpegQ = n
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

	return &Config{
		CORSOrigins:      splitCSV(origins),
		OCRMaxImageSide:     maxSide,
		OCRFastMaxSide:      fastMaxSide,
		OCRJPEGQuality:      jpegQ,
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
	}, nil
}

func (c *Config) OCRModel() string {
	if c.OCRFast && c.CursorOCRFastModel != "" {
		return c.CursorOCRFastModel
	}
	return c.CursorOCRModel
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

func (c *Config) HandwritingDBPath(workspace string) string {
	if c.HandwritingDB != "" {
		return c.HandwritingDB
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
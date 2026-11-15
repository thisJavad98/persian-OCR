package config

import (
	"os"
	"strconv"
	"strings"

	"github.com/joho/godotenv"
)

type Config struct {
	CORSOrigins      []string
	OCRMaxImageSide  int
	Host             string
	Port             string
	OCRUseCursor     bool
	CursorOCRModel   string
	CursorOCRTimeout float64
	CursorAPIKey     string
	AuthUsername     string
	AuthPassword     string
	SessionSecret    string
}

func Load() (*Config, error) {
	_ = godotenv.Load()

	useCursor := os.Getenv("OCR_USE_CURSOR")
	if useCursor == "" {
		useCursor = "1"
	}

	maxSide := 1600
	if v := strings.TrimSpace(os.Getenv("OCR_MAX_IMAGE_SIDE")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			maxSide = n
		}
	}

	timeout := 180.0
	if v := strings.TrimSpace(os.Getenv("CURSOR_OCR_TIMEOUT")); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil && f > 0 {
			timeout = f
		}
	}

	model := strings.TrimSpace(os.Getenv("CURSOR_OCR_MODEL"))
	if model == "" {
		model = strings.TrimSpace(os.Getenv("CURSOR_MODEL"))
	}
	if model == "" {
		model = "composer-2.5"
	}

	origins := strings.TrimSpace(os.Getenv("CORS_ORIGINS"))
	if origins == "" {
		origins = "http://localhost:5173,http://127.0.0.1:5173"
	}

	return &Config{
		CORSOrigins:      splitCSV(origins),
		OCRMaxImageSide:  maxSide,
		Host:             envOr("HOST", "0.0.0.0"),
		Port:             envOr("PORT", "8000"),
		OCRUseCursor:     useCursor != "0",
		CursorOCRModel:   model,
		CursorOCRTimeout: timeout,
		CursorAPIKey:     strings.TrimSpace(os.Getenv("CURSOR_API_KEY")),
		AuthUsername:     envOr("AUTH_USERNAME", "alifaghihi123"),
		AuthPassword:     envOr("AUTH_PASSWORD", "AliFaghihi@123"),
		SessionSecret:    envOr("SESSION_SECRET", ""),
	}, nil
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
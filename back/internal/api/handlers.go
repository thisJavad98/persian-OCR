package api

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime"
	"net/http"
	"path/filepath"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/javad-moghofei/persian-ocr/back/internal/auth"
	"github.com/javad-moghofei/persian-ocr/back/internal/config"
	"github.com/javad-moghofei/persian-ocr/back/internal/cursor"
	"github.com/javad-moghofei/persian-ocr/back/internal/export"
	"github.com/javad-moghofei/persian-ocr/back/internal/imageutil"
)

var allowedTypes = map[string]bool{
	"image/jpeg": true, "image/jpg": true, "image/png": true,
	"image/webp": true, "image/bmp": true, "image/tiff": true,
}

type Server struct {
	cfg     *config.Config
	cursor  *cursor.Service
	root    string
	session *auth.Session
}

func NewServer(cfg *config.Config, root string) *Server {
	sess := auth.NewSession(auth.Credentials{
		Username: cfg.AuthUsername,
		Password: cfg.AuthPassword,
	}, cfg.SessionSecret)
	return &Server{
		cfg:     cfg,
		cursor:  cursor.NewService(cfg, root),
		root:    root,
		session: sess,
	}
}

func (s *Server) Routes() chi.Router {
	r := chi.NewRouter()
	r.Post("/api/auth/login", s.authLogin)
	r.Post("/api/auth/logout", s.authLogout)
	r.Get("/api/auth/me", s.authMe)

	r.Group(func(r chi.Router) {
		r.Use(s.session.Middleware)
		r.Route("/api/ocr", func(r chi.Router) {
			r.Post("/upload", s.upload)
			r.Post("/export/excel", s.exportExcel)
			r.Post("/export/word", s.exportWord)
		})
		r.Get("/api/health", s.health)
	})
	return r
}

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	ready := s.cursor.Available()
	status := "ok"
	if !ready {
		status = "degraded"
	}
	initErr := s.cursor.InitError()
	var init any
	if initErr != "" {
		init = initErr
	}
	writeJSON(w, http.StatusOK, HealthOut{
		Status:   status,
		Database: "none",
		OCRReady: ready,
		Engines:  s.cursor.Engines(),
		Details: map[string]any{
			"init_error": init,
			"mode":       "cursor-only",
			"storage":    "none",
		},
	})
}

func (s *Server) upload(w http.ResponseWriter, r *http.Request) {
	if !s.cursor.Available() {
		writeJSON(w, http.StatusServiceUnavailable, ErrorDetail{Detail: s.cursor.InitError()})
		return
	}

	if err := r.ParseMultipartForm(32 << 20); err != nil {
		writeJSON(w, http.StatusBadRequest, ErrorDetail{Detail: "Invalid multipart form."})
		return
	}
	file, hdr, err := r.FormFile("file")
	if err != nil {
		writeJSON(w, http.StatusBadRequest, ErrorDetail{Detail: "Missing file field."})
		return
	}
	defer file.Close()

	contentType := strings.ToLower(hdr.Header.Get("Content-Type"))
	if contentType == "" {
		contentType = strings.ToLower(mime.TypeByExtension(filepath.Ext(hdr.Filename)))
	}
	if !allowedTypes[contentType] {
		writeJSON(w, http.StatusBadRequest, ErrorDetail{Detail: "Only image uploads are supported."})
		return
	}

	raw, err := io.ReadAll(file)
	if err != nil || len(raw) == 0 {
		writeJSON(w, http.StatusBadRequest, ErrorDetail{Detail: "Empty file."})
		return
	}

	filename := hdr.Filename
	if filename == "" {
		filename = "upload.png"
	}

	maxSide := max(960, s.cfg.OCRMaxImageSide)
	tmpPath, cleanup, err := imageutil.PrepareToTemp(s.root, raw, maxSide)
	if err != nil {
		writeJSON(w, http.StatusOK, failedOut(filename, contentType, "Uploaded file is not a readable image."))
		return
	}
	defer cleanup()

	ocrCtx, cancel := context.WithTimeout(r.Context(), time.Duration(s.cfg.CursorOCRTimeout*float64(time.Second)))
	defer cancel()

	result, err := s.cursor.Extract(ocrCtx, tmpPath)
	if err != nil {
		writeJSON(w, http.StatusOK, failedOut(filename, contentType, err.Error()))
		return
	}

	conf := result.Confidence
	if conf <= 0 {
		conf = 0.88
	}

	out := buildSuccessOut(filename, contentType, result, conf)
	writeJSON(w, http.StatusOK, out)
}

func (s *Server) exportExcel(w http.ResponseWriter, r *http.Request) {
	var in ExportIn
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
		writeJSON(w, http.StatusBadRequest, ErrorDetail{Detail: "Invalid JSON body."})
		return
	}
	lines, words := exportMaps(in.Lines, in.Words)
	payload, err := export.BuildExcel(in.Filename, in.ExtractedText, lines, words, in.Sentences, in.Confidence, in.Engine)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, ErrorDetail{Detail: err.Error()})
		return
	}
	w.Header().Set("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
	w.Header().Set("Content-Disposition", attachmentName(in.Filename, "xlsx"))
	_, _ = w.Write(payload)
}

func (s *Server) exportWord(w http.ResponseWriter, r *http.Request) {
	var in ExportIn
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
		writeJSON(w, http.StatusBadRequest, ErrorDetail{Detail: "Invalid JSON body."})
		return
	}
	lineTexts := []string{}
	for _, ln := range in.Lines {
		if ln.Text != "" {
			lineTexts = append(lineTexts, ln.Text)
		}
	}
	wordTexts := []string{}
	for _, w := range in.Words {
		if w.Text != "" {
			wordTexts = append(wordTexts, w.Text)
		}
	}
	payload, err := export.BuildWord(in.Filename, in.ExtractedText, lineTexts, wordTexts, in.Sentences, in.Engine, in.Confidence)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, ErrorDetail{Detail: err.Error()})
		return
	}
	w.Header().Set("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
	w.Header().Set("Content-Disposition", attachmentName(in.Filename, "docx"))
	_, _ = w.Write(payload)
}

func buildSuccessOut(filename, mime string, result *cursor.Result, conf float64) OcrJobOut {
	text := result.Text
	engine := result.Engine
	out := OcrJobOut{
		Filename:      filename,
		MimeType:      mime,
		Status:        "completed",
		ExtractedText: &text,
		Lines:         []OcrLine{},
		Words:         []OcrWord{},
		Sentences:     append([]string(nil), result.Sentences...),
		Table:         nil,
		DeathRecords:  nil,
		Engine:        &engine,
		Confidence:    &conf,
	}
	for i, line := range result.Lines {
		row := i + 1
		out.Lines = append(out.Lines, OcrLine{Text: line, Confidence: conf, Row: &row})
	}
	for i, word := range result.Words {
		out.Words = append(out.Words, OcrWord{
			Text: word, Confidence: conf, Row: 0, LineIndex: i,
		})
	}
	return out
}

func failedOut(filename, mime, msg string) OcrJobOut {
	return OcrJobOut{
		Filename:     filename,
		MimeType:     mime,
		Status:       "failed",
		Lines:        []OcrLine{},
		Words:        []OcrWord{},
		Sentences:    []string{},
		ErrorMessage: &msg,
	}
}

func exportMaps(lines []OcrLine, words []OcrWord) ([]map[string]any, []map[string]any) {
	lineMaps := make([]map[string]any, 0, len(lines))
	for _, ln := range lines {
		lineMaps = append(lineMaps, map[string]any{
			"text": ln.Text, "confidence": ln.Confidence, "box": ln.Box, "row": ln.Row,
		})
	}
	wordMaps := make([]map[string]any, 0, len(words))
	for _, w := range words {
		wordMaps = append(wordMaps, map[string]any{
			"text": w.Text, "confidence": w.Confidence, "box": w.Box,
			"row": w.Row, "line_index": w.LineIndex,
		})
	}
	return lineMaps, wordMaps
}

func attachmentName(filename, ext string) string {
	base := strings.TrimSuffix(filepath.Base(filename), filepath.Ext(filename))
	if base == "" {
		base = "ocr"
	}
	return fmt.Sprintf(`attachment; filename="%s.%s"`, base, ext)
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(v)
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
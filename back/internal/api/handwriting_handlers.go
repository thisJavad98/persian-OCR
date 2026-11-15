package api

import (
	"context"
	"io"
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/javad-moghofei/persian-ocr/back/internal/handwriting"
	"github.com/javad-moghofei/persian-ocr/back/internal/imageutil"
)

func (s *Server) handwritingStatus(w http.ResponseWriter, r *http.Request) {
	user, err := s.session.UsernameFromRequest(r)
	if err != nil {
		writeJSON(w, http.StatusUnauthorized, ErrorDetail{Detail: "ورود لازم است."})
		return
	}
	writeJSON(w, http.StatusOK, s.hw.Status(user))
}

func (s *Server) handwritingClear(w http.ResponseWriter, r *http.Request) {
	user, err := s.session.UsernameFromRequest(r)
	if err != nil {
		writeJSON(w, http.StatusUnauthorized, ErrorDetail{Detail: "ورود لازم است."})
		return
	}
	s.hw.Clear(user)
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (s *Server) handwritingTrain(w http.ResponseWriter, r *http.Request) {
	if !s.cursor.Available() {
		writeJSON(w, http.StatusServiceUnavailable, ErrorDetail{Detail: s.cursor.InitError()})
		return
	}
	user, err := s.session.UsernameFromRequest(r)
	if err != nil {
		writeJSON(w, http.StatusUnauthorized, ErrorDetail{Detail: "ورود لازم است."})
		return
	}

	if err := r.ParseMultipartForm(24 << 20); err != nil {
		writeJSON(w, http.StatusBadRequest, ErrorDetail{Detail: "فرم نامعتبر."})
		return
	}

	imgFile, imgHdr, err := r.FormFile("sample_image")
	if err != nil {
		writeJSON(w, http.StatusBadRequest, ErrorDetail{Detail: "تصویر نمونه لازم است."})
		return
	}
	defer imgFile.Close()

	xlsFile, xlsHdr, err := r.FormFile("reference_excel")
	if err != nil {
		writeJSON(w, http.StatusBadRequest, ErrorDetail{Detail: "فایل اکسل مرجع لازم است."})
		return
	}
	defer xlsFile.Close()

	imgType := strings.ToLower(imgHdr.Header.Get("Content-Type"))
	if imgType == "" {
		imgType = strings.ToLower(mime.TypeByExtension(filepath.Ext(imgHdr.Filename)))
	}
	if !allowedTypes[imgType] {
		writeJSON(w, http.StatusBadRequest, ErrorDetail{Detail: "تصویر نمونه باید فایل تصویری باشد."})
		return
	}
	if ext := strings.ToLower(filepath.Ext(xlsHdr.Filename)); ext != ".xlsx" && ext != ".xlsm" {
		writeJSON(w, http.StatusBadRequest, ErrorDetail{Detail: "فقط فایل .xlsx مرجع پذیرفته می‌شود."})
		return
	}

	imgRaw, err := io.ReadAll(imgFile)
	if err != nil || len(imgRaw) == 0 {
		writeJSON(w, http.StatusBadRequest, ErrorDetail{Detail: "تصویر خالی است."})
		return
	}
	xlsRaw, err := io.ReadAll(xlsFile)
	if err != nil || len(xlsRaw) == 0 {
		writeJSON(w, http.StatusBadRequest, ErrorDetail{Detail: "اکسل خالی است."})
		return
	}

	grid, err := handwriting.ParseReferenceGrid(xlsRaw)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, ErrorDetail{Detail: err.Error()})
		return
	}

	dir := filepath.Join(s.root, ".scratch", "handwriting", user)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		writeJSON(w, http.StatusInternalServerError, ErrorDetail{Detail: err.Error()})
		return
	}
	samplePath := filepath.Join(dir, "sample.jpg")
	previewPath := samplePath
	maxSide := s.cfg.OCRMaxImageSide
	if maxSide < 720 {
		maxSide = 720
	}
	tmpPath, cleanup, err := imageutil.PrepareToTemp(s.root, imgRaw, maxSide)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, ErrorDetail{Detail: "تصویر نمونه خوانده نشد."})
		return
	}
	defer cleanup()
	if err := saveCopy(tmpPath, samplePath); err != nil {
		writeJSON(w, http.StatusInternalServerError, ErrorDetail{Detail: err.Error()})
		return
	}

	rel, _ := filepath.Rel(s.root, samplePath)
	rel = filepath.ToSlash(rel)

	// Detach from client/proxy disconnect; calibration can take as long as OCR.
	trainSecs := s.cfg.CursorOCRTimeout*float64(1+s.cfg.CursorOCRRetries) + 60
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(trainSecs*float64(time.Second)))
	defer cancel()
	notes, err := s.cursor.StudyHandwriting(ctx, previewPath, grid)
	if err != nil {
		writeJSON(w, http.StatusOK, map[string]any{
			"ok":    false,
			"error": err.Error(),
		})
		return
	}

	prof := &handwriting.Profile{
		SampleFilename: imgHdr.Filename,
		ExcelFilename:  xlsHdr.Filename,
		ImageRelPath:   rel,
		ReferenceGrid:  grid,
		StyleNotes:     notes,
	}
	s.hw.Set(user, prof)
	writeJSON(w, http.StatusOK, map[string]any{
		"ok":     true,
		"status": s.hw.Status(user),
	})
}

func saveCopy(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, in)
	return err
}
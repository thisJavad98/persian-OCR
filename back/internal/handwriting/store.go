package handwriting

import (
	"database/sql"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	_ "modernc.org/sqlite"
)

type Profile struct {
	Active         bool      `json:"active"`
	SampleFilename string    `json:"sample_filename,omitempty"`
	ExcelFilename  string    `json:"excel_filename,omitempty"`
	ImageRelPath   string    `json:"-"`
	ReferenceGrid  string    `json:"-"`
	StyleNotes     string    `json:"-"`
	TrainedAt      time.Time `json:"trained_at,omitempty"`
}

type Status struct {
	Active         bool   `json:"active"`
	SampleFilename string `json:"sample_filename,omitempty"`
	ExcelFilename  string `json:"excel_filename,omitempty"`
	Message        string `json:"message,omitempty"`
}

type Store struct {
	mu        sync.RWMutex
	db        *sql.DB
	workspace string
}

func NewStore(workspace, dbPath string) (*Store, error) {
	if err := os.MkdirAll(filepath.Dir(dbPath), 0o700); err != nil {
		return nil, err
	}
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	s := &Store{db: db, workspace: workspace}
	if err := s.migrate(); err != nil {
		_ = db.Close()
		return nil, err
	}
	return s, nil
}

func (s *Store) Close() error {
	return s.db.Close()
}

func (s *Store) migrate() error {
	_, err := s.db.Exec(`
CREATE TABLE IF NOT EXISTS handwriting_profiles (
  username TEXT PRIMARY KEY,
  sample_filename TEXT NOT NULL,
  excel_filename TEXT NOT NULL,
  image_rel_path TEXT NOT NULL,
  reference_grid TEXT NOT NULL,
  style_notes TEXT NOT NULL,
  trained_at INTEGER NOT NULL
);`)
	return err
}

func userKey(username string) string {
	u := strings.TrimSpace(username)
	u = strings.ReplaceAll(u, string(os.PathSeparator), "_")
	u = strings.ReplaceAll(u, "..", "_")
	if u == "" {
		u = "user"
	}
	return u
}

func UserDataDir(workspace, username string) string {
	return filepath.Join(workspace, ".data", "handwriting", userKey(username))
}

func (s *Store) absImage(rel string) string {
	return filepath.Join(s.workspace, filepath.FromSlash(rel))
}

func (s *Store) Get(username string) *Profile {
	p, err := s.load(username)
	if err != nil || p == nil {
		return nil
	}
	if _, err := os.Stat(s.absImage(p.ImageRelPath)); err != nil {
		_ = s.Clear(username)
		return nil
	}
	cp := *p
	return &cp
}

func (s *Store) Status(username string) Status {
	p := s.Get(username)
	if p == nil {
		return Status{Active: false}
	}
	return Status{
		Active:         true,
		SampleFilename: p.SampleFilename,
		ExcelFilename:  p.ExcelFilename,
		Message:        "نمونه دست‌خط و خروجی مرجع ذخیره شده‌اند؛ استخراج‌های بعدی دقیق‌تر انجام می‌شوند.",
	}
}

func (s *Store) Set(username string, p *Profile) error {
	if p == nil {
		return s.Clear(username)
	}
	s.mu.Lock()
	defer s.mu.Unlock()

	p.Active = true
	if p.TrainedAt.IsZero() {
		p.TrainedAt = time.Now()
	}

	_, err := s.db.Exec(`
INSERT INTO handwriting_profiles (
  username, sample_filename, excel_filename, image_rel_path, reference_grid, style_notes, trained_at
) VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(username) DO UPDATE SET
  sample_filename = excluded.sample_filename,
  excel_filename = excluded.excel_filename,
  image_rel_path = excluded.image_rel_path,
  reference_grid = excluded.reference_grid,
  style_notes = excluded.style_notes,
  trained_at = excluded.trained_at`,
		userKey(username),
		p.SampleFilename,
		p.ExcelFilename,
		p.ImageRelPath,
		p.ReferenceGrid,
		p.StyleNotes,
		p.TrainedAt.Unix(),
	)
	return err
}

func (s *Store) Clear(username string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	key := userKey(username)
	_, _ = s.db.Exec(`DELETE FROM handwriting_profiles WHERE username = ?`, key)
	dir := UserDataDir(s.workspace, username)
	if dir != "" {
		_ = os.RemoveAll(dir)
	}
	return nil
}

func (s *Store) load(username string) (*Profile, error) {
	key := userKey(username)
	row := s.db.QueryRow(`
SELECT sample_filename, excel_filename, image_rel_path, reference_grid, style_notes, trained_at
FROM handwriting_profiles WHERE username = ?`, key)

	var p Profile
	var trainedAt int64
	err := row.Scan(
		&p.SampleFilename,
		&p.ExcelFilename,
		&p.ImageRelPath,
		&p.ReferenceGrid,
		&p.StyleNotes,
		&trainedAt,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	p.Active = true
	p.TrainedAt = time.Unix(trainedAt, 0)
	return &p, nil
}

// SaveReferenceExcel writes the user's reference spreadsheet beside the sample image.
func SaveReferenceExcel(workspace, username string, raw []byte) error {
	if len(raw) == 0 {
		return fmt.Errorf("اکسل خالی است")
	}
	dir := UserDataDir(workspace, username)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, "reference.xlsx"), raw, 0o600)
}
package handwriting

import (
	"database/sql"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
)

func openPostgres(workspace, pgURL string) (*Store, error) {
	db, err := sql.Open("pgx", pgURL)
	if err != nil {
		return nil, err
	}
	if err := db.Ping(); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("postgres ping: %w", err)
	}
	s := &Store{db: db, workspace: workspace, driver: driverPostgres}
	if err := s.migratePostgres(); err != nil {
		_ = db.Close()
		return nil, err
	}
	return s, nil
}

func (s *Store) migratePostgres() error {
	_, err := s.db.Exec(`
CREATE TABLE IF NOT EXISTS handwriting_profiles (
  username TEXT PRIMARY KEY,
  sample_filename TEXT NOT NULL,
  excel_filename TEXT NOT NULL,
  reference_grid TEXT NOT NULL,
  style_notes TEXT NOT NULL,
  trained_at BIGINT NOT NULL,
  sample_jpeg BYTEA NOT NULL,
  reference_xlsx BYTEA NOT NULL
);`)
	return err
}

func (s *Store) loadPostgres(username string) (*Profile, error) {
	key := userKey(username)
	row := s.db.QueryRow(`
SELECT sample_filename, excel_filename, reference_grid, style_notes, trained_at, sample_jpeg, reference_xlsx
FROM handwriting_profiles WHERE username = $1`, key)

	var p Profile
	var trainedAt int64
	var sampleJPEG, refXLSX []byte
	err := row.Scan(
		&p.SampleFilename,
		&p.ExcelFilename,
		&p.ReferenceGrid,
		&p.StyleNotes,
		&trainedAt,
		&sampleJPEG,
		&refXLSX,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	p.Active = true
	p.TrainedAt = time.Unix(trainedAt, 0)

	dir := profileScratchDir(s.workspace, key)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	samplePath := filepath.Join(dir, "sample.jpg")
	if err := os.WriteFile(samplePath, sampleJPEG, 0o600); err != nil {
		return nil, err
	}
	if len(refXLSX) > 0 {
		_ = os.WriteFile(filepath.Join(dir, "reference.xlsx"), refXLSX, 0o600)
	}
	rel, err := filepath.Rel(s.workspace, samplePath)
	if err != nil {
		rel = samplePath
	}
	p.ImageRelPath = filepath.ToSlash(rel)
	return &p, nil
}

func (s *Store) setPostgres(username string, p *Profile) error {
	key := userKey(username)
	samplePath := s.absImage(p.ImageRelPath)
	sampleJPEG, err := os.ReadFile(samplePath)
	if err != nil {
		return err
	}
	refPath := filepath.Join(profileScratchDir(s.workspace, key), "reference.xlsx")
	refXLSX, err := os.ReadFile(refPath)
	if err != nil {
		refPath = filepath.Join(UserDataDir(s.workspace, username), "reference.xlsx")
		refXLSX, err = os.ReadFile(refPath)
		if err != nil {
			return fmt.Errorf("reference.xlsx: %w", err)
		}
	}

	_, err = s.db.Exec(`
INSERT INTO handwriting_profiles (
  username, sample_filename, excel_filename, reference_grid, style_notes, trained_at, sample_jpeg, reference_xlsx
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
ON CONFLICT (username) DO UPDATE SET
  sample_filename = EXCLUDED.sample_filename,
  excel_filename = EXCLUDED.excel_filename,
  reference_grid = EXCLUDED.reference_grid,
  style_notes = EXCLUDED.style_notes,
  trained_at = EXCLUDED.trained_at,
  sample_jpeg = EXCLUDED.sample_jpeg,
  reference_xlsx = EXCLUDED.reference_xlsx`,
		key, p.SampleFilename, p.ExcelFilename, p.ReferenceGrid, p.StyleNotes, p.TrainedAt.Unix(), sampleJPEG, refXLSX,
	)
	return err
}

func (s *Store) clearPostgres(username string) error {
	key := userKey(username)
	_, err := s.db.Exec(`DELETE FROM handwriting_profiles WHERE username = $1`, key)
	_ = os.RemoveAll(profileScratchDir(s.workspace, key))
	_ = os.RemoveAll(UserDataDir(s.workspace, username))
	return err
}

func profileScratchDir(workspace, userKey string) string {
	return filepath.Join(workspace, ".scratch", "profiles", userKey)
}
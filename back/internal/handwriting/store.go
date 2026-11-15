package handwriting

import (
	"sync"
	"time"
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
	mu     sync.RWMutex
	byUser map[string]*Profile
}

func NewStore() *Store {
	return &Store{byUser: make(map[string]*Profile)}
}

func (s *Store) Get(username string) *Profile {
	s.mu.RLock()
	defer s.mu.RUnlock()
	p, ok := s.byUser[username]
	if !ok || p == nil || !p.Active {
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
		Message:        "نمونه دست‌خط و خروجی مرجع ثبت شد؛ استخراج‌های بعدی دقیق‌تر انجام می‌شوند.",
	}
}

func (s *Store) Set(username string, p *Profile) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if p == nil {
		delete(s.byUser, username)
		return
	}
	p.Active = true
	p.TrainedAt = time.Now()
	s.byUser[username] = p
}

func (s *Store) Clear(username string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.byUser, username)
}
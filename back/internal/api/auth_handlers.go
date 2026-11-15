package api

import (
	"encoding/json"
	"net/http"
)

type loginIn struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

func (s *Server) authMe(w http.ResponseWriter, r *http.Request) {
	user, err := s.session.UsernameFromRequest(r)
	if err != nil {
		writeJSON(w, http.StatusUnauthorized, ErrorDetail{Detail: "ورود لازم است."})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"username": user})
}

func (s *Server) authLogin(w http.ResponseWriter, r *http.Request) {
	var in loginIn
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
		writeJSON(w, http.StatusBadRequest, ErrorDetail{Detail: "درخواست نامعتبر."})
		return
	}
	if !s.session.Login(in.Username, in.Password) {
		writeJSON(w, http.StatusUnauthorized, ErrorDetail{Detail: "نام کاربری یا رمز اشتباه است."})
		return
	}
	s.session.SetCookie(w, s.session.Creds.Username)
	writeJSON(w, http.StatusOK, map[string]string{"username": s.session.Creds.Username})
}

func (s *Server) authLogout(w http.ResponseWriter, r *http.Request) {
	if user, err := s.session.UsernameFromRequest(r); err == nil {
		s.hw.Clear(user)
	}
	s.session.ClearCookie(w)
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}
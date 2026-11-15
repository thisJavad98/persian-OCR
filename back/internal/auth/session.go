package auth

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"
)

const cookieName = "khatkhan_session"

type Credentials struct {
	Username string
	Password string
}

type Session struct {
	Secret []byte
	MaxAge time.Duration
	Creds  Credentials
}

func NewSession(creds Credentials, secret string) *Session {
	if secret == "" {
		secret = "dev-insecure-change-me"
	}
	age := 7 * 24 * time.Hour
	return &Session{
		Secret: []byte(secret),
		MaxAge: age,
		Creds:  creds,
	}
}

func (s *Session) Login(username, password string) bool {
	u := strings.TrimSpace(username)
	if subtle.ConstantTimeCompare([]byte(u), []byte(s.Creds.Username)) != 1 {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(password), []byte(s.Creds.Password)) == 1
}

func (s *Session) SetCookie(w http.ResponseWriter, username string) {
	exp := time.Now().Add(s.MaxAge).Unix()
	payload := username + "|" + strconv.FormatInt(exp, 10)
	sig := sign(s.Secret, payload)
	value := base64.RawURLEncoding.EncodeToString([]byte(payload)) + "." + base64.RawURLEncoding.EncodeToString(sig)
	http.SetCookie(w, &http.Cookie{
		Name:     cookieName,
		Value:    value,
		Path:     "/",
		HttpOnly: true,
		SameSite: http.SameSiteLaxMode,
		MaxAge:   int(s.MaxAge.Seconds()),
	})
}

func (s *Session) ClearCookie(w http.ResponseWriter) {
	http.SetCookie(w, &http.Cookie{
		Name:     cookieName,
		Value:    "",
		Path:     "/",
		HttpOnly: true,
		MaxAge:   -1,
	})
}

func (s *Session) UsernameFromRequest(r *http.Request) (string, error) {
	c, err := r.Cookie(cookieName)
	if err != nil || c.Value == "" {
		return "", errors.New("no session")
	}
	parts := strings.SplitN(c.Value, ".", 2)
	if len(parts) != 2 {
		return "", errors.New("bad session")
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return "", err
	}
	sig, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return "", err
	}
	payload := string(raw)
	if !hmac.Equal(sign(s.Secret, payload), sig) {
		return "", errors.New("bad signature")
	}
	chunk := strings.SplitN(payload, "|", 2)
	if len(chunk) != 2 {
		return "", errors.New("bad payload")
	}
	exp, err := strconv.ParseInt(chunk[1], 10, 64)
	if err != nil || time.Now().Unix() > exp {
		return "", errors.New("expired")
	}
	if chunk[0] != s.Creds.Username {
		return "", errors.New("unknown user")
	}
	return chunk[0], nil
}

func (s *Session) Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if _, err := s.UsernameFromRequest(r); err != nil {
			w.Header().Set("Content-Type", "application/json; charset=utf-8")
			w.WriteHeader(http.StatusUnauthorized)
			_, _ = w.Write([]byte(`{"detail":"ورود لازم است."}`))
			return
		}
		next.ServeHTTP(w, r)
	})
}

func sign(secret []byte, payload string) []byte {
	m := hmac.New(sha256.New, secret)
	_, _ = m.Write([]byte(payload))
	return m.Sum(nil)
}
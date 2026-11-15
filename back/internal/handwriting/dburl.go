package handwriting

import "strings"

func normalizeDatabaseURL(raw string) string {
	s := strings.TrimSpace(raw)
	if s == "" {
		return ""
	}
	s = strings.Replace(s, "postgresql+psycopg2://", "postgres://", 1)
	s = strings.Replace(s, "postgresql://", "postgres://", 1)
	return s
}
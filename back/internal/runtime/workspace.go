package runtime

import (
	"os"
	"path/filepath"
)

// Serverless is true on Vercel/Render where disk and long-running CLIs are constrained.
func Serverless() bool {
	if os.Getenv("VERCEL") == "1" || os.Getenv("VERCEL_ENV") != "" {
		return true
	}
	return os.Getenv("RENDER") == "true"
}

// WorkspaceRoot returns a writable workspace directory. Vercel's deployment root (/var/task) is read-only.
func WorkspaceRoot(cwd string) string {
	if os.Getenv("VERCEL") == "1" || os.Getenv("VERCEL_ENV") != "" {
		base := filepath.Join(os.TempDir(), "persian-ocr-app")
		_ = os.MkdirAll(base, 0o700)
		return base
	}
	if cwd != "" {
		return cwd
	}
	wd, err := os.Getwd()
	if err != nil {
		return os.TempDir()
	}
	return wd
}
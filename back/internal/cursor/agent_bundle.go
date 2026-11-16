package cursor

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const cursorLinuxPkg = "https://downloads.cursor.com/lab/2026.11.13-eacade1/linux/x64/agent-cli-package.tar.gz"

const shippedBundleName = "cursor-agent-bundle.tgz"

var (
	bundleMu      sync.Mutex
	bundleBinary  string
	lastBundleErr string

	cursorHTTPClient = &http.Client{
		Transport: &http.Transport{
			Proxy: http.ProxyFromEnvironment,
			DialContext: (&net.Dialer{
				Timeout:   90 * time.Second,
				KeepAlive: 30 * time.Second,
			}).DialContext,
			TLSHandshakeTimeout:   90 * time.Second,
			ResponseHeaderTimeout: 120 * time.Second,
			ExpectContinueTimeout: 1 * time.Second,
		},
	}
)

func onVercel() bool {
	return os.Getenv("VERCEL") == "1" || os.Getenv("VERCEL_ENV") != ""
}

func cursorPkgURL() string {
	if u := strings.TrimSpace(os.Getenv("CURSOR_AGENT_PKG_URL")); u != "" {
		return u
	}
	return cursorLinuxPkg
}

// skipCursorTarEntry drops huge SEA blobs and bundled node when the runtime already has node.
func skipCursorTarEntry(name string) bool {
	name = strings.TrimPrefix(name, "./")
	switch name {
	case "dist-package/cursor-agent-sea", "dist-package/cursor-agent-worker-sea":
		return true
	}
	if _, err := exec.LookPath("node"); err == nil {
		return name == "dist-package/node"
	}
	return false
}

func taskRoot() string {
	if r := strings.TrimSpace(os.Getenv("LAMBDA_TASK_ROOT")); r != "" {
		return r
	}
	return "/var/task"
}

func bundledRuntimeDirs() []string {
	task := taskRoot()
	var roots []string
	if wd, err := os.Getwd(); err == nil {
		roots = append(roots, filepath.Join(wd, "cursor-runtime"))
	}
	if exe, err := os.Executable(); err == nil {
		roots = append(roots, filepath.Join(filepath.Dir(exe), "cursor-runtime"))
	}
	roots = append(roots,
		filepath.Join(task, "cursor-runtime"),
		filepath.Join(task, "back", "cursor-runtime"),
	)
	return roots
}

func shippedBundlePaths() []string {
	task := taskRoot()
	var paths []string
	if wd, err := os.Getwd(); err == nil {
		paths = append(paths, filepath.Join(wd, shippedBundleName))
	}
	if exe, err := os.Executable(); err == nil {
		paths = append(paths, filepath.Join(filepath.Dir(exe), shippedBundleName))
	}
	paths = append(paths,
		filepath.Join(task, shippedBundleName),
		filepath.Join(task, "back", shippedBundleName),
	)
	return paths
}

func findBundledBinary() string {
	for _, root := range bundledRuntimeDirs() {
		if b := existingBundleBin(root); b != "" {
			return b
		}
	}
	return ""
}

func installDir() string {
	return filepath.Join(os.TempDir(), "persian-ocr-cursor-install")
}

func materializeShippedBundle() string {
	base := installDir()
	if b := existingBundleBin(base); b != "" {
		return b
	}
	for _, tgz := range shippedBundlePaths() {
		if st, err := os.Stat(tgz); err != nil || st.IsDir() {
			continue
		}
		_ = os.RemoveAll(base)
		_ = os.MkdirAll(base, 0o700)
		if err := extractTarGzFile(tgz, base); err != nil {
			lastBundleErr = err.Error()
			continue
		}
		if b := existingBundleBin(base); b != "" {
			return b
		}
	}
	return ""
}

func discoverBundledIndexJS() string {
	task := taskRoot()
	want := filepath.Join("dist-package", "index.js")
	var found string
	_ = filepath.WalkDir(task, func(path string, d os.DirEntry, err error) error {
		if err != nil || found != "" {
			return nil
		}
		if d.IsDir() {
			if strings.Count(strings.TrimPrefix(path, task), string(os.PathSeparator)) > 6 {
				return filepath.SkipDir
			}
			return nil
		}
		if d.Name() == "index.js" && strings.HasSuffix(filepath.ToSlash(path), want) && agentRunnable(path) {
			found = path
			return filepath.SkipAll
		}
		return nil
	})
	return found
}

// installCursorBundle prefers shipped tgz / cursor-runtime; avoids CDN on hot path.
func installCursorBundle() string {
	bundleMu.Lock()
	defer bundleMu.Unlock()
	if bundleBinary != "" {
		return bundleBinary
	}
	if !onVercel() {
		return ""
	}
	if b := findBundledBinary(); b != "" {
		bundleBinary = b
		lastBundleErr = ""
		return b
	}
	if b := materializeShippedBundle(); b != "" {
		bundleBinary = b
		lastBundleErr = ""
		return b
	}
	if b := discoverBundledIndexJS(); b != "" {
		bundleBinary = b
		lastBundleErr = ""
		return b
	}
	if b := existingBundleBin(installDir()); b != "" {
		bundleBinary = b
		return b
	}

	base := installDir()
	_ = os.RemoveAll(base)
	_ = os.MkdirAll(base, 0o700)

	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Minute)
	defer cancel()

	if err := downloadAndExtractCursorPkg(ctx, cursorPkgURL(), base); err != nil {
		lastBundleErr = err.Error()
		return ""
	}
	if b := existingBundleBin(base); b != "" {
		bundleBinary = b
		lastBundleErr = ""
		return b
	}
	lastBundleErr = "cursor-agent runtime install failed"
	return ""
}

func extractTarGzFile(src, dest string) error {
	f, err := os.Open(src)
	if err != nil {
		return err
	}
	defer f.Close()
	gz, err := gzip.NewReader(f)
	if err != nil {
		return err
	}
	defer gz.Close()
	tr := tar.NewReader(gz)
	destAbs, err := filepath.Abs(dest)
	if err != nil {
		return err
	}
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}
		target := filepath.Join(dest, hdr.Name)
		targetAbs, err := filepath.Abs(target)
		if err != nil {
			return err
		}
		if !strings.HasPrefix(targetAbs, destAbs+string(os.PathSeparator)) && targetAbs != destAbs {
			return fmt.Errorf("invalid tar path: %s", hdr.Name)
		}
		switch hdr.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, os.FileMode(hdr.Mode)|0o700); err != nil {
				return err
			}
		case tar.TypeReg:
			if err := os.MkdirAll(filepath.Dir(target), 0o700); err != nil {
				return err
			}
			out, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, os.FileMode(hdr.Mode)|0o600)
			if err != nil {
				return err
			}
			if _, err := io.Copy(out, tr); err != nil {
				_ = out.Close()
				return err
			}
			_ = out.Close()
		default:
			if hdr.Size > 0 {
				_, _ = io.CopyN(io.Discard, tr, hdr.Size)
			}
		}
	}
}

func downloadWithRetry(ctx context.Context, url string) (*http.Response, error) {
	var last error
	for attempt := 0; attempt < 6; attempt++ {
		if attempt > 0 {
			wait := time.Duration(attempt*attempt) * 2 * time.Second
			if wait > 20*time.Second {
				wait = 20 * time.Second
			}
			select {
			case <-ctx.Done():
				return nil, ctx.Err()
			case <-time.After(wait):
			}
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
		if err != nil {
			return nil, err
		}
		req.Header.Set("User-Agent", "persian-ocr-api/1.0")
		req.Header.Set("Accept", "*/*")

		resp, err := cursorHTTPClient.Do(req)
		if err != nil {
			last = err
			if isRetryableDownloadErr(err) {
				continue
			}
			return nil, err
		}
		if resp.StatusCode == http.StatusOK {
			return resp, nil
		}
		_ = resp.Body.Close()
		last = fmt.Errorf("cursor package download: HTTP %d", resp.StatusCode)
		if resp.StatusCode >= 500 || resp.StatusCode == http.StatusTooManyRequests {
			continue
		}
		return nil, last
	}
	return nil, last
}

func isRetryableDownloadErr(err error) bool {
	if err == nil {
		return false
	}
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "tls handshake timeout") ||
		strings.Contains(msg, "i/o timeout") ||
		strings.Contains(msg, "connection reset") ||
		strings.Contains(msg, "connection refused") ||
		strings.Contains(msg, "no such host") ||
		strings.Contains(msg, "temporary failure") ||
		strings.Contains(msg, "unexpected eof") ||
		strings.Contains(msg, " eof") ||
		strings.Contains(msg, "timeout")
}

func downloadAndExtractCursorPkg(ctx context.Context, url, dest string) error {
	resp, err := downloadWithRetry(ctx, url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	gz, err := gzip.NewReader(resp.Body)
	if err != nil {
		return err
	}
	defer gz.Close()
	tr := tar.NewReader(gz)
	destAbs, err := filepath.Abs(dest)
	if err != nil {
		return err
	}
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}
		name := strings.TrimPrefix(hdr.Name, "./")
		if skipCursorTarEntry(name) {
			if hdr.Typeflag == tar.TypeReg && hdr.Size > 0 {
				_, _ = io.CopyN(io.Discard, tr, hdr.Size)
			}
			continue
		}
		target := filepath.Join(dest, hdr.Name)
		targetAbs, err := filepath.Abs(target)
		if err != nil {
			return err
		}
		if !strings.HasPrefix(targetAbs, destAbs+string(os.PathSeparator)) && targetAbs != destAbs {
			return fmt.Errorf("invalid tar path: %s", hdr.Name)
		}
		switch hdr.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, os.FileMode(hdr.Mode)|0o700); err != nil {
				return err
			}
		case tar.TypeReg:
			if err := os.MkdirAll(filepath.Dir(target), 0o700); err != nil {
				return err
			}
			f, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, os.FileMode(hdr.Mode)|0o600)
			if err != nil {
				return err
			}
			if _, err := io.Copy(f, tr); err != nil {
				_ = f.Close()
				return err
			}
			_ = f.Close()
		default:
			if hdr.Size > 0 {
				_, _ = io.CopyN(io.Discard, tr, hdr.Size)
			}
		}
	}
}

func existingBundleBin(base string) string {
	indexJS := filepath.Join(base, "dist-package", "index.js")
	if agentRunnable(indexJS) {
		return indexJS
	}
	return ""
}

func resolveAgentPath(linkOrBin string) string {
	if linkOrBin == "" {
		return ""
	}
	resolved, err := filepath.EvalSymlinks(linkOrBin)
	if err != nil {
		resolved = linkOrBin
	}
	if st, err := os.Stat(resolved); err != nil || st.IsDir() {
		return ""
	}
	return resolved
}

func resolveNodeForIndex(indexJS string) string {
	if indexJS == "" {
		return ""
	}
	if p, err := exec.LookPath("node"); err == nil {
		return p
	}
	bundled := filepath.Join(filepath.Dir(indexJS), "node")
	if st, err := os.Stat(bundled); err == nil && !st.IsDir() {
		return bundled
	}
	return ""
}
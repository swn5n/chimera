package main

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"math"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
)

func randomID(nBytes int) string {
	b := make([]byte, nBytes)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// randInt returns a random int in [0, n). Used for jitter.
func randInt(n int) int {
	if n <= 0 {
		return 0
	}
	b := make([]byte, 2)
	_, _ = rand.Read(b)
	return (int(b[0])<<8 | int(b[1])) % n
}

const inviteAlphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

func randomInvite() string {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	var sb strings.Builder
	for i, v := range b {
		if i == 4 {
			sb.WriteByte('-')
		}
		sb.WriteByte(inviteAlphabet[int(v)%len(inviteAlphabet)])
	}
	return sb.String()
}

func normalizeInvite(s string) string {
	var sb strings.Builder
	for _, r := range strings.ToUpper(s) {
		if (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') {
			sb.WriteRune(r)
		}
	}
	return sb.String()
}

func ownerKey(s string) string { return strings.ToLower(strings.TrimSpace(s)) }

func sameOwner(a, b string) bool { return ownerKey(a) != "" && ownerKey(a) == ownerKey(b) }

// normModel makes "qwen3" and "qwen3:latest" compare equal.
func normModel(s string) string {
	s = strings.ToLower(strings.TrimSpace(s))
	if s != "" && !strings.Contains(s, ":") {
		s += ":latest"
	}
	return s
}

// parseParamsB turns Ollama's parameter_size ("8.0B", "567.8M") into billions.
func parseParamsB(s string) float64 {
	s = strings.ToUpper(strings.TrimSpace(s))
	if s == "" {
		return 0
	}
	mult := 1.0
	switch {
	case strings.HasSuffix(s, "B"):
		s = strings.TrimSuffix(s, "B")
	case strings.HasSuffix(s, "M"):
		s = strings.TrimSuffix(s, "M")
		mult = 0.001
	case strings.HasSuffix(s, "K"):
		s = strings.TrimSuffix(s, "K")
		mult = 0.000001
	case strings.HasSuffix(s, "T"):
		s = strings.TrimSuffix(s, "T")
		mult = 1000
	}
	v, err := strconv.ParseFloat(strings.TrimSpace(s), 64)
	if err != nil {
		return 0
	}
	return v * mult
}

func round1(v float64) float64 { return math.Round(v*10) / 10 }
func round2(v float64) float64 { return math.Round(v*100) / 100 }

func clampInt(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, code int, msg string) {
	writeJSON(w, code, map[string]string{"error": msg})
}

func readJSON(r *http.Request, v any, limit int64) error {
	body := io.LimitReader(r.Body, limit)
	dec := json.NewDecoder(body)
	if err := dec.Decode(v); err != nil && err != io.EOF {
		return err
	}
	return nil
}

func writeFileAtomic(path string, data []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func fileExists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}

// friendlyNetErr turns low-level network errors into something readable.
func friendlyNetErr(err error, what string) string {
	if err == nil {
		return ""
	}
	var ae *apiError
	if errors.As(err, &ae) {
		return ae.Msg
	}
	var ne net.Error
	if errors.Is(err, syscall.ECONNREFUSED) || strings.Contains(err.Error(), "connection refused") {
		return "Nothing is answering at " + what + ". Check the address and that the host has Chimera open with hosting on."
	}
	if errors.As(err, &ne) && ne.Timeout() {
		return "Timed out reaching " + what + ". Are you on the same network (or Tailscale) as the host?"
	}
	if strings.Contains(err.Error(), "no such host") {
		return "Couldn't find " + what + ". Check the address."
	}
	if strings.Contains(err.Error(), "no route to host") || strings.Contains(err.Error(), "network is unreachable") {
		return "No route to " + what + ". On a Mac, allow Chimera under System Settings → Privacy & Security → Local Network."
	}
	return err.Error()
}

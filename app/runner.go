package main

// Test-runs library scripts on the host computer, only when its owner turned on
// "Test library scripts on this computer". A library script comes from the
// network and is untrusted, so it only runs inside a real sandbox: no network,
// the host's home folder hidden, and writes limited to a throwaway folder. If
// this computer can't provide that sandbox, the script isn't run at all. The
// riskyScript regex is only a fast pre-filter, never the boundary.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

type runResult struct {
	OK       bool    `json:"ok"`
	Skipped  bool    `json:"skipped,omitempty"` // couldn't sandbox here; not a failure of the script
	ExitCode int     `json:"exit_code"`
	Seconds  float64 `json:"seconds"`
	Summary  string  `json:"summary"`
	Output   string  `json:"output"`
}

// canSandbox reports whether this computer can safely run an untrusted script.
func canSandbox() bool {
	switch runtime.GOOS {
	case "darwin":
		_, err := exec.LookPath("sandbox-exec")
		return err == nil
	case "linux":
		if _, err := exec.LookPath("bwrap"); err == nil {
			return true
		}
		_, err := exec.LookPath("unshare")
		return err == nil
	default:
		return false
	}
}

func (a *App) runScript(ctx context.Context, kind, script string) runResult {
	if !a.config().RunTests {
		return runResult{Summary: "Test runs are turned off on this computer."}
	}
	if riskyScript.MatchString(script) {
		return runResult{Summary: "Refused: the script touches files, the network or other programs."}
	}
	dir, err := os.MkdirTemp("", "chimera-test-*")
	if err != nil {
		return runResult{Summary: "Couldn't make a temporary folder: " + err.Error()}
	}
	defer os.RemoveAll(dir)
	path := filepath.Join(dir, "script.py")
	if err := os.WriteFile(path, []byte(script), 0o600); err != nil {
		return runResult{Summary: err.Error()}
	}
	var name string
	var args []string
	timeout := 30 * time.Second
	switch kind {
	case "run_python":
		name = a.tools.Path("python")
		args = []string{"-I", path}
	case "run_blender":
		name = a.tools.Path("blender")
		args = []string{"-b", "--factory-startup", "--python-exit-code", "1", "--python", path}
		timeout = 120 * time.Second
	}
	if name == "" {
		return runResult{Summary: "This computer doesn't have the program needed for this test."}
	}
	argv, how, ok := sandboxed(name, args, dir)
	if !ok {
		// No real sandbox here: never run an untrusted script unprotected.
		return runResult{Skipped: true, Summary: "This computer can't safely sandbox a test run, so it didn't run it."}
	}

	cctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(cctx, argv[0], argv[1:]...)
	cmd.Dir = dir
	cmd.Env = scriptEnv(dir)
	hideWindow(cmd)
	start := time.Now()
	out, err := cmd.CombinedOutput()

	if err != nil && sandboxDidNotStart(string(out)) {
		// The sandbox itself couldn't start; treat it as "couldn't check here",
		// not as the script failing, so a good entry isn't flagged.
		return runResult{Skipped: true, Summary: "Couldn't start the sandbox, so the script didn't run.", Output: tail(string(out), 2000)}
	}
	res := runResult{Seconds: round1(time.Since(start).Seconds()), Output: tail(string(out), 4000)}
	var ee *exec.ExitError
	switch {
	case cctx.Err() == context.DeadlineExceeded:
		res.Summary = fmt.Sprintf("Timed out after %s.", timeout)
		res.ExitCode = -1
	case ctx.Err() != nil:
		res.Skipped = true
		res.Summary = "The test run was cancelled."
	case errors.As(err, &ee):
		res.ExitCode = ee.ExitCode()
		res.Summary = fmt.Sprintf("Exited with code %d after %.1fs.", res.ExitCode, res.Seconds)
	case err != nil:
		res.Summary = "Couldn't start: " + err.Error()
		res.ExitCode = -1
	default:
		res.OK = true
		res.Summary = fmt.Sprintf("Ran cleanly in %.1fs.", res.Seconds)
		if kind == "run_blender" && strings.Contains(string(out), "Error:") {
			res.OK = false
			res.Summary = "Blender reported an error."
		}
	}
	if res.OK && how != "" {
		res.Summary += " (" + how + ")"
	}
	return res
}

func sandboxDidNotStart(out string) bool {
	for _, line := range strings.Split(out, "\n") {
		l := strings.TrimSpace(line)
		if strings.HasPrefix(l, "unshare:") || strings.HasPrefix(l, "bwrap:") || strings.HasPrefix(l, "sandbox-exec:") {
			return true
		}
	}
	return false
}

// scriptEnv is a bare environment: nothing from this computer's own
// environment (tokens, keys) reaches a test script.
func scriptEnv(dir string) []string {
	env := []string{"HOME=" + dir, "TMPDIR=" + dir, "TMP=" + dir, "TEMP=" + dir, "PYTHONDONTWRITEBYTECODE=1", "PYTHONNOUSERSITE=1", "LANG=en_US.UTF-8"}
	for _, k := range []string{"PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC"} {
		if v := os.Getenv(k); v != "" {
			env = append(env, k+"="+v)
		}
	}
	return env
}

// sandboxed returns the command to run a script under a sandbox, a short
// description of the protection, and whether a real sandbox is available at
// all. When ok is false the caller must not run the script.
func sandboxed(name string, args []string, dir string) (argv []string, how string, ok bool) {
	switch runtime.GOOS {
	case "darwin":
		return macSandbox(name, args, dir)
	case "linux":
		return linuxSandbox(name, args, dir)
	default:
		return nil, "", false // no sandbox we trust on this platform
	}
}

func macSandbox(name string, args []string, dir string) ([]string, string, bool) {
	p, err := exec.LookPath("sandbox-exec")
	if err != nil {
		return nil, "", false
	}
	realDir, err := filepath.EvalSymlinks(dir)
	if err != nil {
		realDir = dir
	}
	toolDir := filepath.Dir(name)
	if real, err := filepath.EvalSymlinks(name); err == nil {
		toolDir = filepath.Dir(real)
	}
	// Blender and Python read their own files, which may live in a home
	// folder (~/Applications, pyenv): allow the whole app bundle or install prefix.
	if i := strings.Index(toolDir, ".app/"); i >= 0 {
		toolDir = toolDir[:i+4]
	} else if filepath.Base(toolDir) == "bin" {
		toolDir = filepath.Dir(toolDir)
	}
	// No network; the home folder and other volumes unreadable; writes only to
	// the throwaway folder. Child processes inherit this sandbox.
	profile := fmt.Sprintf(`(version 1)
(allow default)
(deny network*)
(deny file-read* (subpath "/Users") (subpath "/Volumes") (subpath "/private/var/root"))
(allow file-read* (subpath %s) (subpath %s))
(deny file-write*)
(allow file-write* (subpath %s) (subpath "/private/var/folders") (subpath "/private/tmp") (literal "/dev/null") (regex #"^/dev/tty") (regex #"^/dev/fd/"))`,
		sbplQuote(realDir), sbplQuote(toolDir), sbplQuote(realDir))
	return append([]string{p, "-p", profile, name}, args...), "sandboxed: no network or home folder", true
}

func linuxSandbox(name string, args []string, dir string) ([]string, string, bool) {
	// bubblewrap is the strong option: a read-only view of the system, the home
	// folders replaced with empty ones, writes only to the work folder, no network.
	if p, err := exec.LookPath("bwrap"); err == nil {
		argv := []string{p, "--unshare-all", "--die-with-parent", "--new-session",
			"--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
			"--tmpfs", "/home", "--tmpfs", "/root", "--tmpfs", "/tmp"}
		if home := realHome(); home != "" && home != "/home" && home != "/root" {
			argv = append(argv, "--tmpfs", home)
		}
		argv = append(argv, "--bind", dir, dir, "--chdir", dir, "--")
		return append(argv, append([]string{name}, args...)...), "sandboxed: no network or home folder", true
	}
	// Otherwise a user + mount + network namespace: no network, and the home
	// folders hidden behind empty mounts so secrets aren't readable. The user
	// maps to an unprivileged id, so system files owned by root stay read-only.
	if p, err := exec.LookPath("unshare"); err == nil {
		var dirs []string
		for _, d := range []string{"/home", "/root", realHome()} {
			if d != "" {
				dirs = append(dirs, "'"+strings.ReplaceAll(d, "'", `'\''`)+"'")
			}
		}
		script := "mount --make-rprivate / 2>/dev/null || true; " +
			"for d in " + strings.Join(dirs, " ") + "; do [ -d \"$d\" ] && mount -t tmpfs tmpfs \"$d\" 2>/dev/null; done; " +
			`exec "$@"`
		argv := []string{p, "-rnm", "--", "/bin/sh", "-c", script, "chimera-sandbox", name}
		return append(argv, args...), "sandboxed: no network or home folder", true
	}
	return nil, "", false
}

func realHome() string {
	if h, err := os.UserHomeDir(); err == nil {
		return h
	}
	return ""
}

func (r runResult) JSON() string {
	b, _ := json.Marshal(r)
	return string(b)
}

func tail(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return "…" + s[len(s)-n:]
}

// sbplQuote quotes a path for a macOS sandbox profile.
func sbplQuote(p string) string {
	return `"` + strings.NewReplacer(`\`, `\\`, `"`, `\"`).Replace(p) + `"`
}

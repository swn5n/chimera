package main

// Runs untrusted Python and Blender scripts inside a real sandbox: no network,
// the home folder hidden, no other programs, and writes limited to a throwaway
// folder. If this computer can't provide that sandbox, the script isn't run at
// all. Two callers, each with its own consent:
//   - library test runs on the host computer (runScript), only when its owner
//     turned on "Test library scripts on this computer";
//   - the check of a looping long task's result on the computer that asked
//     (checkScript, hydra_check.go), only with "Run long tasks' scripts here
//     to check them".
//
// The riskyScript regex is only a fast pre-filter, never the boundary.

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"time"
)

type runResult struct {
	OK       bool    `json:"ok"`
	Skipped  bool    `json:"skipped,omitempty"` // couldn't sandbox here; not a failure of the script
	ExitCode int     `json:"exit_code"`
	Seconds  float64 `json:"seconds"`
	Summary  string  `json:"summary"`
	Output   string  `json:"output"`

	// Only for this computer, never sent to the hub.
	Stderr   string `json:"-"` // the end of what it printed as errors, paths hidden
	TimedOut bool   `json:"-"`
	NotRun   bool   `json:"-"` // refused, no program, or it couldn't start
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

// runScript test-runs a library entry, when this computer's owner allows it.
func (a *App) runScript(ctx context.Context, kind, script string) runResult {
	if !a.config().RunTests {
		return runResult{Summary: "Test runs are turned off on this computer."}
	}
	if riskyScript.MatchString(script) {
		return runResult{NotRun: true, Summary: "Refused: the script touches files, the network or other programs."}
	}
	return a.runSandboxed(ctx, kind, script, false)
}

// watchdog runs a sandboxed command ("$@") and, beside it, waits for its own
// standard input to close (the app holds the other end), then kills the
// command (by its pid: it may have left the process group with setsid) and
// the process group. The command's exit status is passed on. The watcher
// reads a copy of the input (fd 3): a background job's own input is /dev/null.
const watchdog = `exec 3<&0
"$@" </dev/null 3<&- &
c=$!
(read _ <&3; kill -KILL $c 2>/dev/null; kill -KILL 0) &
w=$!
exec 3<&-
wait $c
s=$?
kill $w 2>/dev/null
exit $s`

// renderStopMarker is what blenderStopAtRender prints when it stops a render.
const renderStopMarker = "chimera-check: stopped at the render"

// blenderStopAtRender ends Blender cleanly the moment a script starts a render:
// a check is about whether the script runs, and a render can take hours.
const blenderStopAtRender = `import bpy, os, sys
@bpy.app.handlers.persistent
def _chimera_stop_at_render(*args):
    print("` + renderStopMarker + `", flush=True)
    sys.stderr.flush()
    os._exit(0)
bpy.app.handlers.render_init.append(_chimera_stop_at_render)
`

// runSandboxed runs a script (kind run_python or run_blender) in the sandbox
// and says how it went. stopAtRender ends a Blender script at its first render.
func (a *App) runSandboxed(ctx context.Context, kind, script string, stopAtRender bool) runResult {
	dir, err := os.MkdirTemp("", "chimera-test-*")
	if err != nil {
		return runResult{NotRun: true, Summary: "Couldn't make a temporary folder: " + err.Error()}
	}
	defer os.RemoveAll(dir)
	path := filepath.Join(dir, "script.py")
	if err := os.WriteFile(path, []byte(script), 0o600); err != nil {
		return runResult{NotRun: true, Summary: err.Error()}
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
		args = []string{"-b", "--factory-startup", "--python-exit-code", "1"}
		if stopAtRender {
			args = append(args, "--python-expr", blenderStopAtRender)
		}
		// "--" ends Blender's own options, so the script can read sys.argv after it.
		args = append(args, "--python", path, "--")
		timeout = 120 * time.Second
	}
	if name == "" {
		return runResult{NotRun: true, Summary: "This computer doesn't have the program needed for this test."}
	}
	argv, how, ok := sandboxed(name, args, dir)
	if !ok {
		// No real sandbox here: never run an untrusted script unprotected.
		return runResult{Skipped: true, Summary: "This computer can't safely sandbox a test run, so it didn't run it."}
	}
	// A watchdog outside the sandbox stops the whole run if this app goes away
	// (even a crash): the pipe on its standard input closes, and it kills the
	// run's process group. The sandbox doesn't let the script fork out of it.
	alive, keep, err := os.Pipe()
	if err != nil {
		return runResult{NotRun: true, Summary: "Couldn't start: " + err.Error()}
	}
	defer alive.Close()
	defer keep.Close()
	argv = append([]string{"/bin/sh", "-c", watchdog, "chimera-check"}, argv...)

	cctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(cctx, argv[0], argv[1:]...)
	cmd.Dir = dir
	cmd.Env = scriptEnv(dir)
	cmd.Stdin = alive
	both, errOut := &tailBuffer{max: 4000}, &tailBuffer{max: 16000}
	cmd.Stdout = both
	cmd.Stderr = io.MultiWriter(both, errOut)
	// Its own process group, so stopping it also stops whatever it started.
	// Stopping goes through the watchdog, which also reaches a script that
	// left the group; WaitDelay and killGroup are the backstops.
	newProcessGroup(cmd)
	cmd.Cancel = func() error { keep.Close(); return nil }
	cmd.WaitDelay = 5 * time.Second
	hideWindow(cmd)
	start := time.Now()
	err = cmd.Run()
	killGroup(cmd) // anything it left behind
	out := both.String()

	if err != nil && sandboxDidNotStart(out) {
		// The sandbox itself couldn't start; treat it as "couldn't check here",
		// not as the script failing, so a good entry isn't flagged.
		return runResult{Skipped: true, Summary: "Couldn't start the sandbox, so the script didn't run.", Output: hidePaths(out, dir)}
	}
	if err != nil && strings.Contains(out, "fork: Operation not permitted") {
		// A launcher script that runs the program without exec can't start it
		// in the sandbox (no forking): couldn't check here, not a failure.
		return runResult{Skipped: true, Summary: "Couldn't start " + filepath.Base(name) + " through its launcher in the sandbox.", Output: hidePaths(out, dir)}
	}
	res := runResult{Seconds: round1(time.Since(start).Seconds()), Output: hidePaths(out, dir), Stderr: hidePaths(errOut.String(), dir)}
	switch {
	case cctx.Err() == context.DeadlineExceeded && ctx.Err() == nil:
		res.Summary = fmt.Sprintf("Timed out after %s.", timeout)
		res.ExitCode = -1
		res.TimedOut = true
	case ctx.Err() != nil:
		res.Skipped = true
		res.Summary = "The test run was cancelled."
	case cmd.ProcessState == nil:
		res.NotRun = true
		res.Summary = "Couldn't start: " + err.Error()
		res.ExitCode = -1
	default:
		// The exit code decides, also when Run only complained that a child
		// kept the output open after a clean exit (exec.ErrWaitDelay).
		res.ExitCode = cmd.ProcessState.ExitCode()
		if res.ExitCode != 0 {
			res.Summary = fmt.Sprintf("Exited with code %d after %.1fs.", res.ExitCode, res.Seconds)
			break
		}
		res.OK = true
		res.Summary = fmt.Sprintf("Ran cleanly in %.1fs.", res.Seconds)
		if kind == "run_blender" && strings.Contains(out, "Error:") {
			res.OK = false
			res.Summary = "Blender reported an error."
		}
	}
	if res.OK && how != "" {
		res.Summary += " (" + how + ")"
	}
	return res
}

// tailBuffer keeps the last max bytes written to it. The two goroutines that
// copy a command's output can write at once, hence the lock.
type tailBuffer struct {
	mu  sync.Mutex
	max int
	b   []byte
}

func (t *tailBuffer) Write(p []byte) (int, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.b = append(t.b, p...)
	if len(t.b) > 2*t.max {
		t.b = append([]byte(nil), t.b[len(t.b)-t.max:]...)
	}
	return len(p), nil
}

func (t *tailBuffer) String() string {
	t.mu.Lock()
	defer t.mu.Unlock()
	return tail(string(t.b), t.max)
}

// hidePaths takes the throwaway folder out of what a script printed, so its
// errors read File "script.py" and say nothing about this computer.
func hidePaths(s, dir string) string {
	var forms []string
	if real, err := filepath.EvalSymlinks(dir); err == nil {
		forms = append(forms, real+"/")
	}
	if strings.HasPrefix(dir, "/var/") {
		forms = append(forms, "/private"+dir+"/")
	}
	forms = append(forms, dir+"/")
	// Longest first, so "/private/var/…/" goes before the "/var/…/" inside it.
	for i := range forms {
		for j := i + 1; j < len(forms); j++ {
			if len(forms[j]) > len(forms[i]) {
				forms[i], forms[j] = forms[j], forms[i]
			}
		}
	}
	for _, f := range forms {
		s = strings.ReplaceAll(s, f, "")
	}
	return s
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
	return append([]string{p, "-p", macScriptProfile(name, dir), name}, args...), "sandboxed: no network or home folder", true
}

// macScriptProfile is the macOS sandbox for a script run with the program name
// in the throwaway folder dir: no network; the home folder and other volumes
// unreadable; writes only to dir; no other programs, no new processes, no
// signals to other processes, and no Apple Events, Finder or clipboard. Blender and Python read their own
// files, which may live in a home folder (~/Applications, pyenv), so the
// program's whole app bundle or install prefix is readable.
func macScriptProfile(name, dir string) string {
	realDir := resolved(dir)
	var reads, execs strings.Builder
	seen := map[*strings.Builder]map[string]bool{&reads: {}, &execs: {}}
	rule := func(b *strings.Builder, kind, p string) {
		if p != "" && !seen[b][kind+p] {
			seen[b][kind+p] = true
			fmt.Fprintf(b, " (%s %s)", kind, sbplQuote(p))
		}
	}
	program := func(p string) {
		rule(&reads, "subpath", hiddenRoot(toolHome(p)))
		rule(&execs, "literal", p)
		rule(&execs, "literal", resolved(p))
		rule(&execs, "subpath", execRoot(toolHome(p)))
	}
	rule(&reads, "subpath", realDir)
	program(name)
	if in := shebangInterp(name); in != "" {
		program(in) // a program that is a script (#!) runs its interpreter too
		// A launcher script (Homebrew's for Blender) starts the app it names.
		for _, app := range launchedApps(name) {
			rule(&reads, "subpath", hiddenRoot(app))
			rule(&execs, "subpath", app)
		}
	}
	return fmt.Sprintf(`(version 1)
(allow default)
(deny network*)
(deny file-read* (subpath "/Users") (subpath "/Volumes") (subpath "/private/var/root"))
(allow file-read*%s)
(deny file-write*)
(allow file-write* (subpath %s) (literal "/dev/null") (regex #"^/dev/tty") (regex #"^/dev/fd/"))
(deny appleevent-send)
(deny mach-lookup (global-name "com.apple.coreservices.launchservicesd") (global-name "com.apple.pasteboard.1"))
(deny signal)
(allow signal (target self))
(deny process-fork)
(deny process-exec*)
(allow process-exec*%s)`,
		reads.String(), sbplQuote(realDir), execs.String())
}

// hiddenRoot is d when the profile hides it (a program kept in a home folder
// or on another volume, which must stay readable for it to run), else "":
// everything else is readable anyway. Only an app bundle or a deep install
// folder: a shallow one such as "/" (the home of /bin/sh) or ~/.local would
// undo the hiding.
func hiddenRoot(d string) string {
	for _, p := range []string{"/Users/", "/Volumes/"} {
		if strings.HasPrefix(d, p) && (strings.HasSuffix(d, ".app") && strings.Count(d, "/") >= 3 || strings.Count(d, "/") >= 4) {
			return d
		}
	}
	return ""
}

var launcherTargetRe = regexp.MustCompile(`(?:['"](/[^'"\n]+?\.app/Contents/MacOS/[^'"\n/]+)['"]|(/[^'"\s]+?\.app/Contents/MacOS/[^'"\s/]+))`)

// launcherTarget is the app binary a launcher script (#!) starts, when it
// names exactly one that exists ("" otherwise): Homebrew's Blender is such a
// launcher, and the app itself runs in the sandbox, which can't fork.
func launcherTarget(name string) string {
	if shebangInterp(name) == "" {
		return ""
	}
	f, err := os.Open(name)
	if err != nil {
		return ""
	}
	defer f.Close()
	head := make([]byte, 4096)
	n, _ := io.ReadFull(f, head)
	found := ""
	for _, m := range launcherTargetRe.FindAllStringSubmatch(string(head[:n]), 4) {
		p := m[1] + m[2]
		if fi, err := os.Stat(p); err != nil || fi.IsDir() || (found != "" && found != p) {
			return ""
		}
		found = p
	}
	return found
}

var launchedAppRe = regexp.MustCompile(`(?:['"](/[^'"\n]+?\.app)|(/[^'"\s]+?\.app))/Contents/MacOS/`)

// launchedApps are the app bundles a launcher script starts (the first 4 KB).
func launchedApps(name string) []string {
	f, err := os.Open(name)
	if err != nil {
		return nil
	}
	defer f.Close()
	head := make([]byte, 4096)
	n, _ := io.ReadFull(f, head)
	var out []string
	for _, m := range launchedAppRe.FindAllStringSubmatch(string(head[:n]), 4) {
		out = append(out, m[1]+m[2]) // quoted (it may hold spaces) or not
	}
	return out
}

// execRoot is a program's folder that it may start its own helpers from: an
// app bundle or a deep install prefix, never a shared one like /usr or
// /opt/homebrew ("" then).
func execRoot(d string) string {
	if d == "" {
		return ""
	}
	if strings.Contains(d, ".app") || strings.Count(d, string(filepath.Separator)) >= 3 {
		return d
	}
	return ""
}

// shebangInterp is the interpreter a script program names on its #! line
// ("" for a real program, or for #!/usr/bin/env, which names none).
func shebangInterp(name string) string {
	f, err := os.Open(name)
	if err != nil {
		return ""
	}
	defer f.Close()
	head := make([]byte, 256)
	n, _ := io.ReadFull(f, head)
	line, _, _ := strings.Cut(string(head[:n]), "\n")
	rest, ok := strings.CutPrefix(line, "#!")
	if !ok {
		return ""
	}
	fields := strings.Fields(rest)
	if len(fields) == 0 || filepath.Base(fields[0]) == "env" {
		return ""
	}
	return fields[0]
}

func linuxSandbox(name string, args []string, dir string) ([]string, string, bool) {
	// bubblewrap is the strong option: a read-only view of the system, the home
	// folders replaced with empty ones, writes only to the work folder, no network.
	if p, err := exec.LookPath("bwrap"); err == nil {
		return bwrapScriptArgs(p, name, args, dir), "sandboxed: no network or home folder", true
	}
	// Otherwise a user + mount + network namespace: no network, and the home
	// folders hidden behind empty mounts so secrets aren't readable. The user
	// maps to an unprivileged id, so system files owned by root stay read-only.
	if p, err := exec.LookPath("unshare"); err == nil {
		var dirs []string
		for _, d := range []string{"/home", "/root", "/run", realHome()} {
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

// bwrapScriptArgs is the bubblewrap command for a script run. /run is hidden
// too: it holds the session's message bus, which can start other programs.
func bwrapScriptArgs(bwrap, name string, args []string, dir string) []string {
	argv := []string{bwrap, "--unshare-all", "--die-with-parent", "--new-session",
		"--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
		"--tmpfs", "/home", "--tmpfs", "/root", "--tmpfs", "/tmp", "--tmpfs", "/run"}
	if home := realHome(); home != "" && home != "/home" && home != "/root" {
		argv = append(argv, "--tmpfs", home)
	}
	argv = append(argv, "--bind", dir, dir, "--chdir", dir, "--")
	return append(argv, append([]string{name}, args...)...)
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

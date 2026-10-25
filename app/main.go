// Chimera: share idle GPUs with friends through Ollama.
//
// One binary does everything: the local interface (served on 127.0.0.1),
// the device agent that lends this computer's Ollama models, and, when you
// host a network, the hub that the other devices connect to.
package main

import (
	"context"
	"embed"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"
)

const Version = "0.6.1"

const (
	defaultUIPort  = 7470
	defaultHubPort = 7480
)

//go:embed web
var webFS embed.FS

func main() {
	// macOS Finder used to pass -psn_X_Y to app bundles; ignore it.
	var args []string
	for _, a := range os.Args[1:] {
		if !strings.HasPrefix(a, "-psn_") {
			args = append(args, a)
		}
	}
	flags := flag.NewFlagSet("chimera", flag.ExitOnError)
	uiPort := flags.Int("ui-port", defaultUIPort, "port for the local interface (127.0.0.1 only)")
	dataDir := flags.String("data-dir", "", "folder for settings, chats and logs")
	noOpen := flags.Bool("no-open", false, "don't open the interface on start")
	hubOnly := flags.Bool("hub-only", false, "run only a network hub, with no interface")
	hubPort := flags.Int("hub-port", 0, fmt.Sprintf("port for hosting a hub (default %d)", defaultHubPort))
	ollamaURL := flags.String("ollama", "", "Ollama address (default $OLLAMA_HOST or http://127.0.0.1:11434)")
	showVersion := flags.Bool("version", false, "print the version and exit")
	pluginTest := flags.String("plugin-test", "", "run the plugin in this folder once, the way the network does (input JSON on stdin), and exit")
	pluginOut := flags.String("plugin-out", "", "with --plugin-test: where to save the files it makes (default ./plugin-test-out)")
	_ = flags.Parse(args)

	if *showVersion {
		fmt.Println("chimera", Version)
		return
	}

	dir := *dataDir
	if dir == "" {
		dir = defaultDataDir()
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		fmt.Fprintln(os.Stderr, "cannot create data folder:", err)
		os.Exit(1)
	}
	if *pluginTest != "" {
		os.Exit(runPluginTest(dir, *pluginTest, *pluginOut))
	}
	setupLogging(dir)
	log.Printf("Chimera %s starting (data folder: %s)", Version, dir)

	if *hubOnly {
		runHubOnly(dir, *hubPort)
		return
	}
	// On a Mac, the process Launch Services started hands over to a detached copy
	// of itself and exits, so that opening Chimera again brings its window back
	// (see handOverOnMac). Terminal use with --no-open stays in the foreground.
	if !*noOpen && handOverOnMac(args) {
		return
	}

	// Only one Chimera per computer. If an older build is already running, ask
	// it to quit and take its place — Chimera lives in the background and only
	// quits from Settings, so otherwise an update never takes effect: opening the
	// new app would just bring up the old one's window. Same or newer: show it.
	ln, port, existing := claimUIPort(*uiPort)
	if existing != 0 && takeOverOlder(existing) {
		ln, port, existing = claimUIPort(*uiPort)
	}
	if existing != 0 {
		log.Printf("Chimera is already running on port %d, opening it", existing)
		cfg := loadConfig(dir)
		openURL(fmt.Sprintf("http://127.0.0.1:%d/", existing), cfg.AppWindow)
		return
	}
	if ln == nil {
		log.Fatalf("couldn't open a local port for the interface (tried %d-%d)", *uiPort, *uiPort+4)
	}

	app := NewApp(dir, port, *hubPort, *ollamaURL)
	app.Start()

	srv := &http.Server{Handler: app.routes(), ReadHeaderTimeout: 10 * time.Second}
	go func() {
		if err := srv.Serve(ln); err != nil && err != http.ErrServerClosed {
			log.Fatalf("interface server: %v", err)
		}
	}()
	url := fmt.Sprintf("http://127.0.0.1:%d/", port)
	log.Printf("Interface ready at %s", url)
	if !*noOpen {
		go func() {
			time.Sleep(300 * time.Millisecond)
			openURL(url, app.config().AppWindow)
		}()
	}

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt, syscall.SIGTERM)
	select {
	case <-sig:
	case <-app.quit:
	}
	log.Printf("Shutting down")
	app.Shutdown()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = srv.Shutdown(ctx)
}

func defaultDataDir() string {
	base, err := os.UserConfigDir()
	if err != nil || base == "" {
		home, _ := os.UserHomeDir()
		base = home
	}
	return filepath.Join(base, "Chimera")
}

func setupLogging(dir string) {
	path := filepath.Join(dir, "chimera.log")
	if fi, err := os.Stat(path); err == nil && fi.Size() > 5<<20 {
		_ = os.Rename(path, path+".1")
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	// File first: on Windows GUI builds stdout is invalid and MultiWriter
	// stops at the first writer that fails.
	log.SetOutput(io.MultiWriter(f, os.Stdout))
	log.SetFlags(log.LstdFlags)
}

// claimUIPort returns a listener on the first free port, or the port of an
// already-running Chimera.
func claimUIPort(start int) (net.Listener, int, int) {
	for p := start; p <= start+4; p++ {
		if isChimera(p) {
			return nil, 0, p
		}
		ln, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", p))
		if err == nil {
			return ln, p, 0
		}
	}
	return nil, 0, 0
}

func isChimera(port int) bool {
	c := http.Client{Timeout: 700 * time.Millisecond}
	resp, err := c.Get(fmt.Sprintf("http://127.0.0.1:%d/api/ping", port))
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
	return strings.Contains(string(b), `"app":"chimera"`)
}

// handOverOnMac makes "open Chimera again" work on a Mac.
//
// Launch Services treats an app as running for as long as the process it
// launched is alive, and a second double-click only sends that process a
// "reopen" Apple event — which a windowless program with no AppKit run loop
// never sees. So before this, opening Chimera while it was running did nothing
// at all, and people took that for "it's already running" with no way back to
// the window. Now the process Launch Services started spawns a detached copy of
// itself (marked CHIMERA_DAEMON) and exits at once. macOS then sees Chimera as
// not running, so the next double-click runs main again: it finds the daemon on
// the interface port, opens its window, and exits. Returns true when this
// process should exit because the daemon is up. CHIMERA_NO_DAEMON=1 disables it.
func handOverOnMac(args []string) bool {
	mac := runtime.GOOS == "darwin" || os.Getenv("CHIMERA_HANDOVER_TEST") != "" // the override lets Linux tests exercise this path
	if !mac || os.Getenv("CHIMERA_DAEMON") != "" || os.Getenv("CHIMERA_NO_DAEMON") != "" {
		return false
	}
	exe, err := os.Executable()
	if err != nil {
		return false
	}
	cmd := exec.Command(exe, args...)
	cmd.Env = append(os.Environ(), "CHIMERA_DAEMON=1")
	detach(cmd)
	if err := cmd.Start(); err != nil {
		log.Printf("couldn't start the background copy (%v); running in this process instead", err)
		return false
	}
	log.Printf("Handed over to the background Chimera (pid %d)", cmd.Process.Pid)
	return true
}

// runningVersion asks the Chimera on port which version it is ("" if it's too
// old to say, which itself means it predates this build).
func runningVersion(port int) string {
	c := http.Client{Timeout: 700 * time.Millisecond}
	resp, err := c.Get(fmt.Sprintf("http://127.0.0.1:%d/api/ping", port))
	if err != nil {
		return ""
	}
	defer resp.Body.Close()
	var v struct {
		Version string `json:"version"`
	}
	_ = json.NewDecoder(io.LimitReader(resp.Body, 512)).Decode(&v)
	return v.Version
}

// takeOverOlder asks an older Chimera holding the interface port to quit so this
// build can start in its place. Returns true once the port is free. A running
// copy that is the same version or newer is left alone.
func takeOverOlder(port int) bool {
	theirs := runningVersion(port)
	if theirs != "" && !versionLess(theirs, Version) {
		return false
	}
	shown := theirs
	if shown == "" {
		shown = "an older version"
	}
	log.Printf("Chimera %s is running on port %d; asking it to quit so %s can take over", shown, port, Version)
	req, err := http.NewRequest(http.MethodPost, fmt.Sprintf("http://127.0.0.1:%d/api/quit", port), nil)
	if err != nil {
		return false
	}
	req.Header.Set("X-Chimera", "1")
	c := http.Client{Timeout: 2 * time.Second}
	resp, err := c.Do(req)
	if err != nil {
		log.Printf("couldn't ask the old Chimera to quit: %v", err)
		return false
	}
	resp.Body.Close()
	for i := 0; i < 50; i++ { // give it up to ~10 s to shut down and free the port
		time.Sleep(200 * time.Millisecond)
		if !isChimera(port) {
			log.Printf("Old Chimera quit; taking over")
			return true
		}
	}
	log.Printf("Old Chimera didn't quit in time; opening it instead")
	return false
}

// versionLess reports whether dotted version a is older than b ("0.3.0" < "0.4.0").
func versionLess(a, b string) bool {
	pa, pb := strings.Split(strings.TrimSpace(a), "."), strings.Split(strings.TrimSpace(b), ".")
	for i := 0; i < len(pa) || i < len(pb); i++ {
		var x, y int
		if i < len(pa) {
			x, _ = strconv.Atoi(pa[i])
		}
		if i < len(pb) {
			y, _ = strconv.Atoi(pb[i])
		}
		if x != y {
			return x < y
		}
	}
	return false
}

func runHubOnly(dir string, port int) {
	cfg := loadConfig(dir)
	if port == 0 {
		port = cfg.HostPort
	}
	if port == 0 {
		port = defaultHubPort
	}
	h := NewHub(filepath.Join(dir, "hub.json"), port)
	if cfg.Owner != "" {
		h.EnsureName(cfg.Owner + "'s network")
		h.EnsureOwner(cfg.Owner)
	}
	if err := h.Start(); err != nil {
		log.Fatalf("hub: %v", err)
	}
	fmt.Printf("\nChimera hub %s is running on port %d\n", Version, port)
	fmt.Printf("Network: %s\nInvite code: %s\n\nFriends can join at:\n", h.Name(), h.Invite())
	for _, a := range localAddresses() {
		fmt.Printf("  %s:%d   (%s)\n", a.IP, port, a.Label)
	}
	fmt.Println()
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt, syscall.SIGTERM)
	<-sig
	h.Stop()
}

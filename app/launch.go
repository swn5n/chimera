package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
)

func homeDir() string {
	h, _ := os.UserHomeDir()
	return h
}

func macOllamaApps() []string {
	return []string{"/Applications/Ollama.app", filepath.Join(homeDir(), "Applications", "Ollama.app")}
}

// Command-line installs that a Finder-launched app won't find on its PATH.
func ollamaBinaries() []string {
	var out []string
	if p, err := exec.LookPath("ollama"); err == nil {
		out = append(out, p)
	}
	switch runtime.GOOS {
	case "darwin":
		out = append(out, "/opt/homebrew/bin/ollama", "/usr/local/bin/ollama", "/Applications/Ollama.app/Contents/Resources/ollama")
	case "linux":
		out = append(out, "/usr/local/bin/ollama", "/usr/bin/ollama")
	case "windows":
		out = append(out, filepath.Join(os.Getenv("LOCALAPPDATA"), "Programs", "Ollama", "ollama.exe"))
	}
	var existing []string
	for _, p := range out {
		if fileExists(p) {
			existing = append(existing, p)
		}
	}
	return existing
}

func windowsOllamaApp() string {
	for _, p := range []string{
		filepath.Join(os.Getenv("LOCALAPPDATA"), "Programs", "Ollama", "ollama app.exe"),
		`C:\Program Files\Ollama\ollama app.exe`,
	} {
		if fileExists(p) {
			return p
		}
	}
	return ""
}

func ollamaInstalled() bool {
	switch runtime.GOOS {
	case "darwin":
		for _, p := range macOllamaApps() {
			if fileExists(p) {
				return true
			}
		}
	case "windows":
		if windowsOllamaApp() != "" {
			return true
		}
	}
	return len(ollamaBinaries()) > 0
}

// startOllama opens the Ollama app (or `ollama serve`) in the background.
func startOllama() error {
	switch runtime.GOOS {
	case "darwin":
		for _, p := range macOllamaApps() {
			if fileExists(p) {
				return exec.Command("open", "-a", p).Run()
			}
		}
	case "windows":
		if p := windowsOllamaApp(); p != "" {
			return exec.Command(p).Start()
		}
	}
	bins := ollamaBinaries()
	if len(bins) == 0 {
		return errOllamaMissing
	}
	cmd := exec.Command(bins[0], "serve")
	detach(cmd)
	if err := cmd.Start(); err != nil {
		return err
	}
	go func() { _ = cmd.Wait() }()
	return nil
}

// openURL shows the interface, in a browser app window when possible.
func openURL(u string, appWindow bool) {
	if appWindow && openAppWindow(u) {
		return
	}
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		cmd = exec.Command("open", u)
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", u)
	default:
		cmd = exec.Command("xdg-open", u)
	}
	_ = cmd.Start()
}

func openAppWindow(u string) bool {
	args := []string{"--app=" + u, "--window-size=1340,900"}
	switch runtime.GOOS {
	case "darwin":
		for _, name := range []string{"Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium", "Arc"} {
			for _, dir := range []string{"/Applications", filepath.Join(homeDir(), "Applications")} {
				if fileExists(filepath.Join(dir, name+".app")) {
					if name == "Arc" {
						continue // Arc ignores --app
					}
					all := append([]string{"-na", name, "--args"}, args...)
					return exec.Command("open", all...).Start() == nil
				}
			}
		}
	case "windows":
		pf := os.Getenv("ProgramFiles")
		pf86 := os.Getenv("ProgramFiles(x86)")
		local := os.Getenv("LOCALAPPDATA")
		for _, p := range []string{
			filepath.Join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
			filepath.Join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
			filepath.Join(pf, "Google", "Chrome", "Application", "chrome.exe"),
			filepath.Join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
			filepath.Join(local, "Google", "Chrome", "Application", "chrome.exe"),
		} {
			if fileExists(p) {
				return exec.Command(p, args...).Start() == nil
			}
		}
	default:
		for _, name := range []string{"google-chrome", "chromium", "chromium-browser", "microsoft-edge", "brave-browser"} {
			if p, err := exec.LookPath(name); err == nil {
				return exec.Command(p, args...).Start() == nil
			}
		}
	}
	return false
}

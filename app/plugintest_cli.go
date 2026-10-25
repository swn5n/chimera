package main

// chimera --plugin-test <folder>: runs a plugin once, exactly the way a worker
// runs a step for the network (probe, sandbox, progress, files), with the
// input JSON on stdin. Nothing joins a network and no window opens; it's for
// people writing or installing plugins.

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
)

func runPluginTest(dataDir, pluginDir, outDir string) int {
	fail := func(format string, args ...any) int {
		fmt.Fprintf(os.Stderr, "plugin test: "+format+"\n", args...)
		return 1
	}
	dir, err := filepath.Abs(pluginDir)
	if err != nil {
		return fail("%v", err)
	}
	m, mod, err := readManifest(dir)
	if err != nil {
		return fail("%v", err)
	}
	a := &App{dataDir: dataDir, cfg: Config{DeviceName: friendlyComputerName(), LendPlugins: true}, quit: make(chan struct{})}
	a.tools = NewToolScanner(a)
	if p := findPython(); p != "" {
		a.tools.ext["python"] = ToolInfo{ID: "python", Have: true, Path: p}
	}
	if p, v := findBlender(); p != "" {
		a.tools.ext["blender"] = ToolInfo{ID: "blender", Have: true, Via: v, Path: p}
	}
	p := &installedPlugin{Dir: dir, Manifest: m, modTime: mod}
	p.Probe, p.Err = a.tools.probePlugin(p)
	probe, _ := json.Marshal(p.Probe)
	fmt.Fprintf(os.Stderr, "probe %s %s: %s\n", m.ID, m.Version, probe)
	if p.Err != "" {
		return fail("%s", p.Err)
	}
	a.tools.plugins = map[string]*installedPlugin{m.ID: p}
	input, err := io.ReadAll(io.LimitReader(os.Stdin, pluginInputMax+1))
	if err != nil {
		return fail("reading stdin: %v", err)
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	res := a.runPlugin(ctx, "plugin-test", m.ID, input, func(msg string, f float64) {
		if f >= 0 {
			fmt.Fprintf(os.Stderr, "%3.0f%%  %s\n", f*100, msg)
		} else {
			fmt.Fprintf(os.Stderr, "      %s\n", msg)
		}
	})
	if outDir == "" {
		outDir = "plugin-test-out"
	}
	var saved []StepFile
	for _, f := range res.Files {
		if err := os.MkdirAll(outDir, 0o755); err != nil {
			return fail("%v", err)
		}
		if err := os.WriteFile(filepath.Join(outDir, f.Name), f.Data, 0o644); err != nil {
			return fail("%v", err)
		}
		saved = append(saved, f.withoutData())
	}
	out, _ := json.MarshalIndent(map[string]any{"ok": res.OK, "summary": res.Summary, "error": res.Error,
		"retryable": res.Retryable, "seconds": res.Seconds, "files": saved, "saved_to": outDir}, "", "  ")
	fmt.Println(string(out))
	if !res.OK {
		return 1
	}
	return 0
}

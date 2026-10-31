package main

// chimera --check-result <file>: checks a long task's result the way looping
// mode does (which script it would run, the sandbox, how it judges the run)
// and prints the verdict as JSON. The file is a reply (.md) or a script (.py).
// Nothing joins a network and no window opens; it's for trying the check on
// real results. Running it is the person's own explicit request, so it runs
// whatever the "Run long tasks' scripts here" setting says.

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

func runCheckResult(dataDir, path, goal string) int {
	fail := func(format string, args ...any) int {
		fmt.Fprintf(os.Stderr, "check result: "+format+"\n", args...)
		return 2
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return fail("%v", err)
	}
	a := &App{dataDir: dataDir, cfg: Config{DeviceName: friendlyComputerName(), CheckResults: true}, quit: make(chan struct{})}
	a.tools = NewToolScanner(a)
	if p := findPython(); p != "" {
		a.tools.ext["python"] = ToolInfo{ID: "python", Have: true, Path: p, Version: strings.TrimSpace(runOut(5*time.Second, p, "--version"))}
	}
	if p, v := findBlender(); p != "" {
		a.tools.ext["blender"] = ToolInfo{ID: "blender", Have: true, Via: v, Path: p, Version: v}
	}
	var kind, script, why string
	if strings.HasSuffix(strings.ToLower(path), ".py") {
		kind, script = "run_python", string(b)
		if bpyImport.Match(b) {
			kind = "run_blender"
		}
	} else {
		kind, script, why = pickScript(map[string]bool{"blender": true, "code": true}, string(b))
		if kind == "" {
			return fail("no script to check in %s", path)
		}
	}
	runner, blocked := a.scriptBlocker(kind, script)
	if why == "" {
		why = blocked
	}
	var c resultCheck
	if why != "" {
		c = resultCheck{Outcome: "skipped", Runner: runner, Summary: sentence("Didn't run the script: " + why)}
	} else {
		ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
		defer cancel()
		fmt.Fprintf(os.Stderr, "running it in %s, sandboxed…\n", runner)
		c = judgeRun(kind, runner, goal, script, a.checkScript(ctx, kind, script))
		if kind != "" && !strings.HasSuffix(strings.ToLower(path), ".py") {
			c = otherBlocks(c, string(b), script)
		}
		if c.Outcome == "failed" {
			c.Critique = crashCritique(kind, runner, c)
		}
	}
	out, _ := json.MarshalIndent(map[string]any{"check": c, "critique": c.Critique}, "", "  ")
	fmt.Println(string(out))
	switch c.Outcome {
	case "passed":
		return 0
	case "failed":
		return 1
	}
	return 2
}

//go:build !windows

package main

import (
	"os"
	"os/exec"
	"strconv"
	"syscall"
)

func hideWindow(cmd *exec.Cmd) {}

func detach(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
}

// newProcessGroup starts cmd in a process group of its own, so stopping it
// can reach everything it started (a plugin's Blender, for example).
func newProcessGroup(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
}

// terminateGroup asks cmd's whole process group to stop (SIGTERM); the
// caller's WaitDelay kills it if it doesn't.
func terminateGroup(cmd *exec.Cmd) error {
	if cmd.Process == nil {
		return nil
	}
	if err := syscall.Kill(-cmd.Process.Pid, syscall.SIGTERM); err != nil {
		return cmd.Process.Signal(syscall.SIGTERM)
	}
	return nil
}

// killGroup stops whatever is left of cmd's process group.
func killGroup(cmd *exec.Cmd) {
	if cmd.Process != nil {
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
}

// interruptGroup sends Ctrl-C (SIGINT) to cmd's process group: a server
// started with newProcessGroup shuts down cleanly on it.
func interruptGroup(cmd *exec.Cmd) error {
	if cmd.Process == nil {
		return nil
	}
	if err := syscall.Kill(-cmd.Process.Pid, syscall.SIGINT); err != nil {
		return cmd.Process.Signal(syscall.SIGINT)
	}
	return nil
}

// startWatchdog starts a small shell, in a process group of its own, that waits
// for its standard input to close and then stops process group pgid (Ctrl-C,
// then a kill if it's still there 10 s later). This app holds the other end of that pipe, so a
// server it started can't outlive it, even if the app crashes or is killed.
// Kill the returned command first when stopping the server yourself.
func startWatchdog(pgid int) (*exec.Cmd, *os.File) {
	r, w, err := os.Pipe()
	if err != nil {
		return nil, nil
	}
	cmd := exec.Command("/bin/sh", "-c", `trap '' INT HUP
read _
kill -s INT -- -"$1" 2>/dev/null || exit 0
i=0
while [ $i -lt 20 ] && kill -0 -- -"$1" 2>/dev/null; do sleep 0.5; i=$((i+1)); done
kill -s KILL -- -"$1" 2>/dev/null`, "chimera-watch", strconv.Itoa(pgid))
	cmd.Stdin = r
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		r.Close()
		w.Close()
		return nil, nil
	}
	r.Close()
	go func() { _ = cmd.Wait() }()
	return cmd, w
}

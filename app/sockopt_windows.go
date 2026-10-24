//go:build windows

package main

import (
	"net"
	"syscall"
)

// enableBroadcast lets a UDP socket send to broadcast addresses (see the Unix
// version). Windows needs the handle form of setsockopt.
func enableBroadcast(c net.PacketConn) {
	uc, ok := c.(*net.UDPConn)
	if !ok {
		return
	}
	rc, err := uc.SyscallConn()
	if err != nil {
		return
	}
	_ = rc.Control(func(fd uintptr) {
		_ = syscall.SetsockoptInt(syscall.Handle(fd), syscall.SOL_SOCKET, syscall.SO_BROADCAST, 1)
	})
}

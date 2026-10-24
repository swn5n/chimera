//go:build darwin || linux

package main

import (
	"net"
	"syscall"
)

// enableBroadcast lets a UDP socket send to broadcast addresses. Without it the
// OS silently drops packets aimed at 255.255.255.255 or a subnet broadcast, so
// LAN discovery never reaches other machines.
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
		_ = syscall.SetsockoptInt(int(fd), syscall.SOL_SOCKET, syscall.SO_BROADCAST, 1)
	})
}

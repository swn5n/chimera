package main

import (
	"net"
	"sort"
	"strings"
)

type LocalAddr struct {
	IP    string `json:"ip"`
	Label string `json:"label"`
}

var tailscaleNet = mustCIDR("100.64.0.0/10")

func mustCIDR(s string) *net.IPNet {
	_, n, _ := net.ParseCIDR(s)
	return n
}

// localAddresses lists the IPv4 addresses friends could use to reach this hub.
func localAddresses() []LocalAddr {
	var out []LocalAddr
	ifaces, _ := net.Interfaces()
	for _, ifc := range ifaces {
		if ifc.Flags&net.FlagUp == 0 || ifc.Flags&net.FlagLoopback != 0 {
			continue
		}
		addrs, _ := ifc.Addrs()
		for _, a := range addrs {
			ipn, ok := a.(*net.IPNet)
			if !ok {
				continue
			}
			ip := ipn.IP.To4()
			if ip == nil || ip.IsLinkLocalUnicast() {
				continue
			}
			label := "Other network"
			switch {
			case tailscaleNet.Contains(ip):
				label = "Tailscale"
			case ip.IsPrivate():
				label = "Same Wi-Fi / local network"
			}
			name := strings.ToLower(ifc.Name)
			if label == "Other network" && (strings.HasPrefix(name, "docker") || strings.HasPrefix(name, "br-") || strings.HasPrefix(name, "veth")) {
				continue
			}
			out = append(out, LocalAddr{IP: ip.String(), Label: label})
		}
	}
	rank := map[string]int{"Same Wi-Fi / local network": 0, "Tailscale": 1, "Other network": 2}
	sort.SliceStable(out, func(i, j int) bool { return rank[out[i].Label] < rank[out[j].Label] })
	return out
}

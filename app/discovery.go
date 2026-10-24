package main

// LAN discovery over UDP, so friends on the same network don't have to type an
// address or invite code. The host answers small "who's there?" probes; a
// joining device broadcasts a probe and gets back the host's address and, when
// the host allows it, the invite code too — then it can join on its own.

import (
	"encoding/json"
	"log"
	"net"
	"strconv"
	"time"
)

const discoProbe = "CHIMERA-DISCOVER/1"

type discoReply struct {
	App      string `json:"app"`
	HubID    string `json:"hub_id"`
	Name     string `json:"name"`
	Port     int    `json:"port"`
	Proto    int    `json:"proto"`
	Version  string `json:"version"`
	AutoJoin bool   `json:"auto_join"`
	Invite   string `json:"invite,omitempty"` // only when AutoJoin: lets the device join with no typing
	Chosen   bool   `json:"chosen"`           // a person started this host (or it came back from settings)
	Members  int    `json:"members"`          // devices online
	Since    int64  `json:"since"`            // hub created, unix seconds
}

// DiscoveredNet is a network found on the local network.
type DiscoveredNet struct {
	HubID    string `json:"hub_id"`
	Name     string `json:"name"`
	Address  string `json:"address"` // ip:port to join
	Version  string `json:"version"`
	AutoJoin bool   `json:"auto_join"`
	Invite   string `json:"invite,omitempty"`
	SameApp  bool   `json:"same_app"`
	Chosen   bool   `json:"chosen"`
	Members  int    `json:"members"`
	Since    int64  `json:"since"`
}

// hostStanding ranks open hosts so that, when two meet, they agree which one
// keeps hosting. See outranks.
type hostStanding struct {
	ID      string
	Chosen  bool
	Members int
	Since   int64
}

// outranks reports whether host a should keep hosting over host b: chosen by a
// person beats auto-elected; then more devices online; then up longer (smaller
// Since); then the smaller id as a final tie-break so the answer is always
// definite and the same from both sides.
func outranks(a, b hostStanding) bool {
	if a.Chosen != b.Chosen {
		return a.Chosen
	}
	if a.Members != b.Members {
		return a.Members > b.Members
	}
	if a.Since != b.Since && a.Since != 0 && b.Since != 0 {
		return a.Since < b.Since
	}
	return a.ID < b.ID
}

// ---------- host side ----------

func (h *Hub) startDiscovery() {
	conn, err := net.ListenPacket("udp4", net.JoinHostPort("", strconv.Itoa(discoveryPort)))
	if err != nil {
		log.Printf("hub: discovery off (port %d: %v)", discoveryPort, err)
		return
	}
	h.mu.Lock()
	h.disco = conn
	h.mu.Unlock()
	go h.discoveryLoop(conn)
}

func (h *Hub) stopDiscovery() {
	h.mu.Lock()
	c := h.disco
	h.disco = nil
	h.mu.Unlock()
	if c != nil {
		_ = c.Close()
	}
}

func (h *Hub) discoveryLoop(conn net.PacketConn) {
	buf := make([]byte, 1024)
	for {
		n, addr, err := conn.ReadFrom(buf)
		if err != nil {
			return // closed on Stop
		}
		if string(buf[:n]) != discoProbe {
			continue
		}
		h.mu.Lock()
		st := h.standingLocked()
		reply := discoReply{
			App: "chimera-hub", HubID: h.st.HubID, Name: h.st.Name, Port: h.port,
			Proto: hubProto, Version: Version, AutoJoin: h.st.AutoJoin,
			Chosen: st.Chosen, Members: st.Members, Since: st.Since,
		}
		if h.st.AutoJoin {
			reply.Invite = h.st.Invite
		}
		h.mu.Unlock()
		b, _ := json.Marshal(reply)
		_, _ = conn.WriteTo(b, addr)
	}
}

// ---------- device side ----------

// discoverNetworks broadcasts a probe and collects hosts that answer. ownHubID
// (if hosting) is marked SameApp so the interface can skip it.
func discoverNetworks(timeout time.Duration, ownHubID string) []DiscoveredNet {
	conn, err := net.ListenPacket("udp4", ":0")
	if err != nil {
		return nil
	}
	defer conn.Close()
	enableBroadcast(conn) // without this the OS drops our broadcast probes
	if uc, ok := conn.(*net.UDPConn); ok {
		_ = uc.SetWriteBuffer(1 << 16)
	}
	// Send to the global broadcast, each interface's broadcast, and loopback
	// (so a host and a device on the same computer still find each other).
	targets := map[string]bool{"255.255.255.255": true, "127.0.0.1": true}
	for _, b := range broadcastAddrs() {
		targets[b] = true
	}
	msg := []byte(discoProbe)
	for t := range targets {
		dst := &net.UDPAddr{IP: net.ParseIP(t), Port: discoveryPort}
		_, _ = conn.WriteTo(msg, dst)
	}

	found := map[string]DiscoveredNet{}
	_ = conn.SetReadDeadline(time.Now().Add(timeout))
	buf := make([]byte, 2048)
	for {
		n, addr, err := conn.ReadFrom(buf)
		if err != nil {
			break // deadline
		}
		var r discoReply
		if json.Unmarshal(buf[:n], &r) != nil || r.App != "chimera-hub" {
			continue
		}
		host, _, _ := net.SplitHostPort(addr.String())
		if host == "" {
			host = addr.String()
		}
		d := DiscoveredNet{
			HubID: r.HubID, Name: r.Name, Address: net.JoinHostPort(host, strconv.Itoa(r.Port)),
			Version: r.Version, AutoJoin: r.AutoJoin, Invite: r.Invite, SameApp: r.HubID == ownHubID,
			Chosen: r.Chosen, Members: r.Members, Since: r.Since,
		}
		if cur, ok := found[r.HubID]; !ok || (!cur.AutoJoin && d.AutoJoin) {
			found[r.HubID] = d
		}
	}
	out := make([]DiscoveredNet, 0, len(found))
	for _, d := range found {
		out = append(out, d)
	}
	return out
}

// broadcastAddrs returns the IPv4 broadcast address of each up, non-loopback interface.
func broadcastAddrs() []string {
	var out []string
	ifaces, err := net.Interfaces()
	if err != nil {
		return out
	}
	for _, ifi := range ifaces {
		if ifi.Flags&net.FlagUp == 0 || ifi.Flags&net.FlagBroadcast == 0 {
			continue
		}
		addrs, _ := ifi.Addrs()
		for _, a := range addrs {
			ipnet, ok := a.(*net.IPNet)
			if !ok || ipnet.IP.To4() == nil {
				continue
			}
			ip := ipnet.IP.To4()
			mask := ipnet.Mask
			bc := make(net.IP, 4)
			for i := 0; i < 4; i++ {
				bc[i] = ip[i] | ^mask[i]
			}
			out = append(out, bc.String())
		}
	}
	return out
}

// discoverAndMaybeJoin scans for networks; if the device isn't in one and a
// single auto-join network is found, it joins it. Returns what it found.
func (a *App) discoverAndMaybeJoin(autoJoin bool) []DiscoveredNet {
	own := ""
	a.hubMu.Lock()
	if a.hub != nil {
		own = a.hub.HubID()
	}
	a.hubMu.Unlock()
	nets := discoverNetworks(1200*time.Millisecond, own)
	if !autoJoin || a.config().Joined() {
		return nets
	}
	var pick *DiscoveredNet
	for i := range nets {
		if nets[i].SameApp || !nets[i].AutoJoin || nets[i].Invite == "" {
			continue
		}
		if pick != nil {
			return nets // more than one: let the person choose
		}
		pick = &nets[i]
	}
	if pick != nil {
		cfg := a.config()
		owner, device := cfg.Owner, cfg.DeviceName
		if owner == "" {
			return nets // need a name first
		}
		if err := a.joinNetwork(pick.Address, pick.Invite, owner, device); err != nil {
			log.Printf("auto-join %s: %v", pick.Name, err)
		} else {
			log.Printf("Auto-joined %q on the local network", pick.Name)
		}
	}
	return nets
}

package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

type App struct {
	dataDir        string
	uiPort         int
	hubPortFlag    int
	ollamaOverride string
	poolBusy       int32 // 1 while autoPool is running, so overlapping calls don't race each other

	cfgMu sync.Mutex
	cfg   Config

	sysMu sync.Mutex
	sys   SysInfo

	ollama   *OllamaMonitor
	node     *Node
	sessions *SessionStore
	gens     *GenManager
	tasks    *TaskManager
	perf     *PerfStore
	tools    *ToolScanner

	hubMu  sync.Mutex
	hub    *Hub
	hubErr string

	subMu sync.Mutex
	subs  map[chan struct{}]struct{}

	quit     chan struct{}
	quitOnce sync.Once
}

func NewApp(dataDir string, uiPort, hubPort int, ollamaURL string) *App {
	a := &App{
		dataDir:        dataDir,
		uiPort:         uiPort,
		hubPortFlag:    hubPort,
		ollamaOverride: ollamaURL,
		subs:           map[chan struct{}]struct{}{},
		quit:           make(chan struct{}),
	}
	a.cfg = loadConfig(dataDir)
	if hubPort != 0 {
		a.cfg.HostPort = hubPort
	}
	url := a.cfg.OllamaURL
	if ollamaURL != "" {
		url = ollamaURL
	}
	a.ollama = NewOllamaMonitor(a, url)
	a.node = NewNode(a)
	a.sessions = NewSessionStore(dataDir)
	a.gens = NewGenManager(a)
	a.tasks = NewTaskManager(a)
	a.perf = NewPerfStore(dataDir)
	a.tools = NewToolScanner(a)
	_ = saveConfig(dataDir, a.cfg)
	return a
}

func (a *App) Start() {
	go func() {
		s := detectSysInfo()
		if path := os.Getenv("CHIMERA_SYSINFO"); path != "" { // for testing: pretend to be other hardware
			if b, err := os.ReadFile(path); err == nil {
				_ = json.Unmarshal(b, &s)
			}
		}
		a.sysMu.Lock()
		a.sys = s
		a.sysMu.Unlock()
		a.updateConfig(func(c *Config) {
			if !c.DefaultsApplied {
				c.MaxModelGB = defaultLendLimitGB(s)
				c.DefaultsApplied = true
			}
		})
		log.Printf("This computer: %s %s, %s, %.0f GB RAM", s.OS, s.OSVersion, s.Chip, s.RAMGB)
		a.notify()
	}()
	go a.ollama.loop()
	go a.tools.loop()
	go a.node.membershipLoop()
	go a.staleHubWatch()

	cfg := a.config()
	if cfg.Hosting {
		if err := a.startHosting(); err != nil {
			log.Printf("couldn't start hosting: %v", err)
		}
	}
	if cfg.ConnectOnLaunch && cfg.Joined() {
		go func() {
			time.Sleep(3 * time.Second)
			if err := a.node.Connect(); err != nil {
				log.Printf("connect on launch: %v", err)
			}
		}()
	}
	// Not in a network and not hosting: get into the pool on our own — a baked
	// or configured pool address first (works across networks), then the local
	// Wi-Fi, electing a host if nobody is hosting yet.
	if !cfg.Joined() && !cfg.Hosting {
		go a.autoPool()
	}
}

// autoPool joins the shared pool with no setup: a pool address if there is one,
// otherwise a host found on the Wi-Fi, otherwise it becomes the host.
//
// Every stage is best-effort and racy — a host we elect may clash with another
// fresh device, and a discovery sweep can miss a host that announced a moment
// later — so this is a bounded retry loop. A device that loses the host race
// (or whose first sweep came up empty) comes back around and joins the winner
// instead of giving up, so no device is ever left orphaned outside the pool.
func (a *App) autoPool() {
	if os.Getenv("CHIMERA_NO_AUTOPOOL") != "" { // scripted tests drive host/join themselves
		return
	}
	if !atomic.CompareAndSwapInt32(&a.poolBusy, 0, 1) {
		return // already running
	}
	defer atomic.StoreInt32(&a.poolBusy, 0)
	time.Sleep(2 * time.Second)
	a.ensureOwner()

	for attempt := 0; attempt < 8; attempt++ {
		if a.config().Joined() || a.config().Hosting {
			return
		}

		// 1. A pool hub (any network). Open pools accept a code-less join.
		if addr := a.config().pool(); addr != "" {
			cfg := a.config()
			if err := a.joinNetwork(addr, cfg.Invite, cfg.Owner, cfg.DeviceName); err == nil {
				log.Printf("Auto-joined the pool at %s", addr)
				a.lendIfWanted()
				return
			}
		}

		// 2. A host already up on the local Wi-Fi.
		a.discoverAndMaybeJoin(true)
		if a.config().Joined() {
			a.lendIfWanted()
			return
		}

		// 3. Nobody is hosting here: wait a random moment (so two fresh devices
		// don't both grab it), look once more, then host the pool ourselves.
		time.Sleep(time.Duration(300+randInt(1500)) * time.Millisecond)
		a.discoverAndMaybeJoin(true)
		if a.config().Joined() {
			a.lendIfWanted()
			return
		}
		log.Printf("No pool found on this network; hosting one")
		if err := a.startHostingWith(true); err != nil {
			// Almost always means another device won the host race a moment ago
			// and its hub is already up. Loop back and join it.
			log.Printf("auto-host: %v; looking for a pool to join instead", err)
			time.Sleep(time.Duration(500+randInt(1500)) * time.Millisecond)
			continue
		}
		a.lendIfWanted()
		// If another open host turns out to exist, mergeLoop (started by
		// startHosting) folds the two pools into one.
		return
	}
	log.Printf("auto-pool: couldn't join or host after several tries; open the Network tab to connect manually")
}

// lendIfWanted starts lending our spare capacity if the person left that on.
func (a *App) lendIfWanted() {
	if a.config().ConnectOnLaunch {
		go func() { _ = a.node.Connect() }()
	}
}

// ensureOwner gives this computer a name for credits if it doesn't have one, so
// joining or hosting never stalls waiting for the person to type it.
func (a *App) ensureOwner() {
	if strings.TrimSpace(a.config().Owner) == "" {
		a.updateConfig(func(c *Config) {
			if strings.TrimSpace(c.DeviceName) != "" {
				c.Owner = c.DeviceName
			} else {
				c.Owner = friendlyComputerName()
			}
		})
	}
}

// mergeLoop keeps an open host from sitting next to another open host on the
// same network. Every so often it looks around; if it finds an open host that
// outranks this one (see outranks), it steps down and joins it, so two people
// who both opened Chimera — or a laptop that woke up later — end up in one pool
// rather than two. Closed hosts (invite code required) are left alone, in both
// directions. It stops when this hub stops.
func (a *App) mergeLoop(h *Hub) {
	delay := 3 * time.Second
	for {
		time.Sleep(delay)
		delay = 20 * time.Second
		a.hubMu.Lock()
		cur := a.hub
		a.hubMu.Unlock()
		if cur != h {
			return // stopped, or replaced
		}
		if !h.AutoJoin() {
			continue // a private pool: never merged
		}
		me := h.Standing()
		n := pickMergeTarget(me, discoverNetworks(1200*time.Millisecond, me.ID))
		if n == nil {
			continue
		}
		log.Printf("Another open pool (%s, %d online) outranks this one; stepping down to join it", n.Name, n.Members)
		a.stopHosting()
		cfg := a.config()
		if err := a.joinNetwork(n.Address, n.Invite, cfg.Owner, cfg.DeviceName); err != nil {
			// Couldn't reach it after stepping down — don't sit orphaned. Take
			// hosting back; the next sweep will try again.
			log.Printf("merge join failed (%v); resuming hosting", err)
			if herr := a.startHostingWith(!me.Chosen); herr != nil {
				log.Printf("resume hosting: %v", herr)
			}
			return // the resumed hub starts its own mergeLoop
		}
		a.lendIfWanted()
		return
	}
}

// pickMergeTarget returns the open host this one should step down for — the
// best-ranked open host that outranks us — or nil to keep hosting. With every
// host able to see every other, exactly one (the top-ranked) keeps hosting and
// all the rest join it directly, with no chains through middle hosts.
func pickMergeTarget(me hostStanding, nets []DiscoveredNet) *DiscoveredNet {
	var best *DiscoveredNet
	for i := range nets {
		n := nets[i]
		if n.SameApp || !n.AutoJoin || n.HubID == "" || n.Invite == "" {
			continue
		}
		them := hostStanding{ID: n.HubID, Chosen: n.Chosen, Members: n.Members, Since: n.Since}
		if !outranks(them, me) {
			continue
		}
		if best == nil || outranks(them, hostStanding{ID: best.HubID, Chosen: best.Chosen, Members: best.Members, Since: best.Since}) {
			best = &nets[i]
		}
	}
	return best
}

// staleHubWatch makes sure "not in the pool" is never where a device rests.
// It notices when this computer is in a network whose hub it can't reach any
// more (the host moved, got a new address, or went away) and, after a minute,
// finds the pool again: the pool address, an open host on the Wi-Fi, or failing
// both, hosting a new pool so the remaining devices aren't stranded. And if the
// device is neither joined nor hosting at all — its launch-time attempt failed,
// or it just left a dead network — it keeps retrying autoPool every half-minute.
func (a *App) staleHubWatch() {
	const tick = 15 * time.Second
	streak := 0
	var lastFix time.Time
	for {
		time.Sleep(tick)
		cfg := a.config()
		if !cfg.Joined() && !cfg.Hosting {
			streak = 0
			if time.Since(lastFix) >= 30*time.Second {
				lastFix = time.Now()
				go a.autoPool() // bounded, and a no-op if one is already running
			}
			continue
		}
		if cfg.Hosting {
			streak = 0
			continue
		}
		_, hubOK, _, _ := a.node.view(a.ollama.Running())
		if hubOK {
			streak = 0
			continue
		}
		streak++
		if streak < 4 || time.Since(lastFix) < 90*time.Second { // ~1 min unreachable
			continue
		}
		lastFix = time.Now()
		streak = 0
		log.Printf("Haven't reached the hub at %s for a minute; looking for the pool again", cfg.HubAddress)
		a.rejoinSomewhere(cfg)
	}
}

// rejoinSomewhere moves a device whose hub has gone quiet to wherever the pool
// is now. It never joins a closed host, and never the address it already has.
func (a *App) rejoinSomewhere(cfg Config) {
	try := func(addr, invite string) bool {
		if addr == "" || addr == cfg.HubAddress {
			return false
		}
		if err := a.joinNetwork(addr, invite, cfg.Owner, cfg.DeviceName); err != nil {
			return false
		}
		log.Printf("Rejoined the pool at %s", addr)
		a.lendIfWanted()
		return true
	}
	if try(cfg.pool(), cfg.Invite) {
		return
	}
	var best *DiscoveredNet
	for _, n := range discoverNetworks(1200*time.Millisecond, "") {
		if !n.AutoJoin || n.Invite == "" || n.Address == cfg.HubAddress {
			continue
		}
		n := n
		if best == nil || outranks(hostStanding{ID: n.HubID, Chosen: n.Chosen, Members: n.Members, Since: n.Since},
			hostStanding{ID: best.HubID, Chosen: best.Chosen, Members: best.Members, Since: best.Since}) {
			best = &n
		}
	}
	if best != nil && try(best.Address, best.Invite) {
		return
	}
	// Nothing to join: the pool is gone. Leave the dead network and let
	// autoPool stand a new one up (another device may do the same — mergeLoop
	// then folds them together).
	log.Printf("No pool reachable; leaving %s and starting over", cfg.HubAddress)
	a.node.Disconnect("now")
	a.updateConfig(func(c *Config) { c.HubAddress, c.Token, c.Invite, c.NetworkName = "", "", "", "" })
	go a.autoPool()
}

func (a *App) Shutdown() {
	a.node.Disconnect("now")
	time.Sleep(300 * time.Millisecond)
	a.hubMu.Lock()
	if a.hub != nil {
		a.hub.Stop()
	}
	a.hubMu.Unlock()
}

func (a *App) Quit() {
	a.quitOnce.Do(func() { close(a.quit) })
}

func (a *App) config() Config {
	a.cfgMu.Lock()
	defer a.cfgMu.Unlock()
	c := a.cfg
	c.Unshared = append([]string(nil), a.cfg.Unshared...)
	return c
}

func (a *App) updateConfig(fn func(*Config)) Config {
	a.cfgMu.Lock()
	fn(&a.cfg)
	c := a.cfg
	err := saveConfig(a.dataDir, a.cfg)
	a.cfgMu.Unlock()
	if err != nil {
		log.Printf("saving settings: %v", err)
	}
	a.notify()
	return c
}

func (a *App) sysInfo() SysInfo {
	a.sysMu.Lock()
	defer a.sysMu.Unlock()
	return a.sys
}

// ---------- change notifications for the interface ----------

func (a *App) notify() {
	a.subMu.Lock()
	defer a.subMu.Unlock()
	for ch := range a.subs {
		select {
		case ch <- struct{}{}:
		default:
		}
	}
}

func (a *App) subscribe() chan struct{} {
	ch := make(chan struct{}, 1)
	a.subMu.Lock()
	a.subs[ch] = struct{}{}
	a.subMu.Unlock()
	return ch
}

func (a *App) unsubscribe(ch chan struct{}) {
	a.subMu.Lock()
	delete(a.subs, ch)
	a.subMu.Unlock()
}

// ---------- networks ----------

func (a *App) joinNetwork(address, invite, owner, deviceName string) error {
	owner = strings.TrimSpace(owner)
	deviceName = strings.TrimSpace(deviceName)
	if owner == "" {
		return errors.New("enter your name (it's how friends see your credits)")
	}
	if deviceName == "" {
		return errors.New("give this computer a name")
	}
	c, err := NewHubClient(address, "")
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	if _, err := c.Ping(ctx); err != nil {
		return errors.New(friendlyNetErr(err, address))
	}
	cfg := a.config()
	resp, err := c.Join(ctx, joinReq{
		Invite: invite, DeviceID: cfg.DeviceID, DeviceName: deviceName, Owner: owner,
		Info: a.sysInfo(), AppVersion: Version, Proto: hubProto,
	})
	if err != nil {
		return errors.New(friendlyNetErr(err, address))
	}
	if a.node != nil {
		a.node.Disconnect("now")
	}
	a.updateConfig(func(c *Config) {
		c.HubAddress = strings.TrimSpace(address)
		c.Invite = invite
		c.Token = resp.Token
		c.NetworkName = resp.NetworkName
		c.Owner = owner
		c.DeviceName = deviceName
		c.SetupDone = true
	})
	log.Printf("Joined network %q at %s", resp.NetworkName, address)
	signal1(a.node.beatNow)
	return nil
}

func (a *App) leaveNetwork() {
	a.node.Disconnect("now")
	cfg := a.config()
	if cfg.Joined() {
		if c, err := NewHubClient(cfg.HubAddress, cfg.Token); err == nil {
			ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
			_ = c.Leave(ctx)
			cancel()
		}
	}
	a.updateConfig(func(c *Config) {
		c.HubAddress, c.Token, c.Invite, c.NetworkName = "", "", "", ""
	})
	a.stopHosting()
	signal1(a.node.beatNow)
}

// startHosting hosts because the person asked (or hosting was on last time).
func (a *App) startHosting() error { return a.startHostingWith(false) }

// startHostingWith hosts the pool; elected says auto-pool picked this computer
// rather than the person, which decides who gives way when two open hosts meet.
func (a *App) startHostingWith(elected bool) error {
	cfg := a.config()
	if strings.TrimSpace(cfg.Owner) == "" {
		return errors.New("enter your name first")
	}
	a.hubMu.Lock()
	var started *Hub
	if a.hub == nil {
		h := NewHub(filepath.Join(a.dataDir, "hub.json"), cfg.HostPort)
		h.EnsureName(cfg.Owner + "'s network")
		h.EnsureOwner(cfg.Owner)
		h.EnsureAutoJoin(cfg.AutoJoin)
		h.SetElected(elected)
		if err := h.Start(); err != nil {
			a.hubErr = err.Error()
			a.hubMu.Unlock()
			a.notify()
			return err
		}
		a.hub = h
		started = h
	}
	h := a.hub
	a.hubErr = ""
	a.hubMu.Unlock()
	if started != nil {
		go a.mergeLoop(started)
	}

	a.updateConfig(func(c *Config) { c.Hosting = true })
	// The host's own Chimera joins its hub like everyone else.
	local := fmt.Sprintf("127.0.0.1:%d", h.Port())
	if cfg.HubAddress != local || !cfg.Joined() {
		if err := a.joinNetwork(local, h.Invite(), cfg.Owner, cfg.DeviceName); err != nil {
			return err
		}
	}
	a.notify()
	return nil
}

func (a *App) stopHosting() {
	a.hubMu.Lock()
	h := a.hub
	a.hub = nil
	a.hubMu.Unlock()
	if h == nil {
		a.updateConfig(func(c *Config) { c.Hosting = false })
		return
	}
	cfg := a.config()
	if cfg.HubAddress == fmt.Sprintf("127.0.0.1:%d", h.Port()) {
		a.node.Disconnect("now")
		a.updateConfig(func(c *Config) { c.HubAddress, c.Token, c.Invite, c.NetworkName = "", "", "", "" })
	}
	h.Stop()
	a.updateConfig(func(c *Config) { c.Hosting = false })
}

func (a *App) hostingView() HostingView {
	a.hubMu.Lock()
	h := a.hub
	errMsg := a.hubErr
	a.hubMu.Unlock()
	cfg := a.config()
	v := HostingView{Enabled: h != nil, Port: cfg.HostPort, Error: errMsg}
	if h != nil {
		v.Invite = h.Invite()
		v.Name = h.Name()
		v.Port = h.Port()
		v.Addresses = localAddresses()
	}
	return v
}

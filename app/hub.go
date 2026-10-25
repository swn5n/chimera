package main

// The hub is the network's switchboard. One person hosts it; everyone's
// Chimera connects to it. It tracks who is online and what they lend, hands
// out work to the device that should finish it soonest, relays the streamed
// answers back, keeps the credit ledger, tracks what the network is waiting
// for, and runs the shared library (see library.go). It never stores prompts
// beyond the life of a step.

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	hubProto = 1
	// TESTING: everyone starts with a million credits so credits never get in
	// the way while we try things out. Set back to 100 before real use.
	starterCredits   = 1_000_000.0
	starterMigration = 1 // bump when starterCredits changes and existing owners should be topped up
	offlineAfter     = 15 * time.Second
	ackAfter         = 20 * time.Second // assigned but never picked up
	stallAfter       = 30 * time.Second // running but silent
	maxAttempts      = 3
	// From this version the computer running a Head reads its options from the
	// request; older ones run the Head on its defaults when the asker leaves them out.
	optionsOnWorkerSince = "0.6.1"
	softFloor            = -50.0
	queueTimeout         = 20 * time.Minute
	recentKeep           = 60
	ledgerKeep           = 2000
	demandWindow         = time.Hour
	libraryBigWait       = 10 * time.Minute // library jobs wait this long for the biggest model
	discoveryPort        = 7479             // UDP: devices find hosts on the same network here
)

type hubDevice struct {
	ID     string    `json:"id"`
	Token  string    `json:"token"`
	Owner  string    `json:"owner"`
	Name   string    `json:"name"`
	Joined time.Time `json:"joined"`
	Info   SysInfo   `json:"info"`
	// Local is the hosting computer itself (it joined over loopback). Only it
	// reviews the library and only it may test-run library scripts.
	Local bool `json:"local"`

	lastSeen    time.Time
	online      bool
	lending     bool
	draining    bool
	slots       int
	ollamaOK    bool
	ollamaVer   string
	models      []ModelInfo
	appVer      string
	profile     DeviceProfile
	runTests    bool
	lendPlugins bool // its owner lets the network run its plugins
	lastWork    time.Time
}

func (d *hubDevice) hasTool(id string) bool {
	for _, t := range d.profile.Tools {
		if t.ID == id && t.Have {
			return true
		}
	}
	return false
}

// plugin returns what the device says about one of its plugins.
func (d *hubDevice) plugin(id string) (PluginInfo, bool) {
	for _, p := range d.profile.Plugins {
		if p.ID == id {
			return p, p.Have
		}
	}
	return PluginInfo{}, false
}

type LedgerTx struct {
	At     time.Time `json:"at"`
	From   string    `json:"from"`
	To     string    `json:"to"`
	Amount float64   `json:"amount"`
	Note   string    `json:"note"`
	StepID string    `json:"step_id,omitempty"`
}

type StepSummary struct {
	ID              string    `json:"id"`
	At              time.Time `json:"at"`
	Requester       string    `json:"requester"`
	RequesterDevice string    `json:"requester_device"`
	RequesterID     string    `json:"requester_id"`
	Worker          string    `json:"worker"`
	WorkerDevice    string    `json:"worker_device"`
	WorkerID        string    `json:"worker_id"`
	Model           string    `json:"model"`
	Purpose         string    `json:"purpose,omitempty"`
	Tokens          int       `json:"tokens"`
	PromptTokens    int       `json:"prompt_tokens"`
	TokPerSec       float64   `json:"tok_s"`
	WaitSec         float64   `json:"wait_s"`
	Credits         float64   `json:"credits"`
	Free            bool      `json:"free"`
	Status          string    `json:"status"`
	Error           string    `json:"error,omitempty"`
}

type hubState struct {
	HubID    string                `json:"hub_id"`
	Name     string                `json:"name"`
	Invite   string                `json:"invite"`
	Owner    string                `json:"owner"` // who hosts; reviews the library
	Created  time.Time             `json:"created"`
	Devices  map[string]*hubDevice `json:"devices"`
	Balances map[string]float64    `json:"balances"`
	Owners   map[string]string     `json:"owners"` // owner key -> display name
	Ledger   []LedgerTx            `json:"ledger"`
	Recent   []StepSummary         `json:"recent"`
	// How long a lending device must sit idle before it helps check the library.
	VerifyIdleMin int `json:"verify_idle_min"`
	// Which starter-credit grant has been applied (for one-time top-ups).
	StarterMigration int `json:"starter_migration"`
	// Let devices on the same network join automatically (no code/IP typed).
	AutoJoin bool `json:"auto_join"`
}

type hubEvent struct {
	Type       string     `json:"type"` // queued, assigned, delta, requeued, done, error, cancelled
	Device     string     `json:"device,omitempty"`
	DeviceName string     `json:"device_name,omitempty"`
	Owner      string     `json:"owner,omitempty"`
	Model      string     `json:"model,omitempty"`
	Content    string     `json:"content,omitempty"`
	Thinking   string     `json:"thinking,omitempty"`
	Reason     string     `json:"reason,omitempty"`
	Error      string     `json:"error,omitempty"`
	Stats      *ChatStats `json:"stats,omitempty"`
	Credits    float64    `json:"credits,omitempty"`
	Free       bool       `json:"free,omitempty"`
	Position   int        `json:"position,omitempty"`
	Fraction   float64    `json:"fraction,omitempty"` // status: how far a plugin step is, 0..1
	File       *StepFile  `json:"file,omitempty"`     // file: something a plugin step made
}

type hubStep struct {
	ID             string
	RequesterID    string
	RequesterOwner string
	RequesterName  string
	Model          string // requested; "" means pick automatically
	RunModel       string // what actually ran
	Target         string // device id or ""
	Private        bool
	Messages       []ChatMessage
	Options        map[string]any
	Prefer         string   // "", "largest", "fastest"
	NeedCaps       []string // e.g. vision
	NeedCtx        int      // tokens of context the step needs
	Format         json.RawMessage
	Kind           string // chat (default), run_python, run_blender, run_plugin
	Script         string
	Plugin         string          // run_plugin: which plugin
	Input          json.RawMessage // run_plugin: its input
	Files          []StepFile      // run_plugin: what it made
	StatusMsg      string          // run_plugin: what it's doing now
	Fraction       float64
	Note           string // run_plugin: the worker's line for the asker (the options it read)
	optionsLeft    bool   // run_plugin: the input has no options, for the worker to read (0.6.1 and newer)
	Purpose        string // shown to the worker
	Internal       bool   // made by the hub itself (library jobs); free
	HostOnly       bool   // only the hosting computer may run it (library review)
	TaskWork       bool   // part of a Hydra long task (for owner auto-help)
	onDone         func(h *Hub, st *hubStep)

	Status       string // queued, assigned, running, done, failed, cancelled
	Assigned     string
	Attempts     int
	Exclude      map[string]bool
	Created      time.Time
	AssignedAt   time.Time
	LastProgress time.Time
	Finished     time.Time
	unrunnable   time.Time
	Text         strings.Builder
	Thinking     strings.Builder
	Stats        ChatStats
	Credits      float64
	Free         bool
	Err          string
	CancelReq    bool

	subs map[chan hubEvent]struct{}
}

type waiter struct {
	deviceID string
	ch       chan *hubStep
}

type demandEvent struct {
	At    time.Time
	Model string // "" = any model
	Caps  []string
	Unmet bool
	Wait  float64 // seconds from submit to assignment; -1 if not assigned yet
}

type Hub struct {
	path string
	port int
	srv  *http.Server

	mu      sync.Mutex
	elected bool // hosting because auto-pool picked us, not because the person chose it
	st      hubState
	tokens  map[string]string // token -> device id
	steps   map[string]*hubStep
	queue   []*hubStep
	waiters map[string]*waiter
	demand  []demandEvent
	lib     *library
	dirty   bool
	stop    chan struct{}
	running bool

	disco net.PacketConn // UDP discovery listener
}

func NewHub(path string, port int) *Hub {
	h := &Hub{
		path:    path,
		port:    port,
		tokens:  map[string]string{},
		steps:   map[string]*hubStep{},
		waiters: map[string]*waiter{},
	}
	if b, err := os.ReadFile(path); err == nil {
		_ = json.Unmarshal(b, &h.st)
	}
	if h.st.HubID == "" {
		h.st.HubID = randomID(6)
		h.st.Invite = randomInvite()
		h.st.Name = "Chimera network"
		h.st.Created = time.Now()
		h.dirty = true
	}
	if h.st.Devices == nil {
		h.st.Devices = map[string]*hubDevice{}
	}
	if h.st.Balances == nil {
		h.st.Balances = map[string]float64{}
	}
	if h.st.Owners == nil {
		h.st.Owners = map[string]string{}
	}
	if h.st.VerifyIdleMin == 0 {
		h.st.VerifyIdleMin = 10
	}
	// One-time top-up when the starter amount changes, so people who already
	// joined get the new balance too (used for the 1,000,000 testing grant).
	if h.st.StarterMigration < starterMigration {
		for key := range h.st.Owners {
			if h.st.Balances[key] < starterCredits {
				h.st.Balances[key] = starterCredits
			}
		}
		h.st.StarterMigration = starterMigration
		h.dirty = true
	}
	for id, d := range h.st.Devices {
		if d.Token != "" {
			h.tokens[d.Token] = id
		}
		d.slots = 1
	}
	h.lib = loadLibrary(filepath.Join(filepath.Dir(path), "library.json"))
	return h
}

func (h *Hub) Invite() string { h.mu.Lock(); defer h.mu.Unlock(); return h.st.Invite }
func (h *Hub) HubID() string  { h.mu.Lock(); defer h.mu.Unlock(); return h.st.HubID }
func (h *Hub) AutoJoin() bool { h.mu.Lock(); defer h.mu.Unlock(); return h.st.AutoJoin }

// SetElected records that this computer chose to host on its own (auto-pool),
// rather than the person starting it or it being restored from settings. When
// two open hosts meet, an elected one gives way to a chosen one.
func (h *Hub) SetElected(on bool) { h.mu.Lock(); h.elected = on; h.mu.Unlock() }

// Standing is what a host advertises so two open hosts can agree which one
// keeps hosting: chosen-by-a-person first, then more devices online, then the
// one that has been up longer, then the smaller id. Read under h.mu.
func (h *Hub) standingLocked() hostStanding {
	n := 0
	now := time.Now()
	for _, d := range h.st.Devices {
		if now.Sub(d.lastSeen) < offlineAfter {
			n++
		}
	}
	return hostStanding{ID: h.st.HubID, Chosen: !h.elected, Members: n, Since: h.st.Created.Unix()}
}

func (h *Hub) Standing() hostStanding { h.mu.Lock(); defer h.mu.Unlock(); return h.standingLocked() }
func (h *Hub) Name() string           { h.mu.Lock(); defer h.mu.Unlock(); return h.st.Name }
func (h *Hub) Port() int              { return h.port }

func (h *Hub) EnsureName(name string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.st.Name == "" || h.st.Name == "Chimera network" {
		h.st.Name = name
		h.dirty = true
	}
}

// EnsureOwner records who hosts the network (they review the library).
func (h *Hub) EnsureOwner(owner string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if strings.TrimSpace(owner) != "" && h.st.Owner == "" {
		h.st.Owner = strings.TrimSpace(owner)
		h.dirty = true
	}
}

func (h *Hub) SetName(name string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if name = strings.TrimSpace(name); name != "" {
		h.st.Name = name
		h.dirty = true
	}
}

// NewInvite replaces the invite code. Devices already in keep working.
func (h *Hub) NewInvite() string {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.st.Invite = randomInvite()
	h.dirty = true
	h.saveLocked()
	return h.st.Invite
}

// SetAutoJoin controls whether devices on the same network can join without a code.
func (h *Hub) SetAutoJoin(on bool) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.st.AutoJoin != on {
		h.st.AutoJoin = on
		h.dirty = true
		h.saveLocked()
	}
}

// EnsureAutoJoin sets the default for a freshly created hub.
func (h *Hub) EnsureAutoJoin(on bool) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.st.AutoJoin = on
}

func (h *Hub) Start() error {
	ln, err := net.Listen("tcp", fmt.Sprintf(":%d", h.port))
	if err != nil {
		return fmt.Errorf("port %d is already in use on this computer (is another hub running?)", h.port)
	}
	h.stop = make(chan struct{})
	h.srv = &http.Server{Handler: h.routes(), ReadHeaderTimeout: 10 * time.Second}
	h.running = true
	go func() {
		if err := h.srv.Serve(ln); err != nil && err != http.ErrServerClosed {
			log.Printf("hub server: %v", err)
		}
	}()
	go h.monitor()
	h.startDiscovery()
	h.mu.Lock()
	h.saveLocked()
	h.mu.Unlock()
	log.Printf("Hub %q listening on port %d", h.Name(), h.port)
	return nil
}

func (h *Hub) Stop() {
	if !h.running {
		return
	}
	h.running = false
	close(h.stop)
	h.stopDiscovery()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = h.srv.Shutdown(ctx)
	h.mu.Lock()
	h.saveLocked()
	h.lib.save()
	h.mu.Unlock()
	log.Printf("Hub stopped")
}

func (h *Hub) saveLocked() {
	b, err := json.MarshalIndent(h.st, "", "  ")
	if err != nil {
		return
	}
	if err := writeFileAtomic(h.path, b); err != nil {
		log.Printf("hub: saving state: %v", err)
		return
	}
	h.dirty = false
}

func (h *Hub) routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/ping", h.handlePing)
	mux.HandleFunc("POST /v1/join", h.handleJoin)
	mux.HandleFunc("POST /v1/leave", h.auth(h.handleLeave))
	mux.HandleFunc("POST /v1/heartbeat", h.auth(h.handleHeartbeat))
	mux.HandleFunc("GET /v1/network", h.auth(h.handleNetwork))
	mux.HandleFunc("GET /v1/work", h.auth(h.handleWork))
	mux.HandleFunc("POST /v1/steps", h.auth(h.handleSubmit))
	mux.HandleFunc("GET /v1/steps/{id}/events", h.auth(h.handleEvents))
	mux.HandleFunc("POST /v1/steps/{id}/cancel", h.auth(h.handleCancel))
	mux.HandleFunc("POST /v1/steps/{id}/progress", h.auth(h.handleProgress))
	mux.HandleFunc("POST /v1/steps/{id}/complete", h.auth(h.handleComplete))
	mux.HandleFunc("POST /v1/steps/{id}/fail", h.auth(h.handleFail))
	mux.HandleFunc("POST /v1/admin/settings", h.auth(h.handleAdminSettings))
	mux.HandleFunc("GET /v1/plugins", h.auth(h.handlePlugins))
	h.libraryRoutes(mux)
	return mux
}

func (h *Hub) auth(fn func(http.ResponseWriter, *http.Request, *hubDevice)) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		tok := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
		h.mu.Lock()
		var d *hubDevice
		if id, ok := h.tokens[tok]; ok && tok != "" {
			d = h.st.Devices[id]
		}
		h.mu.Unlock()
		if d == nil {
			writeErr(w, 401, "This device isn't a member of this network anymore. Join again with the invite code.")
			return
		}
		fn(w, r, d)
	}
}

// isAdminLocked is true for the hosting computer itself. Names aren't
// authenticated (anyone with the invite could join as the host's name), so
// admin rights follow the machine, not the name.
func (h *Hub) isAdminLocked(d *hubDevice) bool { return d != nil && d.Local }

func isLoopback(remoteAddr string) bool {
	host, _, err := net.SplitHostPort(remoteAddr)
	if err != nil {
		host = remoteAddr
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

// handleAdminSettings lets the host change network-wide settings.
func (h *Hub) handleAdminSettings(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	var req struct {
		VerifyIdleMin *int `json:"verify_idle_min"`
	}
	if err := readJSON(r, &req, 4096); err != nil {
		writeErr(w, 400, "bad request")
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	if !h.isAdminLocked(d) {
		writeErr(w, 403, "Only the network's host can change this.")
		return
	}
	if req.VerifyIdleMin != nil {
		h.st.VerifyIdleMin = clampInt(*req.VerifyIdleMin, 1, 24*60)
		h.dirty = true
	}
	writeJSON(w, 200, map[string]int{"verify_idle_min": h.st.VerifyIdleMin})
}

// ---------- membership ----------

func (h *Hub) handlePing(w http.ResponseWriter, r *http.Request) {
	h.mu.Lock()
	name := h.st.Name
	h.mu.Unlock()
	writeJSON(w, 200, map[string]any{"app": "chimera-hub", "proto": hubProto, "version": Version, "name": name})
}

type joinReq struct {
	Invite     string  `json:"invite"`
	DeviceID   string  `json:"device_id"`
	DeviceName string  `json:"device_name"`
	Owner      string  `json:"owner"`
	Info       SysInfo `json:"info"`
	AppVersion string  `json:"app_version"`
	Proto      int     `json:"proto"`
}

type joinResp struct {
	Token       string `json:"token"`
	HubID       string `json:"hub_id"`
	NetworkName string `json:"network_name"`
}

func (h *Hub) handleJoin(w http.ResponseWriter, r *http.Request) {
	var req joinReq
	if err := readJSON(r, &req, 1<<20); err != nil {
		writeErr(w, 400, "bad request")
		return
	}
	req.Owner = strings.TrimSpace(req.Owner)
	req.DeviceName = strings.TrimSpace(req.DeviceName)
	if req.Proto != 0 && req.Proto != hubProto {
		writeErr(w, 409, "This hub runs a different Chimera version. Update both to the same version.")
		return
	}
	if req.Owner == "" || req.DeviceName == "" || req.DeviceID == "" {
		writeErr(w, 400, "Your name and a device name are required.")
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	// An open pool (auto-join on) lets anyone join with no code; otherwise the
	// invite code must match.
	if !h.st.AutoJoin && normalizeInvite(req.Invite) != normalizeInvite(h.st.Invite) {
		writeErr(w, 403, "That invite code doesn't match this network.")
		return
	}
	d := h.st.Devices[req.DeviceID]
	if d == nil {
		d = &hubDevice{ID: req.DeviceID, Joined: time.Now(), slots: 1}
		h.st.Devices[req.DeviceID] = d
	} else if d.Token != "" {
		delete(h.tokens, d.Token)
	}
	d.Token = randomID(16)
	d.Name = req.DeviceName
	d.Owner = req.Owner
	d.Local = isLoopback(r.RemoteAddr)
	d.Info = req.Info
	d.appVer = req.AppVersion
	d.lastSeen = time.Now()
	h.tokens[d.Token] = d.ID
	key := ownerKey(req.Owner)
	if _, ok := h.st.Owners[key]; !ok {
		h.st.Owners[key] = req.Owner
		h.st.Balances[key] += starterCredits
		h.addTxLocked(LedgerTx{At: time.Now(), From: "network", To: req.Owner, Amount: starterCredits, Note: "starter credits"})
	}
	h.saveLocked()
	log.Printf("hub: %s joined (owner %s)", d.Name, d.Owner)
	writeJSON(w, 200, joinResp{Token: d.Token, HubID: h.st.HubID, NetworkName: h.st.Name})
}

func (h *Hub) handleLeave(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	h.mu.Lock()
	defer h.mu.Unlock()
	for _, st := range h.steps {
		if st.Assigned == d.ID && (st.Status == "assigned" || st.Status == "running") {
			h.requeueLocked(st, d.Name+" left the network", true)
		}
	}
	delete(h.tokens, d.Token)
	delete(h.st.Devices, d.ID)
	delete(h.waiters, d.ID)
	h.saveLocked()
	writeJSON(w, 200, map[string]bool{"ok": true})
}

type heartbeatReq struct {
	Name          string        `json:"name"`
	Lending       bool          `json:"lending"`
	Draining      bool          `json:"draining"`
	Slots         int           `json:"slots"`
	OllamaOK      bool          `json:"ollama_ok"`
	OllamaVersion string        `json:"ollama_version"`
	Models        []ModelInfo   `json:"models"`
	Info          *SysInfo      `json:"info,omitempty"`
	Profile       DeviceProfile `json:"profile"`
	RunTests      bool          `json:"run_tests"`
	LendPlugins   bool          `json:"lend_plugins"`
	AppVersion    string        `json:"app_version"`
}

func (h *Hub) handleHeartbeat(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	var hb heartbeatReq
	if err := readJSON(r, &hb, 4<<20); err != nil {
		writeErr(w, 400, "bad heartbeat")
		return
	}
	h.mu.Lock()
	if !d.online {
		log.Printf("hub: %s is online", d.Name)
	}
	d.lastSeen = time.Now()
	d.online = true
	if hb.Lending && !d.lending {
		d.lastWork = time.Now()
	}
	d.lending = hb.Lending
	d.draining = hb.Draining
	d.slots = clampInt(hb.Slots, 1, 8)
	d.ollamaOK = hb.OllamaOK
	d.ollamaVer = hb.OllamaVersion
	d.models = hb.Models
	d.appVer = hb.AppVersion
	if len(hb.Profile.Plugins) > maxPluginsPerDevice {
		hb.Profile.Plugins = hb.Profile.Plugins[:maxPluginsPerDevice]
	}
	d.profile = hb.Profile
	d.runTests = hb.RunTests
	d.lendPlugins = hb.LendPlugins
	h.syncPluginEntriesLocked(d)
	if hb.Info != nil && hb.Info.OS != "" {
		d.Info = *hb.Info
	}
	if n := strings.TrimSpace(hb.Name); n != "" && n != d.Name {
		d.Name = n
		h.dirty = true
	}
	if !d.lending || d.draining {
		delete(h.waiters, d.ID)
	}
	snap := h.snapshotLocked(d)
	h.mu.Unlock()
	writeJSON(w, 200, snap)
}

func (h *Hub) handleNetwork(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	h.mu.Lock()
	snap := h.snapshotLocked(d)
	h.mu.Unlock()
	writeJSON(w, 200, snap)
}

// ---------- snapshot ----------

type NetInfo struct {
	HubID         string `json:"hub_id"`
	Name          string `json:"name"`
	Owner         string `json:"owner"`
	Version       string `json:"version"`
	VerifyIdleMin int    `json:"verify_idle_min"`
}

type DeviceView struct {
	ID            string        `json:"id"`
	Name          string        `json:"name"`
	Owner         string        `json:"owner"`
	Info          SysInfo       `json:"info"`
	Online        bool          `json:"online"`
	Lending       bool          `json:"lending"`
	Draining      bool          `json:"draining"`
	OllamaOK      bool          `json:"ollama_ok"`
	OllamaVersion string        `json:"ollama_version"`
	Slots         int           `json:"slots"`
	Busy          int           `json:"busy"`
	Models        []ModelInfo   `json:"models"`
	Profile       DeviceProfile `json:"profile"`
	RunTests      bool          `json:"run_tests"`
	LastSeenSec   int           `json:"last_seen_sec"`
	AppVersion    string        `json:"app_version"`
}

type DemandView struct {
	Model    string   `json:"model"` // "" = any model
	Caps     []string `json:"caps,omitempty"`
	Requests int      `json:"requests"`
	Unmet    int      `json:"unmet"`
	AvgWait  float64  `json:"avg_wait_s"`
	MaxWait  float64  `json:"max_wait_s"`
	Waiting  int      `json:"waiting"` // queued right now
}

type NetSnapshot struct {
	Network   NetInfo            `json:"network"`
	Devices   []DeviceView       `json:"devices"`
	Balances  map[string]float64 `json:"balances"`
	Recent    []StepSummary      `json:"recent"`
	Queue     int                `json:"queue"`
	Demand    []DemandView       `json:"demand"`
	Library   LibraryStats       `json:"library"`
	Admin     bool               `json:"admin"`
	OwnerBusy bool               `json:"owner_busy"` // the viewer's owner has a long task running
}

// ownerTaskActiveLocked reports whether this owner has Hydra task work queued
// or running right now (used so their other devices can auto-connect to help).
func (h *Hub) ownerTaskActiveLocked(owner string) bool {
	if owner == "" {
		return false
	}
	for _, st := range h.steps {
		if st.TaskWork && sameOwner(st.RequesterOwner, owner) && (st.Status == "queued" || st.Status == "assigned" || st.Status == "running") {
			return true
		}
	}
	return false
}

func (h *Hub) snapshotLocked(viewer *hubDevice) NetSnapshot {
	now := time.Now()
	snap := NetSnapshot{
		Network:  NetInfo{HubID: h.st.HubID, Name: h.st.Name, Owner: h.st.Owner, Version: Version, VerifyIdleMin: h.st.VerifyIdleMin},
		Balances: map[string]float64{},
		Admin:    h.isAdminLocked(viewer),
	}
	if viewer != nil {
		snap.OwnerBusy = h.ownerTaskActiveLocked(viewer.Owner)
	}
	for _, d := range h.st.Devices {
		online := now.Sub(d.lastSeen) < offlineAfter
		v := DeviceView{
			ID: d.ID, Name: d.Name, Owner: d.Owner, Info: d.Info,
			Online: online, Lending: online && d.lending, Draining: online && d.draining,
			OllamaOK: online && d.ollamaOK, OllamaVersion: d.ollamaVer,
			Slots: d.slots, Busy: h.activeLocked(d.ID), AppVersion: d.appVer,
			LastSeenSec: int(now.Sub(d.lastSeen).Seconds()), RunTests: d.runTests,
		}
		if online {
			v.Models = d.models
			v.Profile = d.profile
		}
		if d.lastSeen.IsZero() {
			v.LastSeenSec = -1
		}
		snap.Devices = append(snap.Devices, v)
	}
	sort.Slice(snap.Devices, func(i, j int) bool {
		a, b := snap.Devices[i], snap.Devices[j]
		if a.Online != b.Online {
			return a.Online
		}
		return strings.ToLower(a.Name) < strings.ToLower(b.Name)
	})
	for k, v := range h.st.Balances {
		name := h.st.Owners[k]
		if name == "" {
			name = k
		}
		snap.Balances[name] = round2(v)
	}
	n := len(h.st.Recent)
	for i := n - 1; i >= 0 && len(snap.Recent) < 30; i-- {
		snap.Recent = append(snap.Recent, h.st.Recent[i])
	}
	for _, st := range h.queue {
		if st.Status == "queued" && !st.Internal {
			snap.Queue++
		}
	}
	snap.Demand = h.demandLocked()
	snap.Library = h.lib.stats()
	return snap
}

// demandLocked summarises the last hour: what people asked for, what found
// no device, and how long things waited.
func (h *Hub) demandLocked() []DemandView {
	cut := time.Now().Add(-demandWindow)
	agg := map[string]*DemandView{}
	waits := map[string]int{}
	for _, e := range h.demand {
		if e.At.Before(cut) {
			continue
		}
		key := normModel(e.Model) + "|" + strings.Join(e.Caps, ",")
		v := agg[key]
		if v == nil {
			v = &DemandView{Model: e.Model, Caps: e.Caps}
			agg[key] = v
		}
		switch {
		case e.Unmet:
			v.Unmet++
			v.Requests++
		case e.Wait >= 0:
			v.AvgWait += e.Wait
			waits[key]++
			if e.Wait > v.MaxWait {
				v.MaxWait = e.Wait
			}
		default:
			v.Requests++
		}
	}
	for _, st := range h.queue {
		if st.Status == "queued" && !st.Internal {
			key := normModel(st.Model) + "|" + strings.Join(st.NeedCaps, ",")
			if v := agg[key]; v != nil {
				v.Waiting++
			}
		}
	}
	var out []DemandView
	for key, v := range agg {
		if waits[key] > 0 {
			v.AvgWait = round1(v.AvgWait / float64(waits[key]))
		}
		v.MaxWait = round1(v.MaxWait)
		out = append(out, *v)
	}
	sort.Slice(out, func(i, j int) bool {
		si := float64(out[i].Unmet*3+out[i].Waiting*2) + out[i].AvgWait/10
		sj := float64(out[j].Unmet*3+out[j].Waiting*2) + out[j].AvgWait/10
		if si != sj {
			return si > sj
		}
		return out[i].Requests > out[j].Requests
	})
	if len(out) > 12 {
		out = out[:12]
	}
	if out == nil {
		out = []DemandView{}
	}
	return out
}

func (h *Hub) noteDemandLocked(e demandEvent) {
	e.At = time.Now()
	h.demand = append(h.demand, e)
	if len(h.demand) > 2000 {
		h.demand = h.demand[len(h.demand)-2000:]
	}
}

// ---------- matching ----------

func (h *Hub) activeLocked(deviceID string) int {
	n := 0
	for _, st := range h.steps {
		if st.Assigned == deviceID && (st.Status == "assigned" || st.Status == "running") {
			n++
		}
	}
	return n
}

func (h *Hub) onlineLocked(d *hubDevice) bool {
	return time.Since(d.lastSeen) < offlineAfter
}

// eta guesses how many seconds a model would take to answer on its device.
func eta(m ModelInfo) float64 {
	speed := m.Speed()
	if speed <= 0 {
		speed = 15
	}
	load := 0.0
	if !m.Loaded {
		load = m.SizeGB() / 2.5
	}
	return load + 500/speed
}

func modelOK(m ModelInfo, st *hubStep) bool {
	if m.Fits == "too_big" {
		return false
	}
	for _, c := range st.NeedCaps {
		if !m.HasCap(c) {
			return false
		}
	}
	if st.NeedCtx > 0 && m.CtxMax > 0 && m.CtxMax < st.NeedCtx {
		return false
	}
	return true
}

// fits reports whether device d could run step st, with which model, and how
// good a choice it is (higher is better).
func (h *Hub) fits(d *hubDevice, st *hubStep) (model string, score float64, ok bool) {
	if st.Exclude[d.ID] {
		return "", 0, false
	}
	if st.Target != "" && st.Target != d.ID {
		return "", 0, false
	}
	if st.Private && !sameOwner(d.Owner, st.RequesterOwner) {
		return "", 0, false
	}
	if st.HostOnly && !h.isAdminLocked(d) {
		return "", 0, false
	}
	switch st.Kind {
	case "run_plugin":
		// Only devices with the plugin installed, and whose owner lends their
		// plugins (or that belong to the person asking).
		pi, ok := d.plugin(st.Plugin)
		if !ok || !d.hasTool("plugin:"+st.Plugin) {
			return "", 0, false
		}
		own := sameOwner(d.Owner, st.RequesterOwner)
		if !d.lendPlugins && !own {
			return "", 0, false
		}
		for _, c := range st.NeedCaps {
			if !contains(pi.Caps, c) {
				return "", 0, false
			}
		}
		score := 1.0
		if own {
			score += 0.5 // free, and the person's own computer
		}
		if h.activeLocked(d.ID) == 0 {
			score += 0.25
		}
		return "", score, true
	case "run_python", "run_blender":
		// Only the hosting computer, when its owner opted in, ever runs library scripts.
		if !d.runTests || !h.isAdminLocked(d) {
			return "", 0, false
		}
		need := "python"
		if st.Kind == "run_blender" {
			need = "blender"
		}
		if !d.hasTool(need) {
			return "", 0, false
		}
		return "", 1, true
	}
	if st.Model != "" {
		for _, m := range d.models {
			if normModel(m.Name) == normModel(st.Model) {
				if st.NeedCtx > 0 && m.CtxMax > 0 && m.CtxMax < st.NeedCtx {
					return "", 0, false
				}
				return m.Name, 10000 - eta(m), true
			}
		}
		return "", 0, false
	}
	best, bestParams := -1e18, 0.0
	for _, m := range d.models {
		if !m.CanChat() || !modelOK(m, st) {
			continue
		}
		var s float64
		loaded := 0.0
		if m.Loaded {
			loaded = 1
		}
		switch st.Prefer {
		case "largest":
			s = m.ParamsB*100 + loaded*50 - eta(m)
		case "fastest":
			s = 10000 - eta(m)
		default:
			size := m.ParamsB
			if m.Fits == "tight" {
				size *= 0.6 // works, but close to the memory limit: prefer roomier choices
			}
			s = size*10 + loaded*30 - eta(m)
		}
		if s > best {
			best, model, bestParams = s, m.Name, m.ParamsB
		}
	}
	// Library work isn't urgent: give the network's biggest model a while to
	// come free instead of settling for a much smaller one.
	if model != "" && st.Internal && st.Prefer == "largest" && time.Since(st.Created) < libraryBigWait {
		if top := h.largestLocked(st); bestParams < top*0.5 {
			return "", 0, false
		}
	}
	return model, best, model != ""
}

// largestLocked is the biggest model any lending device could run st with.
func (h *Hub) largestLocked(st *hubStep) float64 {
	top := 0.0
	for _, d := range h.st.Devices {
		if !h.onlineLocked(d) || !d.lending || d.draining || !d.ollamaOK || st.Exclude[d.ID] {
			continue
		}
		if st.HostOnly && !h.isAdminLocked(d) {
			continue
		}
		for _, m := range d.models {
			if m.CanChat() && modelOK(m, st) && m.ParamsB > top {
				top = m.ParamsB
			}
		}
	}
	return top
}

func (h *Hub) readyLocked(d *hubDevice) bool {
	return h.onlineLocked(d) && d.lending && !d.draining && d.ollamaOK && h.activeLocked(d.ID) < d.slots
}

func (h *Hub) possibleLocked(st *hubStep) bool {
	for _, d := range h.st.Devices {
		if !h.onlineLocked(d) || !d.lending || d.draining || !d.ollamaOK {
			continue
		}
		if _, _, ok := h.fits(d, st); ok {
			return true
		}
	}
	return false
}

func (h *Hub) balanceLocked(owner string) float64 { return h.st.Balances[ownerKey(owner)] }

func (h *Hub) sortQueueLocked() {
	sort.SliceStable(h.queue, func(i, j int) bool {
		a, b := h.queue[i], h.queue[j]
		if a.Internal != b.Internal {
			return !a.Internal // people first, library jobs after
		}
		la := h.balanceLocked(a.RequesterOwner) < softFloor
		lb := h.balanceLocked(b.RequesterOwner) < softFloor
		if la != lb {
			return !la
		}
		return a.Created.Before(b.Created)
	})
}

func (h *Hub) removeFromQueueLocked(st *hubStep) {
	out := h.queue[:0]
	for _, q := range h.queue {
		if q != st {
			out = append(out, q)
		}
	}
	h.queue = out
}

func (h *Hub) assignLocked(st *hubStep, d *hubDevice, model string) {
	h.removeFromQueueLocked(st)
	st.Status = "assigned"
	st.Assigned = d.ID
	st.RunModel = model
	if st.Kind == "run_plugin" {
		model = st.Plugin + " plugin"
		if pi, ok := d.plugin(st.Plugin); ok && pi.Name != "" {
			model = pi.Name
		}
		st.RunModel = model
		if st.optionsLeft && versionLess(d.appVer, optionsOnWorkerSince) { // it won't read them: say so
			st.Note = d.Name + " runs an older Chimera that doesn't read options from the request, so the Head uses its defaults. Update it to " + Version + "."
		}
	}
	st.Attempts++
	st.AssignedAt = time.Now()
	st.LastProgress = time.Now()
	d.lastWork = time.Now()
	if !st.Internal && st.Attempts == 1 && st.Kind != "run_plugin" {
		h.noteDemandLocked(demandEvent{Model: st.Model, Caps: st.NeedCaps, Wait: time.Since(st.Created).Seconds()})
	}
	st.emit(hubEvent{Type: "assigned", Device: d.ID, DeviceName: d.Name, Owner: d.Owner, Model: model})
	if st.Note != "" {
		st.emit(hubEvent{Type: "note", Reason: st.Note})
	}
}

// dispatchLocked hands queued steps to the waiting device that suits them best.
func (h *Hub) dispatchLocked() {
	if len(h.queue) == 0 || len(h.waiters) == 0 {
		return
	}
	h.sortQueueLocked()
	for _, st := range append([]*hubStep(nil), h.queue...) {
		if st.Status != "queued" || len(h.waiters) == 0 {
			continue
		}
		var bestW *waiter
		var bestD *hubDevice
		bestModel, bestScore := "", -1e18
		for id, w := range h.waiters {
			d := h.st.Devices[id]
			if d == nil || !h.readyLocked(d) {
				continue
			}
			model, score, ok := h.fits(d, st)
			if !ok {
				continue
			}
			if score > bestScore {
				bestW, bestD, bestModel, bestScore = w, d, model, score
			}
		}
		if bestW == nil {
			continue
		}
		delete(h.waiters, bestD.ID)
		h.assignLocked(st, bestD, bestModel)
		bestW.ch <- st
	}
}

// ---------- worker endpoints ----------

type Assignment struct {
	StepID          string          `json:"step_id"`
	Kind            string          `json:"kind,omitempty"`
	Model           string          `json:"model"`
	Messages        []ChatMessage   `json:"messages"`
	Options         map[string]any  `json:"options,omitempty"`
	Format          json.RawMessage `json:"format,omitempty"`
	NumCtx          int             `json:"num_ctx,omitempty"`
	Script          string          `json:"script,omitempty"`
	Plugin          string          `json:"plugin,omitempty"`
	Input           json.RawMessage `json:"input,omitempty"`
	Purpose         string          `json:"purpose,omitempty"`
	Requester       string          `json:"requester"`
	RequesterDevice string          `json:"requester_device"`
}

// ctxBucket rounds a context need up to a few fixed sizes, so Ollama doesn't
// reload the model for every slightly different prompt.
func ctxBucket(need, max int) int {
	b := 8192
	switch {
	case need > 65536:
		b = 131072
	case need > 30000:
		b = 65536
	case need > 7000:
		b = 32768
	}
	if max > 0 && b > max {
		b = max
	}
	return b
}

func (h *Hub) assignmentFor(st *hubStep, d *hubDevice) Assignment {
	a := Assignment{StepID: st.ID, Kind: st.Kind, Model: st.RunModel, Messages: st.Messages, Options: st.Options,
		Format: st.Format, Script: st.Script, Plugin: st.Plugin, Input: st.Input, Purpose: st.Purpose,
		Requester: st.RequesterOwner, RequesterDevice: st.RequesterName}
	if st.Internal {
		a.Requester, a.RequesterDevice = "the network", "library"
	}
	if st.Kind == "" || st.Kind == "chat" {
		max := 0
		for _, m := range d.models {
			if normModel(m.Name) == normModel(st.RunModel) {
				max = m.CtxMax
			}
		}
		a.NumCtx = ctxBucket(st.NeedCtx, max)
	}
	return a
}

func (h *Hub) handleWork(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	wait := clampInt(atoiDefault(r.URL.Query().Get("wait"), 25), 0, 30)
	h.mu.Lock()
	d.lastSeen = time.Now()
	d.online = true
	d.lending = true
	if !h.readyLocked(d) {
		h.mu.Unlock()
		w.WriteHeader(204)
		return
	}
	h.sortQueueLocked()
	for _, st := range h.queue {
		if st.Status != "queued" {
			continue
		}
		if model, _, ok := h.fits(d, st); ok {
			h.assignLocked(st, d, model)
			a := h.assignmentFor(st, d)
			h.mu.Unlock()
			writeJSON(w, 200, a)
			return
		}
	}
	if wait == 0 {
		h.mu.Unlock()
		w.WriteHeader(204)
		return
	}
	wt := &waiter{deviceID: d.ID, ch: make(chan *hubStep, 1)}
	h.waiters[d.ID] = wt
	h.mu.Unlock()

	timer := time.NewTimer(time.Duration(wait) * time.Second)
	defer timer.Stop()
	select {
	case st := <-wt.ch:
		h.mu.Lock()
		a := h.assignmentFor(st, d)
		h.mu.Unlock()
		writeJSON(w, 200, a)
		return
	case <-timer.C:
	case <-r.Context().Done():
	}
	h.mu.Lock()
	if h.waiters[d.ID] == wt {
		delete(h.waiters, d.ID)
	}
	select {
	case st := <-wt.ch: // assigned at the last moment
		if r.Context().Err() != nil {
			st.Attempts-- // not the device's fault
			h.requeueLocked(st, "device stopped listening", false)
			h.mu.Unlock()
			return
		}
		a := h.assignmentFor(st, d)
		h.mu.Unlock()
		writeJSON(w, 200, a)
		return
	default:
	}
	h.mu.Unlock()
	w.WriteHeader(204)
}

type progressReq struct {
	Content  string  `json:"content"`
	Thinking string  `json:"thinking"`
	Status   string  `json:"status,omitempty"`   // a plugin step: what it's doing now
	Fraction float64 `json:"fraction,omitempty"` // and how far along, 0..1
	Note     string  `json:"note,omitempty"`     // a plugin step: a line for the asker (the options it read)
}

func (h *Hub) handleProgress(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	var req progressReq
	if err := readJSON(r, &req, 8<<20); err != nil {
		writeErr(w, 400, "bad progress")
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	d.lastSeen = time.Now()
	st := h.steps[r.PathValue("id")]
	if st == nil || st.Assigned != d.ID || (st.Status != "assigned" && st.Status != "running") {
		writeJSON(w, 200, map[string]bool{"cancel": true})
		return
	}
	if st.Status == "assigned" {
		st.Status = "running"
	}
	st.LastProgress = time.Now()
	d.lastWork = time.Now()
	if req.Content != "" || req.Thinking != "" {
		st.Text.WriteString(req.Content)
		st.Thinking.WriteString(req.Thinking)
		st.emit(hubEvent{Type: "delta", Content: req.Content, Thinking: req.Thinking})
	}
	if req.Status != "" && (req.Status != st.StatusMsg || req.Fraction != st.Fraction) {
		st.StatusMsg, st.Fraction = truncate(req.Status, 200), clampFloat(req.Fraction, 0, 1)
		st.emit(hubEvent{Type: "status", Reason: st.StatusMsg, Fraction: st.Fraction})
	}
	if req.Note != "" && req.Note != st.Note {
		st.Note = truncate(req.Note, 500)
		st.emit(hubEvent{Type: "note", Reason: st.Note})
	}
	writeJSON(w, 200, map[string]bool{"cancel": st.CancelReq})
}

type completeReq struct {
	Stats ChatStats  `json:"stats"`
	Files []StepFile `json:"files,omitempty"` // what a plugin step made
}

func (h *Hub) handleComplete(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	var req completeReq
	if err := readJSON(r, &req, pluginFilesMax*4/3+(1<<20)); err != nil {
		writeErr(w, 400, "bad request")
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	st := h.steps[r.PathValue("id")]
	if st == nil || st.Assigned != d.ID || (st.Status != "assigned" && st.Status != "running") {
		writeErr(w, 409, "step isn't assigned to this device")
		return
	}
	if len(req.Files) > 0 {
		if st.Kind != "run_plugin" {
			writeErr(w, 400, "only plugin steps return files")
			return
		}
		total := 0
		for i := range req.Files {
			f := &req.Files[i]
			total += len(f.Data)
			f.Bytes = len(f.Data)
			f.Name = filepath.Base(strings.ReplaceAll(f.Name, "\\", "/"))
			if f.Name == "." || f.Name == "/" || f.Name == "" {
				f.Name = fmt.Sprintf("file-%d", i+1)
			}
		}
		if total > pluginFilesMax {
			writeErr(w, 413, "files too large")
			return
		}
		st.Files = req.Files
		for i := range st.Files {
			st.emit(hubEvent{Type: "file", File: &st.Files[i]})
		}
	}
	st.Stats = req.Stats
	d.lastWork = time.Now()
	h.finishLocked(st, d, "done", "")
	writeJSON(w, 200, map[string]bool{"ok": true})
}

type failReq struct {
	Error        string `json:"error"`
	Retryable    bool   `json:"retryable"`
	Cancelled    bool   `json:"cancelled"`
	ApproxTokens int    `json:"approx_tokens"`
}

func (h *Hub) handleFail(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	var req failReq
	if err := readJSON(r, &req, 1<<20); err != nil {
		writeErr(w, 400, "bad request")
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	st := h.steps[r.PathValue("id")]
	if st == nil || st.Assigned != d.ID || (st.Status != "assigned" && st.Status != "running") {
		writeJSON(w, 200, map[string]bool{"ok": true})
		return
	}
	d.lastWork = time.Now()
	switch {
	case req.Cancelled || st.CancelReq:
		st.Stats = ChatStats{EvalCount: req.ApproxTokens}
		h.finishLocked(st, d, "cancelled", "")
	case req.Retryable:
		h.requeueLocked(st, req.Error, true)
	default:
		h.finishLocked(st, d, "failed", req.Error)
	}
	writeJSON(w, 200, map[string]bool{"ok": true})
}

// ---------- requester endpoints ----------

type submitReq struct {
	Model    string          `json:"model"`
	Target   string          `json:"target"`
	Private  bool            `json:"private"`
	Messages []ChatMessage   `json:"messages"`
	Options  map[string]any  `json:"options"`
	Prefer   string          `json:"prefer,omitempty"`
	NeedCaps []string        `json:"need_caps,omitempty"`
	NeedCtx  int             `json:"need_ctx,omitempty"`
	Format   json.RawMessage `json:"format,omitempty"`
	Purpose  string          `json:"purpose,omitempty"`
	TaskWork bool            `json:"task_work,omitempty"` // part of a Hydra long task
	Kind     string          `json:"kind,omitempty"`      // "" (chat) or run_plugin
	Plugin   string          `json:"plugin,omitempty"`    // run_plugin: which plugin
	Input    json.RawMessage `json:"input,omitempty"`     // run_plugin: its input
	NotHere  bool            `json:"not_here,omitempty"`  // never on the asking device (work for someone else's Head)
}

// usesOthers reports whether a step would run on someone else's device (and so
// would cost the requester credits).
func (h *Hub) usesOthers(st *hubStep) bool {
	if st.Private {
		return false
	}
	if st.Target != "" {
		if t := h.st.Devices[st.Target]; t != nil && sameOwner(t.Owner, st.RequesterOwner) {
			return false
		}
	}
	return true
}

func (h *Hub) handleSubmit(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	var req submitReq
	if err := readJSON(r, &req, pluginInputMax+(1<<20)); err != nil {
		writeErr(w, 400, "bad request")
		return
	}
	switch req.Kind {
	case "", "chat":
		req.Kind = ""
		if len(req.Messages) == 0 {
			writeErr(w, 400, "nothing to send")
			return
		}
	case "run_plugin":
		if !pluginIDRe.MatchString(req.Plugin) || len(req.Input) == 0 {
			writeErr(w, 400, "which plugin, with what input?")
			return
		}
		if len(req.Input) > pluginInputMax {
			writeErr(w, 413, "That's too large for a plugin.")
			return
		}
		req.Model, req.Messages, req.NeedCtx, req.Format = "", nil, 0, nil
	default:
		writeErr(w, 400, "unknown kind of step")
		return
	}
	model := strings.TrimSpace(req.Model)
	if strings.EqualFold(model, "auto") {
		model = ""
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	st := &hubStep{
		ID: randomID(8), RequesterID: d.ID, RequesterOwner: d.Owner, RequesterName: d.Name,
		Model: model, Target: req.Target, Private: req.Private,
		Messages: req.Messages, Options: req.Options, Prefer: req.Prefer, NeedCaps: req.NeedCaps,
		NeedCtx: req.NeedCtx, Format: req.Format, Purpose: req.Purpose, TaskWork: req.TaskWork,
		Kind: req.Kind, Plugin: req.Plugin, Input: req.Input,
		Status: "queued", Created: time.Now(), Exclude: map[string]bool{},
		subs: map[chan hubEvent]struct{}{},
	}
	if req.NotHere {
		st.Exclude[d.ID] = true
	}
	if st.Kind == "run_plugin" {
		_, _, st.optionsLeft = optionsWanted(req.Input)
	}
	demand := func(e demandEvent) { // plugin steps aren't demand for models
		if st.Kind != "run_plugin" {
			h.noteDemandLocked(e)
		}
	}
	// Out of credits: you can still use your own devices (free), but not others'.
	if h.usesOthers(st) && h.balanceLocked(d.Owner) < 0 {
		demand(demandEvent{Model: model, Caps: req.NeedCaps, Unmet: true, Wait: -1})
		writeErr(w, 402, "You're out of credits. Lend your GPU to earn more, or switch on \"Only my devices\" to use your own for free.")
		return
	}
	if msg := h.runnableLocked(st); msg != "" {
		demand(demandEvent{Model: model, Caps: req.NeedCaps, Unmet: true, Wait: -1})
		writeErr(w, 409, msg)
		return
	}
	demand(demandEvent{Model: model, Caps: req.NeedCaps, Wait: -1})
	h.steps[st.ID] = st
	h.queue = append(h.queue, st)
	h.dispatchLocked()
	writeJSON(w, 200, map[string]any{"id": st.ID, "status": st.Status})
}

// submitInternalLocked queues a step on the hub's own behalf (library work).
func (h *Hub) submitInternalLocked(st *hubStep) bool {
	st.ID = randomID(8)
	st.Internal = true
	st.RequesterID, st.RequesterOwner, st.RequesterName = "hub", "", "library"
	st.Status, st.Created, st.Exclude = "queued", time.Now(), map[string]bool{}
	st.subs = map[chan hubEvent]struct{}{}
	if !h.possibleLocked(st) {
		return false
	}
	h.steps[st.ID] = st
	h.queue = append(h.queue, st)
	h.dispatchLocked()
	return true
}

func (h *Hub) runnableLocked(st *hubStep) string {
	if st.Kind == "run_plugin" {
		if st.Target != "" {
			t := h.st.Devices[st.Target]
			if t == nil || !h.onlineLocked(t) || !t.lending {
				return "That device isn't lending right now."
			}
			if _, _, ok := h.fits(t, st); !ok {
				return t.Name + " can't run the " + st.Plugin + " plugin."
			}
			return ""
		}
		if !h.possibleLocked(st) {
			if st.Private {
				return "None of your own devices with the " + st.Plugin + " plugin is lending right now."
			}
			return "No device with the " + st.Plugin + " plugin is lending right now."
		}
		return ""
	}
	what := st.Model
	if what == "" {
		what = "a model"
		if len(st.NeedCaps) > 0 {
			what = "a model with " + strings.Join(st.NeedCaps, " and ")
		}
	}
	if st.Target != "" {
		t := h.st.Devices[st.Target]
		switch {
		case t == nil:
			return "That device isn't in this network anymore."
		case !h.onlineLocked(t):
			return t.Name + " is offline."
		case !t.lending || t.draining:
			return t.Name + " isn't lending right now."
		case !t.ollamaOK:
			return t.Name + "'s Ollama isn't running."
		case st.Private && !sameOwner(t.Owner, st.RequesterOwner):
			return t.Name + " belongs to " + t.Owner + ". Private chats only run on your own devices."
		}
		if _, _, ok := h.fits(t, st); !ok {
			if st.NeedCtx > 0 {
				return t.Name + " doesn't lend " + what + " with enough room for this much text."
			}
			return t.Name + " doesn't lend " + what + "."
		}
		return ""
	}
	if !h.possibleLocked(st) {
		roomy := &hubStep{Model: st.Model, Private: st.Private, RequesterOwner: st.RequesterOwner, NeedCaps: st.NeedCaps, Kind: st.Kind, Exclude: st.Exclude}
		if st.NeedCtx > 0 && h.possibleLocked(roomy) {
			return fmt.Sprintf("No device lending %s has room for this much text (about %dK tokens).", what, (st.NeedCtx+999)/1000)
		}
		if st.Private {
			return "None of your own devices is lending " + what + " right now."
		}
		return "No device is lending " + what + " right now."
	}
	return ""
}

func (h *Hub) handleCancel(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	h.mu.Lock()
	defer h.mu.Unlock()
	st := h.steps[r.PathValue("id")]
	if st == nil || st.RequesterID != d.ID {
		writeErr(w, 404, "unknown step")
		return
	}
	switch st.Status {
	case "queued":
		h.removeFromQueueLocked(st)
		h.finishLocked(st, nil, "cancelled", "")
	case "assigned", "running":
		st.CancelReq = true
	}
	writeJSON(w, 200, map[string]bool{"ok": true})
}

func (h *Hub) handleEvents(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	fl, ok := w.(http.Flusher)
	if !ok {
		writeErr(w, 500, "streaming unsupported")
		return
	}
	h.mu.Lock()
	st := h.steps[r.PathValue("id")]
	if st == nil || st.RequesterID != d.ID {
		h.mu.Unlock()
		writeErr(w, 404, "unknown step")
		return
	}
	replay := h.replayLocked(st)
	terminal := isTerminal(st.Status)
	ch := make(chan hubEvent, 4096)
	if !terminal {
		st.subs[ch] = struct{}{}
	}
	h.mu.Unlock()

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(200)
	for _, ev := range replay {
		writeSSE(w, "", ev)
	}
	fl.Flush()
	if terminal {
		return
	}
	defer func() {
		h.mu.Lock()
		delete(st.subs, ch)
		h.mu.Unlock()
	}()
	ping := time.NewTicker(15 * time.Second)
	defer ping.Stop()
	for {
		select {
		case ev, ok := <-ch:
			if !ok {
				return
			}
			writeSSE(w, "", ev)
			fl.Flush()
			if ev.Type == "done" || ev.Type == "error" || ev.Type == "cancelled" {
				return
			}
		case <-ping.C:
			fmt.Fprint(w, ": ping\n\n")
			fl.Flush()
		case <-r.Context().Done():
			return
		}
	}
}

func writeSSE(w http.ResponseWriter, event string, v any) {
	b, _ := json.Marshal(v)
	if event != "" {
		fmt.Fprintf(w, "event: %s\n", event)
	}
	fmt.Fprintf(w, "data: %s\n\n", b)
}

func (h *Hub) replayLocked(st *hubStep) []hubEvent {
	var out []hubEvent
	if st.Assigned != "" && st.Status != "queued" {
		if d := h.st.Devices[st.Assigned]; d != nil {
			out = append(out, hubEvent{Type: "assigned", Device: d.ID, DeviceName: d.Name, Owner: d.Owner, Model: st.RunModel})
		}
	}
	if st.Note != "" {
		out = append(out, hubEvent{Type: "note", Reason: st.Note})
	}
	if st.Text.Len() > 0 || st.Thinking.Len() > 0 {
		out = append(out, hubEvent{Type: "delta", Content: st.Text.String(), Thinking: st.Thinking.String()})
	}
	if st.StatusMsg != "" && !isTerminal(st.Status) {
		out = append(out, hubEvent{Type: "status", Reason: st.StatusMsg, Fraction: st.Fraction})
	}
	for i := range st.Files {
		out = append(out, hubEvent{Type: "file", File: &st.Files[i]})
	}
	switch st.Status {
	case "queued":
		out = append(out, hubEvent{Type: "queued"})
	case "done":
		stats := st.Stats
		out = append(out, hubEvent{Type: "done", Stats: &stats, Credits: st.Credits, Free: st.Free})
	case "failed":
		out = append(out, hubEvent{Type: "error", Error: st.Err})
	case "cancelled":
		stats := st.Stats
		out = append(out, hubEvent{Type: "cancelled", Stats: &stats, Credits: st.Credits, Free: st.Free})
	}
	return out
}

func isTerminal(s string) bool { return s == "done" || s == "failed" || s == "cancelled" }

func (st *hubStep) emit(ev hubEvent) {
	for ch := range st.subs {
		select {
		case ch <- ev:
		default: // reader is hopelessly behind; it can reconnect and replay
			close(ch)
			delete(st.subs, ch)
		}
	}
}

func (st *hubStep) closeSubs() {
	for ch := range st.subs {
		close(ch)
	}
	st.subs = map[chan hubEvent]struct{}{}
}

// ---------- lifecycle ----------

func (h *Hub) requeueLocked(st *hubStep, reason string, exclude bool) {
	if exclude && st.Assigned != "" {
		st.Exclude[st.Assigned] = true
	}
	if st.Attempts >= maxAttempts {
		h.finishLocked(st, nil, "failed", "Gave up after "+fmt.Sprint(st.Attempts)+" tries. Last problem: "+reason)
		return
	}
	st.Status = "queued"
	st.Assigned = ""
	st.Text.Reset()
	st.Thinking.Reset()
	st.StatusMsg, st.Fraction, st.Files, st.Note = "", 0, nil, ""
	st.unrunnable = time.Time{}
	h.queue = append(h.queue, st)
	st.emit(hubEvent{Type: "requeued", Reason: reason})
	h.dispatchLocked()
}

// finishLocked ends a step, charges credits and records it.
func (h *Hub) finishLocked(st *hubStep, worker *hubDevice, status, errMsg string) {
	st.Status = status
	st.Err = errMsg
	st.Finished = time.Now()
	h.removeFromQueueLocked(st)
	if worker != nil && !st.Internal && (status == "done" || status == "cancelled") {
		st.Credits, st.Free = h.chargeLocked(st, worker)
	}
	if st.Internal {
		st.Free = true
	}
	stats := st.Stats
	switch status {
	case "done":
		st.emit(hubEvent{Type: "done", Stats: &stats, Credits: st.Credits, Free: st.Free})
	case "cancelled":
		st.emit(hubEvent{Type: "cancelled", Stats: &stats, Credits: st.Credits, Free: st.Free})
	default:
		st.emit(hubEvent{Type: "error", Error: errMsg})
	}
	st.closeSubs()
	if st.onDone != nil {
		st.onDone(h, st)
	}
	sum := StepSummary{
		ID: st.ID, At: st.Finished, Requester: st.RequesterOwner, RequesterDevice: st.RequesterName, RequesterID: st.RequesterID,
		Model: st.RunModel, Purpose: st.Purpose, Tokens: st.Stats.EvalCount, PromptTokens: st.Stats.PromptEvalCount,
		TokPerSec: st.Stats.TokPerSec(), Credits: st.Credits, Free: st.Free, Status: status, Error: errMsg,
	}
	if st.Internal {
		sum.Requester = "network"
	}
	if !st.AssignedAt.IsZero() {
		sum.WaitSec = round1(st.AssignedAt.Sub(st.Created).Seconds())
	}
	if sum.Model == "" {
		sum.Model = st.Model
	}
	if st.Kind == "run_plugin" {
		if sum.Model == "" {
			sum.Model = st.Plugin + " plugin"
		}
		h.pluginStepDoneLocked(st, worker, status)
	} else if sum.Model == "" && st.Kind != "" && st.Kind != "chat" {
		sum.Model = strings.Replace(st.Kind, "run_", "test run: ", 1)
	}
	if worker != nil {
		sum.Worker, sum.WorkerDevice, sum.WorkerID = worker.Owner, worker.Name, worker.ID
	}
	h.st.Recent = append(h.st.Recent, sum)
	if len(h.st.Recent) > recentKeep {
		h.st.Recent = h.st.Recent[len(h.st.Recent)-recentKeep:]
	}
	h.dirty = true
}

// modelWeight makes bigger models cost more per token: 8B is the reference.
func modelWeight(paramsB float64) float64 {
	if paramsB <= 8 {
		return 1
	}
	return round2(paramsB / 8)
}

func (h *Hub) chargeLocked(st *hubStep, worker *hubDevice) (float64, bool) {
	params := 0.0
	for _, m := range worker.models {
		if normModel(m.Name) == normModel(st.RunModel) {
			params = m.ParamsB
		}
	}
	credits := round2((float64(st.Stats.EvalCount) + 0.1*float64(st.Stats.PromptEvalCount)) / 1000 * modelWeight(params))
	note := fmt.Sprintf("%s on %s", st.RunModel, worker.Name)
	if st.Kind == "run_plugin" {
		// Plugins are priced by the time they hold the device: 2 credits a minute, never more
		// than the hub itself saw pass between handing the step out and its end.
		secs := float64(st.Stats.TotalDuration) / 1e9
		if wall := time.Since(st.AssignedAt).Seconds(); secs < 0 || secs > wall {
			secs = wall
		}
		credits = round2(secs / 30)
		note = fmt.Sprintf("%s plugin on %s", st.Plugin, worker.Name)
	}
	if sameOwner(worker.Owner, st.RequesterOwner) {
		return 0, true // your own devices are free
	}
	if credits > 0 {
		h.st.Balances[ownerKey(st.RequesterOwner)] -= credits
		h.st.Balances[ownerKey(worker.Owner)] += credits
		h.addTxLocked(LedgerTx{At: time.Now(), From: st.RequesterOwner, To: worker.Owner, Amount: credits,
			Note: note, StepID: st.ID})
	}
	if st.Kind == "run_plugin" {
		// A Head bridges what models can't do well with a deterministic tool, so its owner
		// earns extra whenever it runs for someone else: half the time charge again, and never
		// less than a small flat amount (a tool that finishes in a second still did the job).
		// The network mints the bonus; the asker pays only the normal charge.
		bonus := round2(math.Max(pluginBonusMin, credits*pluginBonusShare))
		h.st.Balances[ownerKey(worker.Owner)] += bonus
		h.addTxLocked(LedgerTx{At: time.Now(), From: "network", To: worker.Owner, Amount: bonus,
			Note: "Head bonus: " + st.Plugin, StepID: st.ID})
	}
	if credits <= 0 {
		return 0, false
	}
	return credits, false
}

func (h *Hub) addTxLocked(tx LedgerTx) {
	h.st.Ledger = append(h.st.Ledger, tx)
	if len(h.st.Ledger) > ledgerKeep {
		h.st.Ledger = h.st.Ledger[len(h.st.Ledger)-ledgerKeep:]
	}
	h.dirty = true
}

func (h *Hub) monitor() {
	t := time.NewTicker(2 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-h.stop:
			return
		case <-t.C:
		}
		h.mu.Lock()
		now := time.Now()
		for _, d := range h.st.Devices {
			if d.online && now.Sub(d.lastSeen) >= offlineAfter {
				d.online = false
				d.lending = false
				delete(h.waiters, d.ID)
				log.Printf("hub: %s went offline", d.Name)
			}
		}
		for id, st := range h.steps {
			switch st.Status {
			case "assigned", "running":
				d := h.st.Devices[st.Assigned]
				switch {
				case d == nil || !h.onlineLocked(d):
					h.requeueLocked(st, "the device went offline", true)
				case st.Status == "assigned" && now.Sub(st.LastProgress) > ackAfter:
					h.requeueLocked(st, d.Name+" didn't pick it up", true)
				case st.Status == "running" && now.Sub(st.LastProgress) > stallAfter:
					h.requeueLocked(st, d.Name+" stopped responding", true)
				}
			case "queued":
				if h.possibleLocked(st) {
					st.unrunnable = time.Time{}
				} else if st.unrunnable.IsZero() {
					st.unrunnable = now
				} else if now.Sub(st.unrunnable) > 30*time.Second {
					h.finishLocked(st, nil, "failed", "No device that can run this is lending right now.")
				}
				if st.Status == "queued" && now.Sub(st.Created) > queueTimeout {
					h.finishLocked(st, nil, "failed", "Waited too long for a free device.")
				}
			default:
				if now.Sub(st.Finished) > 10*time.Minute {
					delete(h.steps, id)
				}
			}
		}
		h.libraryTickLocked(now)
		h.dispatchLocked()
		if h.dirty {
			h.saveLocked()
		}
		h.mu.Unlock()
	}
}

func atoiDefault(s string, def int) int {
	var v int
	if _, err := fmt.Sscan(s, &v); err != nil {
		return def
	}
	return v
}

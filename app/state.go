package main

import (
	"fmt"
	"strings"
)

type HostingView struct {
	Enabled   bool        `json:"enabled"`
	Port      int         `json:"port"`
	Invite    string      `json:"invite,omitempty"`
	Name      string      `json:"name,omitempty"`
	Addresses []LocalAddr `json:"addresses,omitempty"`
	Error     string      `json:"error,omitempty"`
}

type NetworkView struct {
	Joined   bool               `json:"joined"`
	Address  string             `json:"address"`
	OK       bool               `json:"ok"`
	Error    string             `json:"error,omitempty"`
	Name     string             `json:"name"`
	Host     string             `json:"host"` // who hosts it (reviews the library)
	IdleMin  int                `json:"verify_idle_min"`
	Admin    bool               `json:"admin"`
	Balance  float64            `json:"balance"`
	Devices  []DeviceView       `json:"devices"`
	Recent   []StepSummary      `json:"recent"`
	Queue    int                `json:"queue"`
	Balances map[string]float64 `json:"balances"`
	Demand   []DemandView       `json:"demand"`
	Library  LibraryStats       `json:"library"`
}

// HelpItem is a way this computer could help with what the network is
// waiting for: connect, share a model it has, or download one that fits.
type HelpItem struct {
	Action  string  `json:"action"` // connect, share, download
	Model   string  `json:"model,omitempty"`
	Title   string  `json:"title"`
	Detail  string  `json:"detail"`
	SizeGB  float64 `json:"size_gb,omitempty"`
	Waiting int     `json:"waiting"`
	Unmet   int     `json:"unmet"`
	AvgWait float64 `json:"avg_wait_s"`
}

type CatalogView struct {
	Items []CatalogItem       `json:"items"`
	Roles []map[string]string `json:"roles"`
}

type DeviceSelf struct {
	ID    string  `json:"id"`
	Name  string  `json:"name"`
	Owner string  `json:"owner"`
	Info  SysInfo `json:"info"`
}

type SettingsView struct {
	DeviceName             string   `json:"device_name"`
	Owner                  string   `json:"owner"`
	OllamaURL              string   `json:"ollama_url"`
	MaxSlots               int      `json:"max_slots"`
	MaxModelGB             float64  `json:"max_model_gb"`
	Unshared               []string `json:"unshared"`
	AutoStartOllama        bool     `json:"auto_start_ollama"`
	FreeMemoryOnDisconnect bool     `json:"free_memory_on_disconnect"`
	ConnectOnLaunch        bool     `json:"connect_on_launch"`
	AppWindow              bool     `json:"app_window"`
	HostPort               int      `json:"host_port"`
	SetupDone              bool     `json:"setup_done"`
	RunTests               bool     `json:"run_tests"`
	AutoHelp               bool     `json:"auto_help"`
	AutoJoin               bool     `json:"auto_join"`
	PoolAddr               string   `json:"pool_addr"`
	LendPlugins            bool     `json:"lend_plugins"`
	UnsandboxedHeads       bool     `json:"unsandboxed_heads"`
}

type UIState struct {
	Version  string        `json:"version"`
	Device   DeviceSelf    `json:"device"`
	Ollama   OllamaState   `json:"ollama"`
	Lending  LendingView   `json:"lending"`
	Network  NetworkView   `json:"network"`
	Hosting  HostingView   `json:"hosting"`
	Settings SettingsView  `json:"settings"`
	DataDir  string        `json:"data_dir"`
	Profile  DeviceProfile `json:"profile"`
	Catalog  CatalogView   `json:"catalog"`
	Help     []HelpItem    `json:"help"`
}

func (a *App) buildState() UIState {
	cfg := a.config()
	lv, hubOK, hubErr, snap := a.node.view(a.ollama.Running())
	lv.Shared = len(a.node.sharedModels())
	s := UIState{
		Version: Version,
		Device:  DeviceSelf{ID: cfg.DeviceID, Name: cfg.DeviceName, Owner: cfg.Owner, Info: a.sysInfo()},
		Ollama:  a.ollama.State(),
		Lending: lv,
		Hosting: a.hostingView(),
		Settings: SettingsView{
			DeviceName: cfg.DeviceName, Owner: cfg.Owner, OllamaURL: a.ollama.Client().Base,
			MaxSlots: cfg.MaxSlots, MaxModelGB: cfg.MaxModelGB, Unshared: cfg.Unshared,
			AutoStartOllama: cfg.AutoStartOllama, FreeMemoryOnDisconnect: cfg.FreeMemoryOnDisconnect,
			ConnectOnLaunch: cfg.ConnectOnLaunch, AppWindow: cfg.AppWindow, HostPort: cfg.HostPort,
			SetupDone: cfg.SetupDone, RunTests: cfg.RunTests, AutoHelp: cfg.AutoHelp, AutoJoin: cfg.AutoJoin, PoolAddr: cfg.PoolAddr,
			LendPlugins: cfg.LendPlugins, UnsandboxedHeads: cfg.UnsandboxedHeads,
		},
		DataDir: a.dataDir,
		Profile: a.profile(),
		Help:    []HelpItem{},
	}
	s.Ollama.Models = a.annotate(s.Ollama.Models)
	items, best := a.catalogFor()
	s.Catalog = CatalogView{Items: items, Roles: rolesSorted(best)}
	if s.Settings.Unshared == nil {
		s.Settings.Unshared = []string{}
	}
	if s.Ollama.Models == nil {
		s.Ollama.Models = []ModelInfo{}
	}
	s.Network = NetworkView{Joined: cfg.Joined(), Address: cfg.HubAddress, OK: hubOK, Error: hubErr, Name: cfg.NetworkName,
		Devices: []DeviceView{}, Recent: []StepSummary{}, Balances: map[string]float64{}, Demand: []DemandView{}}
	if snap != nil && cfg.Joined() {
		s.Network.Devices = snap.Devices
		s.Network.Recent = snap.Recent
		s.Network.Queue = snap.Queue
		s.Network.Balances = snap.Balances
		s.Network.Host = snap.Network.Owner
		s.Network.IdleMin = snap.Network.VerifyIdleMin
		s.Network.Admin = snap.Admin
		s.Network.Library = snap.Library
		if snap.Demand != nil {
			s.Network.Demand = snap.Demand
		}
		s.Help = a.helpItems(snap.Demand, s.Ollama.Models, items, lv.State)
		if snap.Network.Name != "" {
			s.Network.Name = snap.Network.Name
		}
		for name, bal := range snap.Balances {
			if sameOwner(name, cfg.Owner) {
				s.Network.Balance = bal
			}
		}
		if s.Network.Devices == nil {
			s.Network.Devices = []DeviceView{}
		}
		if s.Network.Recent == nil {
			s.Network.Recent = []StepSummary{}
		}
	}
	return s
}

// helpItems compares what the network has been waiting for with what this
// computer has or could download, and suggests up to three ways to help.
func (a *App) helpItems(demand []DemandView, models []ModelInfo, catalogItems []CatalogItem, lending string) []HelpItem {
	cfg := a.config()
	out := []HelpItem{}
	seen := map[string]bool{}
	helping := lending == "connected" || lending == "draining"
	for _, d := range demand {
		if d.Unmet == 0 && d.Waiting == 0 && d.AvgWait < 15 {
			continue
		}
		what := "any model"
		if d.Model != "" {
			what = d.Model
		} else if len(d.Caps) > 0 {
			what = "a model with " + strings.Join(d.Caps, " and ")
		}
		var parts []string
		if d.Unmet > 0 {
			parts = append(parts, plural(d.Unmet, "request")+" found no device in the last hour")
		}
		if d.Waiting > 0 {
			parts = append(parts, fmt.Sprintf("%d waiting now", d.Waiting))
		}
		if d.AvgWait >= 15 {
			parts = append(parts, fmt.Sprintf("waits average %.0fs", d.AvgWait))
		}
		item := HelpItem{Waiting: d.Waiting, Unmet: d.Unmet, AvgWait: d.AvgWait, Detail: "People asked for " + what + ": " + strings.Join(parts, ", ") + "."}

		// A model already here that would do?
		var have *ModelInfo
		for i, m := range models {
			if !m.CanChat() || m.Fits == "too_big" {
				continue
			}
			if d.Model != "" && normModel(m.Name) != normModel(d.Model) {
				continue
			}
			ok := true
			for _, c := range d.Caps {
				if !m.HasCap(c) {
					ok = false
				}
			}
			if ok {
				have = &models[i]
				break
			}
		}
		switch {
		case have != nil && (cfg.IsUnshared(have.Name) || (cfg.MaxModelGB > 0 && have.SizeGB() > cfg.MaxModelGB)):
			item.Action, item.Model = "share", have.Name
			item.Title = "Share " + have.Name + " to help"
		case have != nil && !helping:
			item.Action, item.Model = "connect", have.Name
			item.Title = "Connect: you have " + have.Name
		case have != nil:
			continue // already helping with it
		default:
			pick := -1
			for i, c := range catalogItems {
				if c.Installed || (c.Fit != "comfortable" && c.Fit != "tight") || c.OverLimit {
					continue
				}
				if d.Model != "" && normModel(c.Tag) != normModel(d.Model) {
					continue
				}
				ok := true
				for _, cp := range d.Caps {
					if !contains(c.Caps, cp) {
						ok = false
					}
				}
				if !ok || contains(c.Caps, "embedding") || contains(c.Caps, "image") {
					continue
				}
				if pick < 0 || (c.Fit == "comfortable" && catalogItems[pick].Fit != "comfortable") ||
					(c.Fit == catalogItems[pick].Fit && c.ParamsB > catalogItems[pick].ParamsB) {
					pick = i
				}
			}
			if pick < 0 {
				continue
			}
			c := catalogItems[pick]
			item.Action, item.Model, item.SizeGB = "download", c.Tag, c.SizeGB
			item.Title = fmt.Sprintf("Download %s (%.0f GB) to help", c.Label, c.SizeGB)
		}
		if seen[item.Action+item.Model] {
			continue
		}
		seen[item.Action+item.Model] = true
		out = append(out, item)
		if len(out) == 3 {
			break
		}
	}
	return out
}

func plural(n int, word string) string {
	if n == 1 {
		return "1 " + word
	}
	return fmt.Sprintf("%d %ss", n, word)
}

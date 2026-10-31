package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

// Config is everything Chimera remembers about this computer.
type Config struct {
	DeviceID   string `json:"device_id"`
	DeviceName string `json:"device_name"`
	Owner      string `json:"owner"`
	OllamaURL  string `json:"ollama_url"`

	// Network membership (set when you join or host).
	HubAddress  string `json:"hub_address"`
	Invite      string `json:"invite"`
	Token       string `json:"token"`
	NetworkName string `json:"network_name"`

	// A hub everyone joins automatically from any network (e.g. the Studio over
	// Tailscale). When set, the app auto-joins it on launch. Overrides nothing
	// once you've joined a network manually.
	PoolAddr string `json:"pool_addr"`

	// Hosting a hub on this computer.
	Hosting  bool `json:"hosting"`
	HostPort int  `json:"host_port"`

	// Lending limits.
	MaxSlots               int      `json:"max_slots"`
	MaxModelGB             float64  `json:"max_model_gb"`
	Unshared               []string `json:"unshared"`
	AutoStartOllama        bool     `json:"auto_start_ollama"`
	FreeMemoryOnDisconnect bool     `json:"free_memory_on_disconnect"`
	ConnectOnLaunch        bool     `json:"connect_on_launch"`
	AppWindow              bool     `json:"app_window"`
	RunTests               bool     `json:"run_tests"` // test-run library scripts here (host's devices only)
	AutoHelp               bool     `json:"auto_help"` // let my devices auto-connect to help my long tasks
	AutoHelpInit           bool     `json:"auto_help_init"`
	CheckResults           bool     `json:"check_results"` // run a looping long task's Blender/Python result here, sandboxed, to check it
	CheckResultsInit       bool     `json:"check_results_init"`
	AutoJoin               bool     `json:"auto_join"`         // when hosting, let devices on this Wi-Fi join without a code
	LendPlugins            bool     `json:"lend_plugins"`      // let the network run the plugins installed here
	UnsandboxedHeads       bool     `json:"unsandboxed_heads"` // Windows: run Heads with no sandbox (owner's explicit choice)
	PluginsInit            bool     `json:"plugins_init"`
	DefaultsApplied        bool     `json:"defaults_applied"`
	SetupDone              bool     `json:"setup_done"`
}

func (c Config) Joined() bool { return c.HubAddress != "" && c.Token != "" }

func (c Config) IsUnshared(model string) bool {
	for _, m := range c.Unshared {
		if normModel(m) == normModel(model) {
			return true
		}
	}
	return false
}

func configPath(dir string) string { return filepath.Join(dir, "config.json") }

func loadConfig(dir string) Config {
	var c Config
	if b, err := os.ReadFile(configPath(dir)); err == nil {
		_ = json.Unmarshal(b, &c)
	} else {
		c.MaxSlots = 1
		c.AutoStartOllama = true
		c.FreeMemoryOnDisconnect = true
		c.AppWindow = true
	}
	if c.DeviceID == "" {
		c.DeviceID = randomID(8)
	}
	if c.DeviceName == "" {
		c.DeviceName = friendlyComputerName()
	}
	if c.MaxSlots < 1 {
		c.MaxSlots = 1
	}
	if c.HostPort == 0 {
		c.HostPort = defaultHubPort
	}
	if !c.PluginsInit { // lending plugins is on by default, like lending models
		c.LendPlugins = true
		c.PluginsInit = true
	}
	if !c.AutoHelpInit { // default on, once, for new and existing installs
		c.AutoHelp = true
		c.AutoJoin = true
		c.ConnectOnLaunch = true // join the pool and start lending when opened
		c.AutoHelpInit = true
	}
	if !c.CheckResultsInit { // default on, once, for new and existing installs
		c.CheckResults = true
		c.CheckResultsInit = true
	}
	return c
}

// defaultPoolAddr is a hub baked into the build that every device joins
// automatically (e.g. the Studio's Tailscale address). Empty = none; set it
// here or per-device in Settings → Network → Pool address.
var defaultPoolAddr = ""

func (c Config) pool() string {
	if a := strings.TrimSpace(c.PoolAddr); a != "" {
		return a
	}
	return strings.TrimSpace(defaultPoolAddr)
}

func saveConfig(dir string, c Config) error {
	b, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return err
	}
	return writeFileAtomic(configPath(dir), b)
}

func friendlyComputerName() string {
	if runtime.GOOS == "darwin" {
		if n := runOut(2e9, "scutil", "--get", "ComputerName"); n != "" {
			return n
		}
	}
	h, _ := os.Hostname()
	h = strings.TrimSuffix(h, ".local")
	h = strings.TrimSuffix(h, ".lan")
	if h == "" {
		h = "My computer"
	}
	return h
}

package main

import (
	"bufio"
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// SysInfo describes the hardware, shown on device cards across the network.
type SysInfo struct {
	OS        string    `json:"os"`
	OSVersion string    `json:"os_version"`
	Arch      string    `json:"arch"`
	Chip      string    `json:"chip"`
	RAMGB     float64   `json:"ram_gb"`
	Cores     int       `json:"cores"`
	GPUs      []GPUInfo `json:"gpus"`
}

type GPUInfo struct {
	Name   string  `json:"name"`
	VRAMGB float64 `json:"vram_gb,omitempty"`
}

func runOut(timeout time.Duration, name string, args ...string) string {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, name, args...)
	hideWindow(cmd)
	out, err := cmd.Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

func detectSysInfo() SysInfo {
	s := SysInfo{Arch: runtime.GOARCH, Cores: runtime.NumCPU()}
	switch runtime.GOOS {
	case "darwin":
		s.OS = "macOS"
		s.OSVersion = runOut(3*time.Second, "sw_vers", "-productVersion")
		s.Chip = runOut(3*time.Second, "sysctl", "-n", "machdep.cpu.brand_string")
		if v, err := strconv.ParseFloat(runOut(3*time.Second, "sysctl", "-n", "hw.memsize"), 64); err == nil {
			s.RAMGB = round1(v / (1 << 30))
		}
		gpu := GPUInfo{Name: s.Chip}
		if out := runOut(8*time.Second, "system_profiler", "SPDisplaysDataType"); out != "" {
			for _, line := range strings.Split(out, "\n") {
				l := strings.TrimSpace(line)
				if strings.HasPrefix(l, "Total Number of Cores:") {
					cores := strings.TrimSpace(strings.TrimPrefix(l, "Total Number of Cores:"))
					gpu.Name = strings.TrimSpace(cores + "-core GPU")
					break
				}
			}
		}
		// Apple GPUs share unified memory.
		gpu.VRAMGB = s.RAMGB
		s.GPUs = []GPUInfo{gpu}
	case "windows":
		s.OS = "Windows"
		ps := func(cmd string) string {
			return runOut(10*time.Second, "powershell", "-NoProfile", "-NonInteractive", "-Command", cmd)
		}
		s.OSVersion = strings.TrimPrefix(ps("(Get-CimInstance Win32_OperatingSystem).Caption"), "Microsoft ")
		s.Chip = strings.TrimSpace(ps("(Get-CimInstance Win32_Processor | Select-Object -First 1).Name"))
		if v, err := strconv.ParseFloat(ps("(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"), 64); err == nil {
			s.RAMGB = round1(v / (1 << 30))
		}
		s.GPUs = nvidiaGPUs()
		// The display-adapter registry keys have the real memory size for AMD
		// and Intel cards (Win32_VideoController caps it at 4 GB).
		out := ps(`Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0*' -ErrorAction SilentlyContinue | ForEach-Object { "$($_.DriverDesc)|$($_.'HardwareInformation.qwMemorySize')|$($_.'HardwareInformation.MemorySize')" }`)
		for _, line := range strings.Split(out, "\n") {
			parts := strings.Split(strings.TrimSpace(line), "|")
			if len(parts) < 3 || skipGPU(parts[0]) || haveGPU(s.GPUs, parts[0]) {
				continue
			}
			g := GPUInfo{Name: strings.TrimSpace(parts[0])}
			for _, v := range parts[1:] {
				if b, err := strconv.ParseFloat(strings.TrimSpace(v), 64); err == nil && b > 0 {
					g.VRAMGB = round1(b / (1 << 30))
					break
				}
			}
			s.GPUs = append(s.GPUs, g)
		}
		if len(s.GPUs) == 0 {
			for _, n := range strings.Split(ps("Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"), "\n") {
				if n = strings.TrimSpace(n); n != "" && !skipGPU(n) {
					s.GPUs = append(s.GPUs, GPUInfo{Name: n})
				}
			}
		}
	default:
		s.OS = "Linux"
		if f, err := os.Open("/etc/os-release"); err == nil {
			sc := bufio.NewScanner(f)
			for sc.Scan() {
				if v, ok := strings.CutPrefix(sc.Text(), "PRETTY_NAME="); ok {
					s.OSVersion = strings.Trim(v, `"`)
				}
			}
			f.Close()
		}
		if f, err := os.Open("/proc/cpuinfo"); err == nil {
			sc := bufio.NewScanner(f)
			for sc.Scan() {
				if k, v, ok := strings.Cut(sc.Text(), ":"); ok && strings.TrimSpace(k) == "model name" {
					s.Chip = strings.TrimSpace(v)
					break
				}
			}
			f.Close()
		}
		if f, err := os.Open("/proc/meminfo"); err == nil {
			sc := bufio.NewScanner(f)
			for sc.Scan() {
				if v, ok := strings.CutPrefix(sc.Text(), "MemTotal:"); ok {
					fields := strings.Fields(v)
					if len(fields) > 0 {
						if kb, err := strconv.ParseFloat(fields[0], 64); err == nil {
							s.RAMGB = round1(kb / (1 << 20))
						}
					}
					break
				}
			}
			f.Close()
		}
		s.GPUs = append(nvidiaGPUs(), amdLinuxGPUs()...)
		if len(s.GPUs) == 0 {
			if out := runOut(4*time.Second, "sh", "-c", "lspci 2>/dev/null | grep -Ei 'vga|3d controller'"); out != "" {
				for _, line := range strings.Split(out, "\n") {
					if _, v, ok := strings.Cut(line, ": "); ok {
						s.GPUs = append(s.GPUs, GPUInfo{Name: strings.TrimSpace(v)})
					}
				}
			}
		}
	}
	if s.GPUs == nil {
		s.GPUs = []GPUInfo{}
	}
	return s
}

func nvidiaGPUs() []GPUInfo {
	out := runOut(5*time.Second, "nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits")
	var gpus []GPUInfo
	for _, line := range strings.Split(out, "\n") {
		name, mem, ok := strings.Cut(line, ",")
		if !ok {
			continue
		}
		g := GPUInfo{Name: strings.TrimSpace(name)}
		if mb, err := strconv.ParseFloat(strings.TrimSpace(mem), 64); err == nil {
			g.VRAMGB = round1(mb / 1024)
		}
		gpus = append(gpus, g)
	}
	return gpus
}

func skipGPU(name string) bool {
	n := strings.ToLower(strings.TrimSpace(name))
	return n == "" || strings.Contains(n, "basic display") || strings.Contains(n, "basic render") ||
		strings.Contains(n, "virtual") || strings.Contains(n, "remote display") || strings.Contains(n, "indirect display")
}

func haveGPU(gpus []GPUInfo, name string) bool {
	n := strings.ToLower(strings.TrimSpace(name))
	for _, g := range gpus {
		if strings.Contains(strings.ToLower(g.Name), n) || strings.Contains(n, strings.ToLower(g.Name)) {
			return true
		}
	}
	return false
}

// amdLinuxGPUs reads AMD cards' memory from the amdgpu driver.
func amdLinuxGPUs() []GPUInfo {
	var out []GPUInfo
	seen := map[string]bool{}
	matches, _ := filepath.Glob("/sys/class/drm/card*/device/mem_info_vram_total")
	for _, m := range matches {
		dev := filepath.Dir(m)
		real, err := filepath.EvalSymlinks(dev)
		if err != nil || seen[real] {
			continue
		}
		seen[real] = true
		b, err := os.ReadFile(m)
		if err != nil {
			continue
		}
		bytes, err := strconv.ParseFloat(strings.TrimSpace(string(b)), 64)
		if err != nil || bytes <= 0 {
			continue
		}
		name := "AMD GPU"
		if line := runOut(3*time.Second, "lspci", "-s", filepath.Base(real)); line != "" {
			if _, v, ok := strings.Cut(line, ": "); ok {
				name = strings.TrimSpace(v)
			}
		}
		out = append(out, GPUInfo{Name: name, VRAMGB: round1(bytes / (1 << 30))})
	}
	return out
}

// defaultLendLimitGB picks a sensible "biggest model to lend" for this machine,
// leaving room to keep using the computer for lighter things.
func defaultLendLimitGB(s SysInfo) float64 {
	if s.OS == "macOS" && s.RAMGB > 0 {
		return float64(int(s.RAMGB * 0.6))
	}
	for _, g := range s.GPUs {
		if g.VRAMGB > 0 && s.OS != "macOS" {
			return float64(int(g.VRAMGB * 0.95))
		}
	}
	return 0 // unknown: no limit
}

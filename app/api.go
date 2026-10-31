package main

// The local interface's API. It only listens on 127.0.0.1, and every change
// needs an X-Chimera header so other websites can't poke at it.

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io/fs"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

func (a *App) routes() http.Handler {
	mux := http.NewServeMux()
	static, _ := fs.Sub(webFS, "web")
	files := http.FileServer(http.FS(static))
	mux.Handle("GET /", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-cache")
		files.ServeHTTP(w, r)
	}))

	mux.HandleFunc("GET /api/ping", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]string{"app": "chimera", "version": Version})
	})
	mux.HandleFunc("GET /api/state", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, a.buildState())
	})
	mux.HandleFunc("GET /api/stream", a.handleStream)

	mux.HandleFunc("POST /api/connect", func(w http.ResponseWriter, r *http.Request) {
		if err := a.node.Connect(); err != nil {
			writeErr(w, 409, err.Error())
			return
		}
		writeJSON(w, 200, map[string]bool{"ok": true})
	})
	mux.HandleFunc("POST /api/disconnect", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Mode string `json:"mode"`
		}
		_ = readJSON(r, &req, 4096)
		if req.Mode != "now" {
			req.Mode = "finish"
		}
		a.node.Disconnect(req.Mode)
		writeJSON(w, 200, map[string]bool{"ok": true})
	})

	mux.HandleFunc("POST /api/ollama/start", func(w http.ResponseWriter, r *http.Request) {
		if err := a.ollama.Start(30 * time.Second); err != nil {
			writeErr(w, 409, err.Error())
			return
		}
		writeJSON(w, 200, map[string]bool{"ok": true})
	})
	mux.HandleFunc("POST /api/ollama/pull", a.handlePull)
	mux.HandleFunc("POST /api/helper/install", a.handleHelperInstall) // get Hydra 1.0 from the network's host

	mux.HandleFunc("POST /api/settings", a.handleSettings)

	mux.HandleFunc("POST /api/network/join", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Address    string `json:"address"`
			Invite     string `json:"invite"`
			Owner      string `json:"owner"`
			DeviceName string `json:"device_name"`
		}
		if err := readJSON(r, &req, 1<<16); err != nil {
			writeErr(w, 400, "bad request")
			return
		}
		if a.hostingView().Enabled {
			a.stopHosting()
		}
		if err := a.joinNetwork(req.Address, req.Invite, req.Owner, req.DeviceName); err != nil {
			writeErr(w, 409, err.Error())
			return
		}
		writeJSON(w, 200, map[string]bool{"ok": true})
	})
	mux.HandleFunc("POST /api/network/leave", func(w http.ResponseWriter, r *http.Request) {
		a.leaveNetwork()
		writeJSON(w, 200, map[string]bool{"ok": true})
	})
	mux.HandleFunc("POST /api/network/host", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Enabled    bool   `json:"enabled"`
			Owner      string `json:"owner"`
			DeviceName string `json:"device_name"`
			Name       string `json:"name"`
		}
		if err := readJSON(r, &req, 1<<16); err != nil {
			writeErr(w, 400, "bad request")
			return
		}
		if !req.Enabled {
			a.stopHosting()
			writeJSON(w, 200, a.hostingView())
			return
		}
		if o := strings.TrimSpace(req.Owner); o != "" {
			a.updateConfig(func(c *Config) { c.Owner = o })
		}
		if d := strings.TrimSpace(req.DeviceName); d != "" {
			a.updateConfig(func(c *Config) { c.DeviceName = d })
		}
		if err := a.startHosting(); err != nil {
			writeErr(w, 409, err.Error())
			return
		}
		if n := strings.TrimSpace(req.Name); n != "" {
			a.hubMu.Lock()
			if a.hub != nil {
				a.hub.SetName(n)
			}
			a.hubMu.Unlock()
		}
		writeJSON(w, 200, a.hostingView())
	})
	mux.HandleFunc("POST /api/network/new-invite", func(w http.ResponseWriter, r *http.Request) {
		a.hubMu.Lock()
		h := a.hub
		a.hubMu.Unlock()
		if h == nil {
			writeErr(w, 409, "you're not hosting")
			return
		}
		inv := h.NewInvite()
		a.updateConfig(func(c *Config) { c.Invite = inv })
		writeJSON(w, 200, a.hostingView())
	})
	mux.HandleFunc("POST /api/network/test", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Address string `json:"address"`
		}
		_ = readJSON(r, &req, 4096)
		c, err := NewHubClient(req.Address, "")
		if err != nil {
			writeErr(w, 400, err.Error())
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 6*time.Second)
		defer cancel()
		name, err := c.Ping(ctx)
		if err != nil {
			writeErr(w, 409, friendlyNetErr(err, req.Address))
			return
		}
		writeJSON(w, 200, map[string]string{"name": name})
	})

	mux.HandleFunc("GET /api/sessions", func(w http.ResponseWriter, r *http.Request) {
		list := a.sessions.List()
		if list == nil {
			list = []SessionSummary{}
		}
		writeJSON(w, 200, list)
	})
	mux.HandleFunc("GET /api/sessions/{id}", a.handleGetSession)
	mux.HandleFunc("DELETE /api/sessions/{id}", func(w http.ResponseWriter, r *http.Request) {
		if err := a.sessions.Delete(r.PathValue("id")); err != nil {
			writeErr(w, 404, "no such chat")
			return
		}
		writeJSON(w, 200, map[string]bool{"ok": true})
	})
	mux.HandleFunc("POST /api/chat", a.handleChat)
	mux.HandleFunc("GET /api/chat/{gen}/stream", a.handleChatStream)
	mux.HandleFunc("POST /api/chat/{gen}/cancel", func(w http.ResponseWriter, r *http.Request) {
		if err := a.gens.Cancel(r.PathValue("gen")); err != nil {
			writeErr(w, 404, err.Error())
			return
		}
		writeJSON(w, 200, map[string]bool{"ok": true})
	})

	a.moreRoutes(mux)

	mux.HandleFunc("POST /api/open-folder", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Which string `json:"which"`
			ID    string `json:"id"`
		}
		_ = readJSON(r, &req, 1<<10)
		dir := a.dataDir
		switch req.Which {
		case "plugins": // where plugins get installed
			dir = filepath.Join(a.dataDir, "plugins")
			_ = os.MkdirAll(dir, 0o755)
		case "plugin", "head-try": // one Head's folder, or what trying it made
			p := a.tools.Plugin(req.ID)
			if p == nil {
				writeErr(w, 404, "That Head isn't installed on this computer.")
				return
			}
			dir = p.Dir
			if req.Which == "head-try" {
				dir = filepath.Join(a.dataDir, "head-tries", p.Manifest.ID)
			}
			if !fileExists(dir) {
				writeErr(w, 404, "Nothing there yet.")
				return
			}
		}
		openFolder(dir)
		writeJSON(w, 200, map[string]bool{"ok": true})
	})
	a.fileRoutes(mux)
	a.headRoutes(mux)
	mux.HandleFunc("POST /api/quit", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]bool{"ok": true})
		go func() {
			time.Sleep(200 * time.Millisecond)
			a.Quit()
		}()
	})
	return a.guard(mux)
}

func (a *App) guard(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		host, _, err := net.SplitHostPort(r.Host)
		if err != nil {
			host = r.Host
		}
		if host != "127.0.0.1" && host != "localhost" && host != "::1" && host != "[::1]" {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		if strings.HasPrefix(r.URL.Path, "/api/") && r.Method != http.MethodGet && r.Header.Get("X-Chimera") != "1" {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (a *App) handleStream(w http.ResponseWriter, r *http.Request) {
	fl, ok := w.(http.Flusher)
	if !ok {
		writeErr(w, 500, "streaming unsupported")
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.WriteHeader(200)
	ch := a.subscribe()
	defer a.unsubscribe(ch)
	var last []byte
	lastSent := time.Now()
	send := func(force bool) {
		b, err := json.Marshal(a.buildState())
		if err != nil {
			return
		}
		if force || !bytes.Equal(b, last) {
			last = b
			lastSent = time.Now()
			fmt.Fprintf(w, "event: state\ndata: %s\n\n", b)
			fl.Flush()
		} else if time.Since(lastSent) > 15*time.Second {
			lastSent = time.Now()
			fmt.Fprint(w, ": ping\n\n")
			fl.Flush()
		}
	}
	send(true)
	tick := time.NewTicker(1500 * time.Millisecond)
	defer tick.Stop()
	for {
		select {
		case <-ch:
			time.Sleep(60 * time.Millisecond) // gather bursts of changes
			select {
			case <-ch:
			default:
			}
			send(false)
		case <-tick.C:
			send(false)
		case <-r.Context().Done():
			return
		case <-a.quit:
			return
		}
	}
}

func (a *App) handleSettings(w http.ResponseWriter, r *http.Request) {
	var req struct {
		DeviceName             *string   `json:"device_name"`
		Owner                  *string   `json:"owner"`
		OllamaURL              *string   `json:"ollama_url"`
		MaxSlots               *int      `json:"max_slots"`
		MaxModelGB             *float64  `json:"max_model_gb"`
		Unshared               *[]string `json:"unshared"`
		AutoStartOllama        *bool     `json:"auto_start_ollama"`
		FreeMemoryOnDisconnect *bool     `json:"free_memory_on_disconnect"`
		ConnectOnLaunch        *bool     `json:"connect_on_launch"`
		AppWindow              *bool     `json:"app_window"`
		HostPort               *int      `json:"host_port"`
		SetupDone              *bool     `json:"setup_done"`
		RunTests               *bool     `json:"run_tests"`
		CheckResults           *bool     `json:"check_results"`
		AutoHelp               *bool     `json:"auto_help"`
		AutoJoin               *bool     `json:"auto_join"`
		PoolAddr               *string   `json:"pool_addr"`
		LendPlugins            *bool     `json:"lend_plugins"`
		UnsandboxedHeads       *bool     `json:"unsandboxed_heads"`
	}
	if err := readJSON(r, &req, 1<<16); err != nil {
		writeErr(w, 400, "bad request")
		return
	}
	cfg := a.config()
	if req.Owner != nil && cfg.Joined() && !sameOwner(*req.Owner, cfg.Owner) && strings.TrimSpace(*req.Owner) != "" {
		writeErr(w, 409, "Your name is tied to your credits in this network. Leave and rejoin to change it.")
		return
	}
	newURL := ""
	a.updateConfig(func(c *Config) {
		if req.DeviceName != nil && strings.TrimSpace(*req.DeviceName) != "" {
			c.DeviceName = strings.TrimSpace(*req.DeviceName)
		}
		if req.Owner != nil {
			c.Owner = strings.TrimSpace(*req.Owner)
		}
		if req.OllamaURL != nil {
			c.OllamaURL = strings.TrimSpace(*req.OllamaURL)
			newURL = c.OllamaURL
		}
		if req.MaxSlots != nil {
			c.MaxSlots = clampInt(*req.MaxSlots, 1, 8)
		}
		if req.MaxModelGB != nil && *req.MaxModelGB >= 0 {
			c.MaxModelGB = *req.MaxModelGB
		}
		if req.Unshared != nil {
			c.Unshared = append([]string{}, (*req.Unshared)...)
		}
		if req.AutoStartOllama != nil {
			c.AutoStartOllama = *req.AutoStartOllama
		}
		if req.FreeMemoryOnDisconnect != nil {
			c.FreeMemoryOnDisconnect = *req.FreeMemoryOnDisconnect
		}
		if req.ConnectOnLaunch != nil {
			c.ConnectOnLaunch = *req.ConnectOnLaunch
		}
		if req.AppWindow != nil {
			c.AppWindow = *req.AppWindow
		}
		if req.HostPort != nil && *req.HostPort > 1024 && *req.HostPort < 65536 {
			c.HostPort = *req.HostPort
		}
		if req.SetupDone != nil {
			c.SetupDone = *req.SetupDone
		}
		if req.RunTests != nil {
			c.RunTests = *req.RunTests
		}
		if req.CheckResults != nil {
			c.CheckResults = *req.CheckResults
		}
		if req.AutoHelp != nil {
			c.AutoHelp = *req.AutoHelp
		}
		if req.AutoJoin != nil {
			c.AutoJoin = *req.AutoJoin
		}
		if req.PoolAddr != nil {
			c.PoolAddr = strings.TrimSpace(*req.PoolAddr)
		}
		if req.UnsandboxedHeads != nil {
			c.UnsandboxedHeads = *req.UnsandboxedHeads
		}
		if req.LendPlugins != nil {
			c.LendPlugins = *req.LendPlugins
		}
	})
	if req.AutoJoin != nil {
		a.hubMu.Lock()
		if a.hub != nil {
			a.hub.SetAutoJoin(*req.AutoJoin)
		}
		a.hubMu.Unlock()
	}
	if req.OllamaURL != nil {
		a.ollama.SetURL(newURL)
	}
	a.node.clearLendError()
	signal1(a.node.beatNow)
	writeJSON(w, 200, a.buildState().Settings)
}

func (a *App) handlePull(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Model string `json:"model"`
	}
	if err := readJSON(r, &req, 4096); err != nil || strings.TrimSpace(req.Model) == "" {
		writeErr(w, 400, "which model?")
		return
	}
	if !a.ollama.Running() {
		writeErr(w, 409, "Ollama isn't running")
		return
	}
	fl, _ := w.(http.Flusher)
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.WriteHeader(200)
	last := time.Time{}
	err := a.ollama.Client().Pull(r.Context(), strings.TrimSpace(req.Model), func(p PullProgress) {
		if time.Since(last) < 200*time.Millisecond && p.Status != "success" {
			return
		}
		last = time.Now()
		writeSSE(w, "", map[string]any{"type": "progress", "status": p.Status, "completed": p.Completed, "total": p.Total})
		if fl != nil {
			fl.Flush()
		}
	})
	if err != nil {
		writeSSE(w, "", map[string]any{"type": "error", "error": err.Error()})
	} else {
		writeSSE(w, "", map[string]any{"type": "done"})
		log.Printf("Pulled %s", req.Model)
	}
	if fl != nil {
		fl.Flush()
	}
	a.ollama.Refresh()
}

func (a *App) handleGetSession(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	sess, err := a.sessions.Get(id)
	if err != nil {
		writeErr(w, 404, "no such chat")
		return
	}
	alive := func(m *SessionMessage) bool {
		return (m.GenID != "" && a.gens.Get(m.GenID) != nil) || (m.TaskID != "" && a.tasks.Get(m.TaskID) != nil)
	}
	stale := false
	for i := range sess.Messages {
		m := &sess.Messages[i]
		if m.Status != "pending" {
			continue
		}
		if gen := a.gens.Get(m.GenID); m.GenID != "" && gen != nil {
			content, thinking, meta := gen.Snapshot()
			m.Content, m.Thinking = content, thinking
			if meta.Model != "" {
				m.Model, m.Device, m.Owner = meta.Model, meta.DeviceName, meta.Owner
			}
		} else if run := a.tasks.Get(m.TaskID); m.TaskID != "" && run != nil {
			run.mu.Lock()
			rec := run.snapshot()
			m.Content = run.final.String()
			run.mu.Unlock()
			m.Task = &rec
		} else {
			m.Status, m.Error = "error", "Interrupted (Chimera was closed while this was being written)."
			interruptChecks(m.Task)
			stale = true
		}
	}
	if stale {
		_, _ = a.sessions.Update(id, func(s *Session) {
			for i := range s.Messages {
				if m := &s.Messages[i]; m.Status == "pending" && !alive(m) {
					m.Status = "error"
					m.Error = "Interrupted (Chimera was closed while this was being written)."
					if m.Task != nil && m.Task.Phase != "done" {
						m.Task.Phase = "error"
					}
					interruptChecks(m.Task)
				}
			}
		})
	}
	writeJSON(w, 200, sess)
}

func (a *App) handleChat(w http.ResponseWriter, r *http.Request) {
	var req chatReq
	if err := readJSON(r, &req, chatImageMax*4/3+(4<<20)); err != nil {
		writeErr(w, 400, "bad request")
		return
	}
	gen, err := a.gens.Start(req)
	if err != nil {
		writeErr(w, 409, err.Error())
		return
	}
	a.streamGen(w, r, gen)
}

func (a *App) handleChatStream(w http.ResponseWriter, r *http.Request) {
	gen := a.gens.Get(r.PathValue("gen"))
	if gen == nil {
		writeErr(w, 404, "that reply already finished")
		return
	}
	a.streamGen(w, r, gen)
}

func (a *App) streamGen(w http.ResponseWriter, r *http.Request, gen *generation) {
	fl, ok := w.(http.Flusher)
	if !ok {
		writeErr(w, 500, "streaming unsupported")
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.WriteHeader(200)
	replay, ch := gen.Subscribe()
	for _, ev := range replay {
		writeSSE(w, "", ev)
	}
	fl.Flush()
	if ch == nil {
		return
	}
	defer gen.Unsubscribe(ch)
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
		case <-ping.C:
			fmt.Fprint(w, ": ping\n\n")
			fl.Flush()
		case <-r.Context().Done():
			return
		}
	}
}

func openFolder(p string) {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		cmd = exec.Command("open", p)
	case "windows":
		cmd = exec.Command("explorer", p)
	default:
		cmd = exec.Command("xdg-open", p)
	}
	_ = cmd.Start()
}

var _ = os.Getenv

// fileRoutes serves the files kept with chats.
func (a *App) fileRoutes(mux *http.ServeMux) {
	// Files kept with a chat: pictures sent with a message, or made by a plugin.
	mux.HandleFunc("GET /api/files/{session}/{file}", func(w http.ResponseWriter, r *http.Request) {
		p := a.sessions.FilePath(r.PathValue("session"), r.PathValue("file"))
		data, err := os.ReadFile(p)
		if p == "" || err != nil {
			writeErr(w, 404, "no such file")
			return
		}
		// These bytes may come from another computer's plugin: only raster images are shown
		// inline, anything else downloads, and nothing can run as a page on this origin.
		mime := http.DetectContentType(data)
		switch mime {
		case "image/png", "image/jpeg", "image/webp", "image/gif":
		default:
			mime = "application/octet-stream"
			w.Header().Set("Content-Disposition", "attachment")
		}
		w.Header().Set("Content-Type", mime)
		w.Header().Set("Content-Security-Policy", "default-src 'none'; sandbox")
		w.Header().Set("Cache-Control", "private, max-age=86400")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		_, _ = w.Write(data)
	})
}

package main

// The chat sidebar's API (rename, groups, a chat's folder, delete, search), the
// previews of pages written in chats, and this computer's engines.

import (
	"context"
	"errors"
	"fmt"
	"log"
	"mime"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"
)

func (a *App) chatRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/chat-groups", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, a.sessions.Groups())
	})
	mux.HandleFunc("POST /api/chat-groups", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Name string   `json:"name"`
			Move []string `json:"move"` // chats to put in it straight away
		}
		if err := readJSON(r, &req, 1<<16); err != nil {
			writeErr(w, 400, "bad request")
			return
		}
		g, err := a.sessions.AddGroup(req.Name)
		if err != nil {
			writeErr(w, 400, err.Error())
			return
		}
		for _, id := range req.Move {
			_, _ = a.sessions.Edit(id, func(s *Session) { s.Group = g.ID })
		}
		writeJSON(w, 200, g)
	})
	mux.HandleFunc("PATCH /api/chat-groups/{id}", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Name      *string `json:"name"`
			Collapsed *bool   `json:"collapsed"`
			At        *int    `json:"at"`
		}
		if err := readJSON(r, &req, 1<<12); err != nil {
			writeErr(w, 400, "bad request")
			return
		}
		g, err := a.sessions.UpdateGroup(r.PathValue("id"), req.Name, req.Collapsed, req.At)
		if errors.Is(err, os.ErrNotExist) {
			writeErr(w, 404, "no such group")
			return
		} else if err != nil {
			writeErr(w, 400, err.Error())
			return
		}
		writeJSON(w, 200, g)
	})
	mux.HandleFunc("DELETE /api/chat-groups/{id}", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		deleted := 0
		if r.URL.Query().Get("chats") == "delete" { // the group and every chat in it
			for _, s := range a.sessions.List() {
				if s.Group == id && a.deleteChat(s.ID) == nil {
					deleted++
				}
			}
		}
		if err := a.sessions.DeleteGroup(id); err != nil {
			writeErr(w, 404, "no such group")
			return
		}
		writeJSON(w, 200, map[string]any{"ok": true, "deleted": deleted})
	})

	mux.HandleFunc("GET /api/sessions/search", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, a.sessions.Search(r.URL.Query().Get("q")))
	})
	mux.HandleFunc("PATCH /api/sessions/{id}", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Title  *string `json:"title"`
			Group  *string `json:"group"`
			Folder *string `json:"folder"`
		}
		if err := readJSON(r, &req, 1<<14); err != nil {
			writeErr(w, 400, "bad request")
			return
		}
		folder := ""
		if req.Folder != nil && strings.TrimSpace(*req.Folder) != "" {
			f, err := cleanChatFolder(*req.Folder)
			if err != nil {
				writeErr(w, 400, err.Error())
				return
			}
			folder = f
		}
		if req.Group != nil && *req.Group != "" && !a.sessions.HasGroup(*req.Group) {
			writeErr(w, 404, "no such group")
			return
		}
		sess, err := a.sessions.Edit(r.PathValue("id"), func(s *Session) {
			if req.Title != nil {
				if t := strings.Join(strings.Fields(*req.Title), " "); t != "" {
					if rs := []rune(t); len(rs) > 120 {
						t = string(rs[:120])
					}
					s.Title, s.Named = t, true
				}
			}
			if req.Group != nil {
				s.Group = *req.Group
			}
			if req.Folder != nil {
				s.Folder = folder
			}
		})
		if err != nil {
			writeErr(w, 404, "no such chat")
			return
		}
		writeJSON(w, 200, summaryOf(sess))
	})
	mux.HandleFunc("POST /api/sessions/delete", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			IDs []string `json:"ids"`
		}
		if err := readJSON(r, &req, 1<<18); err != nil {
			writeErr(w, 400, "bad request")
			return
		}
		n := 0
		for _, id := range req.IDs {
			if a.deleteChat(id) == nil {
				n++
			}
		}
		writeJSON(w, 200, map[string]int{"deleted": n})
	})
	mux.HandleFunc("POST /api/sessions/{id}/save-page", a.handleSavePage)
	mux.HandleFunc("POST /api/sessions/{id}/open-page", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Name string `json:"name"`
		}
		_ = readJSON(r, &req, 1<<12)
		sess, err := a.sessions.Get(r.PathValue("id"))
		if err != nil || sess.Folder == "" {
			writeErr(w, 404, "This chat has no folder.")
			return
		}
		target := sess.Folder
		if req.Name != "" {
			name, err := pageName(req.Name)
			if err != nil {
				writeErr(w, 400, err.Error())
				return
			}
			target = filepath.Join(sess.Folder, name)
			if !fileExists(target) {
				writeErr(w, 404, "There's no "+name+" in the chat's folder yet.")
				return
			}
		}
		openFolder(target) // `open` shows a folder in the Finder and opens a page in the browser
		writeJSON(w, 200, map[string]bool{"ok": true})
	})
	mux.HandleFunc("POST /api/pick-folder", func(w http.ResponseWriter, r *http.Request) {
		if runtime.GOOS != "darwin" {
			writeErr(w, 501, "Type the folder's path instead.")
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 5*time.Minute)
		defer cancel()
		out, err := exec.CommandContext(ctx, "osascript", "-e",
			`POSIX path of (choose folder with prompt "A folder for this chat's pages: they load their pictures and files from it")`).Output()
		if err != nil {
			writeJSON(w, 200, map[string]string{"path": ""}) // cancelled
			return
		}
		writeJSON(w, 200, map[string]string{"path": strings.TrimRight(strings.TrimSpace(string(out)), "/")})
	})

	// Previews of pages in chats. The page and the files next to it are served from
	// a path only this window knows, always sandboxed (an origin of its own), so a
	// page a model wrote can't use Chimera's API, even when opened in its own tab.
	mux.HandleFunc("POST /api/preview", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			SessionID string `json:"session_id"`
			HTML      string `json:"html"`
		}
		if err := readJSON(r, &req, previewMax+(1<<16)); err != nil || strings.TrimSpace(req.HTML) == "" {
			writeErr(w, 400, "no page")
			return
		}
		folder := ""
		if sess, err := a.sessions.Get(req.SessionID); err == nil {
			folder = sess.Folder
		}
		tok := a.previews.add(req.HTML, folder)
		writeJSON(w, 200, map[string]any{"url": "/preview/" + tok + "/", "folder": folder != ""})
	})
	mux.HandleFunc("GET /preview/{token}", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "/preview/"+r.PathValue("token")+"/", http.StatusFound)
	})
	mux.HandleFunc("GET /preview/{token}/{path...}", a.servePreview)

	mux.HandleFunc("POST /api/engines/{id}/start", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		go func() {
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			if err := a.engines.Start(ctx, id, nil); err != nil {
				log.Printf("engines: %s: %v", id, err)
			}
		}()
		writeJSON(w, 200, map[string]bool{"ok": true})
	})
	mux.HandleFunc("POST /api/engines/{id}/stop", func(w http.ResponseWriter, r *http.Request) {
		a.engines.Stop(r.PathValue("id"))
		writeJSON(w, 200, map[string]bool{"ok": true})
	})
}

// deleteChat stops anything still being written in a chat, then deletes it.
func (a *App) deleteChat(id string) error {
	sess, err := a.sessions.Get(id)
	if err != nil {
		return err
	}
	for _, m := range sess.Messages {
		if m.Status != "pending" {
			continue
		}
		if m.GenID != "" && a.gens.Get(m.GenID) != nil {
			_ = a.gens.Cancel(m.GenID)
		}
		if m.TaskID != "" && a.tasks.Get(m.TaskID) != nil {
			_ = a.tasks.Cancel(m.TaskID)
		}
	}
	return a.sessions.Delete(id)
}

// pageName checks a page's file name for a chat's folder.
func pageName(name string) (string, error) {
	name = cleanFileName(name)
	low := strings.ToLower(name)
	if !strings.HasSuffix(low, ".html") && !strings.HasSuffix(low, ".htm") {
		name += ".html"
	}
	if strings.HasPrefix(name, ".") {
		return "", errors.New("pick another name")
	}
	return name, nil
}

func (a *App) handleSavePage(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Name      string `json:"name"`
		HTML      string `json:"html"`
		Overwrite bool   `json:"overwrite"`
	}
	if err := readJSON(r, &req, previewMax+(1<<16)); err != nil || strings.TrimSpace(req.HTML) == "" {
		writeErr(w, 400, "no page")
		return
	}
	sess, err := a.sessions.Get(r.PathValue("id"))
	if err != nil {
		writeErr(w, 404, "no such chat")
		return
	}
	if sess.Folder == "" {
		writeErr(w, 409, "Pick a folder for this chat first.")
		return
	}
	if req.Name == "" {
		req.Name = "index.html"
	}
	name, err := pageName(req.Name)
	if err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	target := filepath.Join(sess.Folder, name)
	if fileExists(target) && !req.Overwrite {
		writeJSON(w, 409, map[string]any{"error": name + " is already in that folder.", "exists": true, "name": name})
		return
	}
	if err := writeFileAtomic(target, []byte(req.HTML)); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]string{"path": target, "name": name})
}

// ---------- page previews ----------

const previewMax = 16 << 20

type previewPage struct {
	html   string
	folder string
	at     time.Time
}

type previewStore struct {
	mu    sync.Mutex
	pages map[string]*previewPage
}

func (p *previewStore) add(html, folder string) string {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.pages == nil {
		p.pages = map[string]*previewPage{}
	}
	// Keep the newest 40 (a few big pages at most), and none older than a day.
	for len(p.pages) >= 40 {
		oldest := ""
		for k, v := range p.pages {
			if oldest == "" || v.at.Before(p.pages[oldest].at) {
				oldest = k
			}
		}
		delete(p.pages, oldest)
	}
	for k, v := range p.pages {
		if time.Since(v.at) > 24*time.Hour {
			delete(p.pages, k)
		}
	}
	tok := randomID(16)
	p.pages[tok] = &previewPage{html: html, folder: folder, at: time.Now()}
	return tok
}

func (p *previewStore) get(tok string) *previewPage {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.pages[tok]
}

// previewCSP makes a preview's page a sandbox: scripts run, but on an origin of
// their own, with no reach into Chimera or its storage.
const previewCSP = "sandbox allow-scripts allow-forms allow-popups allow-modals allow-pointer-lock allow-downloads"

func (a *App) servePreview(w http.ResponseWriter, r *http.Request) {
	pg := a.previews.get(r.PathValue("token"))
	if pg == nil {
		http.Error(w, "This preview has expired: show it again from the chat.", http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Security-Policy", previewCSP)
	w.Header().Set("Referrer-Policy", "no-referrer")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Access-Control-Allow-Origin", "*") // the sandboxed page's own fetches (its origin is "null")
	rel := r.PathValue("path")
	if rel == "" || rel == "index.html" {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Header().Set("Cache-Control", "no-store")
		_, _ = w.Write([]byte(pg.html))
		return
	}
	if pg.folder == "" {
		http.Error(w, "This chat has no folder, so the page's files can't be found.", http.StatusNotFound)
		return
	}
	full, err := insideFolder(pg.folder, rel)
	if err != nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	f, err := os.Open(full)
	if err != nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil || st.IsDir() {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	if ct := mime.TypeByExtension(strings.ToLower(filepath.Ext(full))); ct != "" {
		w.Header().Set("Content-Type", ct)
	} else {
		switch strings.ToLower(filepath.Ext(full)) {
		case ".obj", ".mtl", ".gltf":
			w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		case ".glb":
			w.Header().Set("Content-Type", "model/gltf-binary")
		}
	}
	w.Header().Set("Cache-Control", "private, max-age=300")
	http.ServeContent(w, r, st.Name(), st.ModTime(), f)
}

// insideFolder joins a page's relative path to its folder, and refuses anything
// that would leave the folder (also through a link) or names a hidden file.
func insideFolder(folder, rel string) (string, error) {
	rel = filepath.FromSlash(strings.TrimPrefix(rel, "/"))
	for _, part := range strings.Split(filepath.ToSlash(rel), "/") {
		if part == ".." || strings.HasPrefix(part, ".") {
			return "", fmt.Errorf("refused")
		}
	}
	full := filepath.Join(folder, rel)
	root, err := filepath.EvalSymlinks(folder)
	if err != nil {
		return "", err
	}
	real, err := filepath.EvalSymlinks(full)
	if err != nil {
		return "", err
	}
	if real != root && !strings.HasPrefix(real, root+string(filepath.Separator)) {
		return "", fmt.Errorf("refused")
	}
	return real, nil
}

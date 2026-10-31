package main

// Getting the helper model (Hydra 1.0) onto every computer from inside
// Chimera: the host hands out its own copy. The host finds the model file its
// Ollama keeps for hydra:1.0 and streams it to computers in its network that
// ask; each of those pushes the file into its own Ollama (/api/blobs) and makes
// the model there with the host's template, parameters and licence
// (/api/create). Nothing is downloaded from the internet.

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// HelperOffer is the helper model a host can hand out, with what a computer
// needs to make it in its own Ollama.
type HelperOffer struct {
	Model      string         `json:"model"`
	Size       int64          `json:"size"`   // bytes of the model file
	Digest     string         `json:"digest"` // "sha256:<hex>" of the model file
	Template   string         `json:"template,omitempty"`
	Parameters map[string]any `json:"parameters,omitempty"`
	License    string         `json:"license,omitempty"`
	System     string         `json:"system,omitempty"`

	path string // the file on the host
}

// HelperSummary is what the network snapshot says about the offer.
type HelperSummary struct {
	Model string `json:"model"`
	Size  int64  `json:"size"`
}

// helperSendsMax is how many computers the host sends the model to at once.
const helperSendsMax = 2

// helperStall is how long a copy may make no progress, on either end, before
// it's given up (a computer gone to sleep shouldn't hold a send for long). A
// variable so tests can shorten it.
var helperStall = 60 * time.Second

var digestRe = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)

// ---------- on the host ----------

type helperShare struct {
	mu      sync.Mutex
	key     string // the local hydra:1.0 it was built for (digest and size)
	offer   *HelperOffer
	busy    bool
	retryAt time.Time // after a failed build

	installing bool // this computer is getting the helper from its host
}

// sharedHelper is the helper model this computer can hand out as a host, or
// nil. The hub asks on every heartbeat, so it answers from a cache and
// rebuilds the offer in the background when the local model changes.
func (a *App) sharedHelper() *HelperOffer {
	key := ""
	for _, m := range a.ollama.State().Models {
		if normModel(m.Name) == helperModel {
			key = fmt.Sprintf("%s|%d", m.Digest, m.SizeBytes)
		}
	}
	s := &a.helper
	s.mu.Lock()
	defer s.mu.Unlock()
	if key == "" {
		s.key, s.offer = "", nil
		return nil
	}
	stale := key != s.key || (s.offer == nil && time.Now().After(s.retryAt))
	if stale && !s.busy {
		s.busy = true
		go a.buildHelperOffer(key)
	}
	if key != s.key {
		return nil
	}
	return s.offer
}

func (a *App) buildHelperOffer(key string) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	off, err := helperOfferFrom(ctx, a.ollama.Client(), helperModel)
	s := &a.helper
	s.mu.Lock()
	defer s.mu.Unlock()
	s.busy, s.key, s.offer = false, key, off
	if err != nil {
		s.offer, s.retryAt = nil, time.Now().Add(2*time.Minute)
		log.Printf("helper: can't share %s with the network: %v", helperModel, err)
		return
	}
	log.Printf("helper: sharing %s with the network (%.1f GB)", helperModel, float64(off.Size)/1e9)
}

// helperOfferFrom builds the offer for model from this computer's Ollama.
func helperOfferFrom(ctx context.Context, oc *OllamaClient, model string) (*HelperOffer, error) {
	sf, err := oc.ShowFull(ctx, model)
	if err != nil {
		return nil, err
	}
	path, digest, err := findModelFile(sf.Modelfile, model)
	if err != nil {
		return nil, err
	}
	fi, err := os.Stat(path)
	if err != nil {
		return nil, err
	}
	return &HelperOffer{Model: model, Size: fi.Size(), Digest: digest, Template: sf.Template,
		Parameters: parseOllamaParameters(sf.Parameters), License: sf.License, System: sf.System, path: path}, nil
}

// findModelFile finds the model file Ollama keeps for a model and its digest:
// from the FROM line of the Modelfile /api/show gives (Ollama's own blob), or
// else from the model's manifest in Ollama's models folder.
func findModelFile(modelfile, model string) (path, digest string, err error) {
	for _, line := range strings.Split(modelfile, "\n") {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(strings.ToUpper(line), "FROM ") {
			continue
		}
		p := strings.TrimSpace(line[5:])
		if u, err := strconv.Unquote(p); err == nil {
			p = u
		}
		if fi, err := os.Stat(p); err == nil && fi.Mode().IsRegular() {
			if d := blobDigest(p); d != "" {
				return p, d, nil
			}
			d, err := fileDigest(p)
			return p, d, err
		}
		break
	}
	for _, dir := range ollamaModelDirs() {
		if p, d := manifestBlob(dir, model); p != "" {
			return p, d, nil
		}
	}
	return "", "", errors.New("couldn't find the model file Ollama keeps for " + model)
}

// blobDigest reads a digest from an Ollama blob's file name (sha256-<hex>).
func blobDigest(path string) string {
	name := filepath.Base(path)
	if h, ok := strings.CutPrefix(name, "sha256-"); ok {
		if d := "sha256:" + h; digestRe.MatchString(d) {
			return d
		}
	}
	return ""
}

func fileDigest(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return "sha256:" + hex.EncodeToString(h.Sum(nil)), nil
}

func ollamaModelDirs() []string {
	var dirs []string
	if d := os.Getenv("OLLAMA_MODELS"); d != "" {
		dirs = append(dirs, d)
	}
	if home, err := os.UserHomeDir(); err == nil {
		dirs = append(dirs, filepath.Join(home, ".ollama", "models"))
	}
	return append(dirs, "/usr/share/ollama/.ollama/models")
}

// manifestBlob finds a model's weights through its manifest, in Ollama's older
// (manifests/registry.ollama.ai) and newer (manifests-v2/ollama.com) layouts.
func manifestBlob(dir, model string) (path, digest string) {
	name, tag, _ := strings.Cut(normModel(model), ":")
	if strings.Contains(name, "/") || strings.ContainsAny(tag, `/\`) {
		return "", ""
	}
	for _, m := range []string{
		filepath.Join(dir, "manifests-v2", "ollama.com", "library", name, tag),
		filepath.Join(dir, "manifests", "registry.ollama.ai", "library", name, tag),
	} {
		b, err := os.ReadFile(m)
		if err != nil {
			continue
		}
		var man struct {
			Layers []struct {
				MediaType string `json:"mediaType"`
				Digest    string `json:"digest"`
			} `json:"layers"`
		}
		if json.Unmarshal(b, &man) != nil {
			continue
		}
		for _, l := range man.Layers {
			if l.MediaType == "application/vnd.ollama.image.model" && digestRe.MatchString(l.Digest) {
				p := filepath.Join(dir, "blobs", strings.Replace(l.Digest, ":", "-", 1))
				if fi, err := os.Stat(p); err == nil && fi.Mode().IsRegular() {
					return p, l.Digest
				}
			}
		}
	}
	return "", ""
}

// parseOllamaParameters turns /api/show's parameters ("name value" lines,
// values in Go syntax) into what /api/create takes: stop as a list, numbers as
// numbers.
func parseOllamaParameters(s string) map[string]any {
	out := map[string]any{}
	for _, line := range strings.Split(s, "\n") {
		key, val, ok := strings.Cut(strings.TrimSpace(line), " ")
		if !ok || key == "" {
			continue
		}
		val = strings.TrimSpace(val)
		var v any = val
		if strings.HasPrefix(val, `"`) {
			if u, err := strconv.Unquote(val); err == nil {
				v = u
			}
		} else if n, err := strconv.ParseInt(val, 10, 64); err == nil {
			v = n
		} else if f, err := strconv.ParseFloat(val, 64); err == nil {
			v = f
		} else if b, err := strconv.ParseBool(val); err == nil {
			v = b
		}
		if key == "stop" {
			list, _ := out["stop"].([]string)
			out["stop"] = append(list, fmt.Sprint(v))
			continue
		}
		out[key] = v
	}
	return out
}

// ---------- the hub's side ----------

// SetHelperSource tells the hub where to get the helper model it hands out.
func (h *Hub) SetHelperSource(fn func() *HelperOffer) {
	h.mu.Lock()
	h.helperSource = fn
	h.mu.Unlock()
}

func (h *Hub) helperOffer() *HelperOffer {
	h.mu.Lock()
	fn := h.helperSource
	h.mu.Unlock()
	if fn == nil {
		return nil
	}
	return fn()
}

func (h *Hub) helperSummary() *HelperSummary {
	if off := h.helperOffer(); off != nil {
		return &HelperSummary{Model: off.Model, Size: off.Size}
	}
	return nil
}

func (h *Hub) handleHelper(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	off := h.helperOffer()
	if off == nil {
		writeErr(w, 404, "This network's host doesn't have "+helperModel+" to share.")
		return
	}
	writeJSON(w, 200, off)
}

func (h *Hub) handleHelperModel(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	off := h.helperOffer()
	if off == nil || off.path == "" {
		writeErr(w, 404, "This network's host doesn't have "+helperModel+" to share.")
		return
	}
	f, err := os.Open(off.path)
	if err != nil {
		writeErr(w, 404, "The host can't read its copy of "+helperModel+" right now.")
		return
	}
	defer f.Close()
	fi, err := f.Stat()
	if err != nil || fi.Size() != off.Size {
		writeErr(w, 409, "The host's copy of "+helperModel+" changed. Try again in a minute.")
		return
	}
	h.mu.Lock()
	if h.helperSending >= helperSendsMax {
		h.mu.Unlock()
		writeErr(w, 429, fmt.Sprintf("The host is already sending %s to %d computers. Try again in a few minutes.", helperModel, helperSendsMax))
		return
	}
	h.helperSending++
	h.mu.Unlock()
	defer func() {
		h.mu.Lock()
		h.helperSending--
		h.mu.Unlock()
	}()
	log.Printf("hub: sending %s to %s", off.Model, d.Name)
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Content-Length", strconv.FormatInt(fi.Size(), 10))
	w.WriteHeader(200)
	// In pieces, each with a write deadline: a computer that stops reading
	// (asleep, gone) gives its slot back within a minute, not when TCP gives up.
	rc := http.NewResponseController(w)
	buf := make([]byte, 1<<20)
	for {
		n, rerr := f.Read(buf)
		if n > 0 {
			_ = rc.SetWriteDeadline(time.Now().Add(helperStall))
			if _, err := w.Write(buf[:n]); err != nil {
				log.Printf("hub: sending %s to %s stopped: %v", off.Model, d.Name, err)
				return
			}
		}
		if rerr == io.EOF {
			break
		}
		if rerr != nil {
			log.Printf("hub: reading %s for %s: %v", off.Model, d.Name, rerr)
			return
		}
	}
	_ = rc.SetWriteDeadline(time.Time{})
	log.Printf("hub: sent %s to %s", off.Model, d.Name)
}

// ---------- on the computer that gets it ----------

// HelperOffer asks the hub which helper model its host hands out.
func (c *HubClient) HelperOffer(ctx context.Context) (HelperOffer, error) {
	var out HelperOffer
	_, err := c.call(ctx, "GET", "/v1/helper", nil, &out)
	return out, err
}

// HelperModel streams the host's copy of the helper model file.
func (c *HubClient) HelperModel(ctx context.Context) (io.ReadCloser, int64, error) {
	req, err := c.newReq(ctx, "GET", "/v1/helper/model", nil)
	if err != nil {
		return nil, 0, err
	}
	resp, err := c.hc.Do(req)
	if err != nil {
		return nil, 0, err
	}
	if resp.StatusCode != 200 {
		defer resp.Body.Close()
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		var e struct {
			Error string `json:"error"`
		}
		_ = json.Unmarshal(b, &e)
		return nil, 0, &apiError{Status: resp.StatusCode, Msg: firstNonEmpty(e.Error, resp.Status)}
	}
	return resp.Body, resp.ContentLength, nil
}

// countingReader only counts. The HTTP transport reads a request body on its
// own goroutine and may still be reading after the request returns (Ollama can
// answer early, say with a full disk), so it must not call back into anything.
type countingReader struct {
	r io.Reader
	n *atomic.Int64
}

func (c *countingReader) Read(p []byte) (int, error) {
	k, err := c.r.Read(p)
	c.n.Add(int64(k))
	return k, err
}

// installHelper gets the host's helper model into this computer's Ollama,
// reporting what it's doing and how many bytes have arrived.
func (a *App) installHelper(ctx context.Context, progress func(status string, done, total int64)) error {
	s := &a.helper
	s.mu.Lock()
	if s.installing {
		s.mu.Unlock()
		return errors.New("Hydra 1.0 is already being set up on this computer.")
	}
	s.installing = true
	s.mu.Unlock()
	a.notify()
	defer func() {
		s.mu.Lock()
		s.installing = false
		s.mu.Unlock()
		a.notify()
	}()

	if !a.ollama.Running() {
		return errors.New("Ollama isn't running on this computer.")
	}
	c, err := a.node.client()
	if err != nil {
		return errors.New("Join a network first: its host hands out " + helperModel + ".")
	}
	octx, cancel := context.WithTimeout(ctx, 15*time.Second)
	off, err := c.HelperOffer(octx)
	cancel()
	if err != nil {
		var ae *apiError
		if errors.As(err, &ae) {
			return errors.New(ae.Msg)
		}
		return errors.New(friendlyNetErr(err, "the hub"))
	}
	if normModel(off.Model) != helperModel || !digestRe.MatchString(off.Digest) || off.Size <= 0 {
		return errors.New("the host offered something that isn't " + helperModel)
	}
	oc := a.ollama.Client()
	have, err := oc.HasBlob(ctx, off.Digest)
	if err != nil {
		return err
	}
	if !have {
		copyCtx, stopCopy := context.WithCancel(ctx) // so a stalled copy can be stopped
		defer stopCopy()
		body, size, err := c.HelperModel(copyCtx)
		if err != nil {
			var ae *apiError
			if errors.As(err, &ae) {
				return errors.New(ae.Msg)
			}
			return errors.New(friendlyNetErr(err, "the hub"))
		}
		defer body.Close()
		if size < 0 { // a proxy in front of the hub (Tailscale Funnel) may not pass the length on
			size = off.Size
		}
		if size != off.Size {
			return errors.New("the host's copy of " + helperModel + " changed while it was being sent; try again")
		}
		progress("Copying from the host", 0, size)
		// Progress is reported from a ticker that has stopped before this goes
		// on, so only one goroutine reports at a time; a copy with no progress
		// for helperStall is stopped.
		var sent atomic.Int64
		var stalled atomic.Bool
		tickStop, tickDone := make(chan struct{}), make(chan struct{})
		go func() {
			defer close(tickDone)
			t := time.NewTicker(250 * time.Millisecond)
			defer t.Stop()
			lastN, lastAt := int64(0), time.Now()
			for {
				select {
				case <-tickStop:
					return
				case <-t.C:
				}
				if n := sent.Load(); n != lastN {
					lastN, lastAt = n, time.Now()
					progress("Copying from the host", n, size)
				} else if time.Since(lastAt) > helperStall {
					stalled.Store(true)
					stopCopy()
					return
				}
			}
		}()
		err = oc.PushBlob(copyCtx, off.Digest, &countingReader{r: body, n: &sent}, size)
		close(tickStop)
		<-tickDone
		if err != nil {
			switch {
			case ctx.Err() != nil:
				return ctx.Err()
			case stalled.Load():
				return errors.New("The copy from the host stopped for a minute. Check that both computers are awake and online, then try again.")
			}
			return err
		}
		progress("Copying from the host", size, size)
	}
	progress("Setting it up in Ollama", off.Size, off.Size)
	req := map[string]any{"model": off.Model, "files": map[string]string{"hydra-1.0.gguf": off.Digest}}
	if off.Template != "" {
		req["template"] = off.Template
	}
	if len(off.Parameters) > 0 {
		req["parameters"] = off.Parameters
	}
	if off.License != "" {
		req["license"] = off.License
	}
	if off.System != "" {
		req["system"] = off.System
	}
	if err := oc.Create(ctx, req, func(st string) { progress(st, off.Size, off.Size) }); err != nil {
		return err
	}
	log.Printf("helper: %s is set up on this computer", off.Model)
	a.ollama.Refresh()
	signal1(a.node.beatNow)
	return nil
}

// handleHelperInstall is the Models page's "Get it from the host" button: it
// streams progress the same way a download does.
func (a *App) handleHelperInstall(w http.ResponseWriter, r *http.Request) {
	fl, _ := w.(http.Flusher)
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.WriteHeader(200)
	last := time.Time{}
	err := a.installHelper(r.Context(), func(status string, done, total int64) {
		if time.Since(last) < 200*time.Millisecond && done < total {
			return
		}
		last = time.Now()
		writeSSE(w, "", map[string]any{"type": "progress", "status": status, "completed": done, "total": total})
		if fl != nil {
			fl.Flush()
		}
	})
	if err != nil {
		writeSSE(w, "", map[string]any{"type": "error", "error": err.Error()})
	} else {
		writeSSE(w, "", map[string]any{"type": "done"})
	}
	if fl != nil {
		fl.Flush()
	}
}

// HelperView is what the interface shows about the helper model here.
type HelperView struct {
	Model      string   `json:"model"`
	Installed  bool     `json:"installed"`  // in this computer's Ollama
	Offered    bool     `json:"offered"`    // this network's host hands it out
	SizeGB     float64  `json:"size_gb"`    // of the host's copy
	Sharing    bool     `json:"sharing"`    // this computer is the host handing it out
	Installing bool     `json:"installing"` // getting it from the host right now
	Devices    []string `json:"devices"`    // computers in the network that lend it
}

func (a *App) helperView(models []ModelInfo, snap *NetSnapshot, joined bool) HelperView {
	v := HelperView{Model: helperModel, Devices: []string{}}
	for _, m := range models {
		if normModel(m.Name) == helperModel {
			v.Installed = true
		}
	}
	a.helper.mu.Lock()
	v.Installing = a.helper.installing
	a.helper.mu.Unlock()
	if snap != nil && joined {
		if snap.Network.Helper != nil {
			v.Offered = true
			v.SizeGB = round1(float64(snap.Network.Helper.Size) / 1e9)
		}
		for _, d := range snap.Devices {
			for _, m := range d.Models {
				if normModel(m.Name) == helperModel && d.Online {
					v.Devices = append(v.Devices, d.Name)
				}
			}
		}
	}
	a.hubMu.Lock()
	v.Sharing = a.hub != nil && v.Offered
	a.hubMu.Unlock()
	return v
}

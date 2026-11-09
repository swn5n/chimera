package main

// What attached pictures show. The engines read only text, so before one is asked, a
// vision model on this computer (qwen3.8, which the look uses) writes one line on each
// picture: what it shows, what kind of picture it is (photo, cut-out, logo…), whether
// it's light or dark, any words in it, and where a heading could sit. A numbered run
// (a turntable's frames) gets one line, from its first frame.
//
// The model sees a small copy (at most 1,024 px across), made here: Go reads PNG, JPEG
// and GIF, and on a Mac sips reads the rest (WebP, HEIC, TIFF…), which Ollama either
// can't read or fills in black where it's see-through, so a black logo on a clear
// background came back as "dark grey text on black". See-through parts are filled
// with a grey that stands out from the picture, and the model is told so. Light or
// dark is measured from the pixels, not asked.
//
// Memory: this runs before the engine is asked, so with the engine stopped the model
// is loaded first and let go after, and the engine starts on a free Ollama. With the
// engine already running (DeepSeek holds tens of GB), it runs only if there's room
// beside it for the model (the user's choice, Nov 9).

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"image"
	"image/color"
	"image/jpeg"
	"io"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	describeMax    = 40              // pictures looked at in one message
	describeTime   = 3 * time.Minute // for all of them
	describeEach   = 90 * time.Second
	describePx     = 1024
	describePixMax = 60_000_000 // bigger pictures are shrunk by sips first, or skipped
)

const describeSystem = "You describe pictures for a web designer who can't see them. Be short, concrete and plain, and say only what you can see."

const describePrompt = `Describe this picture for a web page that will use it.
- shows: what is in it, in at most 20 words. Don't say what kind of picture it is.
- kind: photo, cut-out (one thing on its own, no background), logo, illustration, render, screenshot, icon, pattern or other.
- words: the words written in it, exactly as written, or "" if there are none.
- tone: light, dark or mixed, overall.
- text_space: where a heading could go on it without covering what matters, in at most 10 words, or "nowhere".`

const describeFilled = "\nIts see-through parts are filled with plain %s grey here: that grey isn't part of the picture, so leave it out."

var describeFormat = json.RawMessage(`{"type":"object","properties":{"shows":{"type":"string"},"kind":{"type":"string","enum":["photo","cut-out","logo","illustration","render","screenshot","icon","pattern","other"]},"words":{"type":"string"},"tone":{"type":"string","enum":["light","dark","mixed"]},"text_space":{"type":"string"}},"required":["shows","kind","words","tone","text_space"]}`)

type describeAnswer struct {
	Shows     string `json:"shows"`
	Kind      string `json:"kind"`
	Words     string `json:"words"`
	Tone      string `json:"tone"`
	TextSpace string `json:"text_space"`
}

// seenCache remembers what pictures showed, by their bytes and the model that looked
// (describe-cache.json in the data folder), so a folder attached again, in this chat
// or another, isn't looked at again.
type seenCache struct {
	mu    sync.Mutex
	path  string
	items map[string]seenItem
	dirty bool
}

type seenItem struct {
	Line string    `json:"line"`
	At   time.Time `json:"at"`
}

const (
	seenCacheMax    = 5000
	describeVersion = "1" // raise it when the prompt changes, so pictures are looked at again
)

var seenCaches = struct {
	sync.Mutex
	m map[string]*seenCache
}{m: map[string]*seenCache{}}

func seenCacheFor(dataDir string) *seenCache {
	seenCaches.Lock()
	defer seenCaches.Unlock()
	if c := seenCaches.m[dataDir]; c != nil {
		return c
	}
	c := &seenCache{path: filepath.Join(dataDir, "describe-cache.json"), items: map[string]seenItem{}}
	if b, err := os.ReadFile(c.path); err == nil {
		_ = json.Unmarshal(b, &c.items)
	}
	seenCaches.m[dataDir] = c
	return c
}

func seenKey(model, sum string) string { return describeVersion + " " + model + " " + sum }

func (c *seenCache) get(model, sum string) (string, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	it, ok := c.items[seenKey(model, sum)]
	return it.Line, ok && it.Line != ""
}

func (c *seenCache) put(model, sum, line string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.items[seenKey(model, sum)] = seenItem{Line: line, At: time.Now().UTC()}
	c.dirty = true
	if len(c.items) > seenCacheMax { // the oldest go
		keys := make([]string, 0, len(c.items))
		for k := range c.items {
			keys = append(keys, k)
		}
		sort.Slice(keys, func(i, j int) bool { return c.items[keys[i]].At.Before(c.items[keys[j]].At) })
		for _, k := range keys[:len(keys)-seenCacheMax] {
			delete(c.items, k)
		}
	}
}

func (c *seenCache) save() {
	c.mu.Lock()
	defer c.mu.Unlock()
	if !c.dirty {
		return
	}
	b, err := json.Marshal(c.items)
	if err != nil {
		return
	}
	tmp := c.path + ".tmp"
	if os.WriteFile(tmp, b, 0o600) == nil && os.Rename(tmp, c.path) == nil {
		c.dirty = false
	}
}

// fileSum is a file's SHA-256 ("" if it can't be read).
func fileSum(full string) string {
	f, err := os.Open(full)
	if err != nil {
		return ""
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return ""
	}
	return hex.EncodeToString(h.Sum(nil))
}

// visionModel is this computer's model whose name starts with prefix that can see:
// the largest that fits.
func (a *App) visionModel(prefix string) (ModelInfo, bool) {
	if a.ollama == nil {
		return ModelInfo{}, false
	}
	var eyes []ModelInfo
	for _, m := range a.annotate(a.ollama.State().Models) {
		if strings.HasPrefix(m.Name, prefix) {
			eyes = append(eyes, m)
		}
	}
	return pickLocalModel(eyes, "", []string{"vision"}, "largest", "")
}

// describeModel is the model that describes attached pictures (CHIMERA_DESCRIBE_MODEL
// tries another).
func (a *App) describeModel() (ModelInfo, bool) {
	name := os.Getenv("CHIMERA_DESCRIBE_MODEL")
	if name == "" {
		name = "qwen3.8:"
	}
	return a.visionModel(name)
}

// roomBeside says whether a model of size bytes fits in memory beside what's running
// now, and if not, why (a size on disk; loaded, it needs some more).
func roomBeside(size int64, free int64, known bool) (bool, string) {
	if !known {
		return false, "how much memory is free can't be told on this computer"
	}
	need := size + size/4 + 4<<30
	if free >= need {
		return true, ""
	}
	return false, fmt.Sprintf("it needs about %s and %s is free", humanBytes(need), humanBytes(free))
}

// freeMemoryNow is how much memory could be had without pushing anything out: what's
// free, plus caches the system can drop (a variable, for tests).
var freeMemoryNow = freeMemory

func freeMemory() (int64, bool) {
	switch runtime.GOOS {
	case "darwin":
		out := runOut(5*time.Second, "/usr/bin/vm_stat")
		return vmStatFree(out)
	case "linux":
		b, err := os.ReadFile("/proc/meminfo")
		if err != nil {
			return 0, false
		}
		for _, l := range strings.Split(string(b), "\n") {
			if f := strings.Fields(l); len(f) >= 2 && f[0] == "MemAvailable:" {
				if kb, err := strconv.ParseInt(f[1], 10, 64); err == nil {
					return kb << 10, true
				}
			}
		}
	}
	return 0, false
}

// vmStatFree reads macOS's vm_stat: free, inactive, speculative and purgeable pages.
func vmStatFree(out string) (int64, bool) {
	page := int64(0)
	if i := strings.Index(out, "page size of "); i >= 0 {
		f := strings.Fields(out[i+len("page size of "):])
		if len(f) > 0 {
			page, _ = strconv.ParseInt(f[0], 10, 64)
		}
	}
	if page <= 0 {
		return 0, false
	}
	var pages int64
	got := 0
	for _, l := range strings.Split(out, "\n") {
		k, v, ok := strings.Cut(l, ":")
		if !ok {
			continue
		}
		switch strings.TrimSpace(k) {
		case "Pages free", "Pages inactive", "Pages speculative", "Pages purgeable":
			if n, err := strconv.ParseInt(strings.TrimSuffix(strings.TrimSpace(v), "."), 10, 64); err == nil {
				pages += n
				got++
			}
		}
	}
	if got == 0 {
		return 0, false
	}
	return pages * page, true
}

// visionCopy is a picture as the vision model gets it: at most describePx across, as a
// JPEG, with any see-through parts filled with a grey that stands out ("dark" or
// "light", or "" when there were none). tone is how light the picture is, measured
// ("" when it couldn't be). A file that can't be read here gives an error.
func visionCopy(ctx context.Context, full string, x fileFacts) (data []byte, filled, tone string, err error) {
	var img image.Image
	switch x.Format {
	case "PNG", "JPEG", "GIF":
		if x.Width*x.Height <= describePixMax {
			img, err = decodeFile(full)
		} else if img, err = sipsCopy(ctx, full, x); err != nil {
			return nil, "", "", errors.New("it's too big to look at here")
		}
	case "SVG":
		return nil, "", "", errors.New("an SVG's code goes with it instead")
	default:
		img, err = sipsCopy(ctx, full, x)
		if err != nil && x.Format == "WebP" {
			// Ollama reads WebP itself; only its see-through parts come out black.
			b, rerr := os.ReadFile(full)
			if rerr != nil || len(b) > 32<<20 {
				return nil, "", "", errors.New("it can't be read here")
			}
			return b, "", "", nil
		}
	}
	if err != nil {
		return nil, "", "", err
	}
	small := shrink(img, describePx)
	if x.Format == "JPEG" { // as a browser shows it: turned the way the camera said
		small = orient(small, exifOrientation(readHead(full, 64<<10)))
	}
	lum, clear := lightness(small)
	switch {
	case lum < 0.38:
		tone = "dark"
	case lum > 0.62:
		tone = "light"
	default:
		tone = "mid-toned"
	}
	if clear {
		// A grey the picture stands out on: dark behind light things, light behind dark ones.
		bg, word := color.NRGBA{R: 216, G: 216, B: 214, A: 255}, "light"
		if lum >= 0.5 {
			bg, word = color.NRGBA{R: 40, G: 40, B: 42, A: 255}, "dark"
		}
		fillBehind(small, bg)
		filled = word
	}
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, small, &jpeg.Options{Quality: 88}); err != nil {
		return nil, "", "", err
	}
	return buf.Bytes(), filled, tone, nil
}

func decodeFile(full string) (image.Image, error) {
	f, err := os.Open(full)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	// Its size first: a header can claim a size that would take all the memory to decode.
	c, _, err := image.DecodeConfig(f)
	if err != nil || c.Width <= 0 || c.Height <= 0 || c.Width*c.Height > describePixMax {
		return nil, errors.New("it can't be read as a picture here")
	}
	if _, err := f.Seek(0, io.SeekStart); err != nil {
		return nil, err
	}
	img, _, err := image.Decode(f)
	if err != nil {
		return nil, errors.New("it can't be read as a picture")
	}
	return img, nil
}

// orient turns a picture the way a JPEG's EXIF orientation (1 to 8) says to show it.
func orient(img *image.NRGBA, o int) *image.NRGBA {
	if o < 2 || o > 8 {
		return img
	}
	w, h := img.Bounds().Dx(), img.Bounds().Dy()
	dw, dh := w, h
	if o >= 5 {
		dw, dh = h, w
	}
	out := image.NewNRGBA(image.Rect(0, 0, dw, dh))
	for y := 0; y < dh; y++ {
		for x := 0; x < dw; x++ {
			sx, sy := x, y
			switch o {
			case 2:
				sx = w - 1 - x
			case 3:
				sx, sy = w-1-x, h-1-y
			case 4:
				sy = h - 1 - y
			case 5:
				sx, sy = y, x
			case 6:
				sx, sy = y, h-1-x
			case 7:
				sx, sy = w-1-y, h-1-x
			case 8:
				sx, sy = w-1-y, x
			}
			out.SetNRGBA(x, y, img.NRGBAAt(sx, sy))
		}
	}
	return out
}

// sipsCopy reads a picture Go can't (WebP, HEIC, TIFF, BMP…) with macOS's sips, as a
// PNG at most describePx across.
func sipsCopy(ctx context.Context, full string, x fileFacts) (image.Image, error) {
	if runtime.GOOS != "darwin" || !fileExists("/usr/bin/sips") {
		return nil, errors.New("it can't be read here")
	}
	dir, err := os.MkdirTemp("", "chimera-look-*")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(dir)
	out := filepath.Join(dir, "copy.png")
	args := []string{"-s", "format", "png"}
	if x.Width == 0 || x.Height == 0 || max(x.Width, x.Height) > describePx {
		args = append(args, "-Z", strconv.Itoa(describePx)) // sips also enlarges, so only when it's big (or its size isn't known)
	}
	cctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	cmd := exec.CommandContext(cctx, "/usr/bin/sips", append(args, full, "--out", out)...)
	hideWindow(cmd)
	if err := cmd.Run(); err != nil {
		return nil, errors.New("it can't be read here")
	}
	if st, err := os.Lstat(out); err != nil || !st.Mode().IsRegular() {
		return nil, errors.New("it can't be read here")
	}
	return decodeFile(out)
}

// shrink is img at most side pixels across, each pixel the average of the ones it
// covers (sampled when it covers many), see-through parts kept.
func shrink(img image.Image, side int) *image.NRGBA {
	b := img.Bounds()
	w, h := b.Dx(), b.Dy()
	if w <= 0 || h <= 0 {
		return image.NewNRGBA(image.Rect(0, 0, 1, 1))
	}
	scale := math.Max(1, float64(max(w, h))/float64(side))
	nw, nh := max(1, int(math.Round(float64(w)/scale))), max(1, int(math.Round(float64(h)/scale)))
	out := image.NewNRGBA(image.Rect(0, 0, nw, nh))
	for y := 0; y < nh; y++ {
		y0, y1 := y*h/nh, max((y+1)*h/nh, y*h/nh+1)
		sy := max(1, (y1-y0)/4)
		for x := 0; x < nw; x++ {
			x0, x1 := x*w/nw, max((x+1)*w/nw, x*w/nw+1)
			sx := max(1, (x1-x0)/4)
			var r, g, bl, a, n uint64
			for yy := y0; yy < y1; yy += sy {
				for xx := x0; xx < x1; xx += sx {
					cr, cg, cb, ca := img.At(b.Min.X+xx, b.Min.Y+yy).RGBA() // alpha-premultiplied
					r, g, bl, a, n = r+uint64(cr), g+uint64(cg), bl+uint64(cb), a+uint64(ca), n+1
				}
			}
			if a == 0 {
				continue
			}
			out.SetNRGBA(x, y, color.NRGBA{R: uint8(r * 255 / a), G: uint8(g * 255 / a), B: uint8(bl * 255 / a), A: uint8(a / n >> 8)})
		}
	}
	return out
}

// lightness is how light a picture's visible parts are (0 black, 1 white), and
// whether any of it is see-through.
func lightness(img *image.NRGBA) (float64, bool) {
	var sum, weight float64
	clear := 0
	px := img.Pix
	for i := 0; i+3 < len(px); i += 4 {
		a := float64(px[i+3]) / 255
		if px[i+3] < 250 {
			clear++
		}
		sum += a * (0.2126*float64(px[i]) + 0.7152*float64(px[i+1]) + 0.0722*float64(px[i+2])) / 255
		weight += a
	}
	n := len(px) / 4
	if weight == 0 {
		return 0, n > 0
	}
	return sum / weight, clear*200 >= n // see-through in at least half a percent of it
}

// fillBehind puts the picture on bg.
func fillBehind(img *image.NRGBA, bg color.NRGBA) {
	px := img.Pix
	for i := 0; i+3 < len(px); i += 4 {
		a := uint32(px[i+3])
		for c, v := range []uint8{bg.R, bg.G, bg.B} {
			px[i+c] = uint8((uint32(px[i+c])*a + uint32(v)*(255-a)) / 255)
		}
		px[i+3] = 255
	}
}

// askDescribe asks the vision model about one picture (data: a JPEG, or a WebP as it is).
func askDescribe(ctx context.Context, client *OllamaClient, model string, data []byte, filled string) (describeAnswer, error) {
	var ans describeAnswer
	prompt := describePrompt
	if filled != "" {
		prompt += fmt.Sprintf(describeFilled, filled)
	}
	reply, err := client.ChatImage(ctx, model, describeSystem, prompt, data, describeFormat)
	if err != nil {
		return ans, err
	}
	if err := json.Unmarshal([]byte(reply), &ans); err != nil {
		return ans, errors.New("its answer wasn't readable")
	}
	if strings.TrimSpace(ans.Shows) == "" {
		return ans, errors.New("it said nothing about it")
	}
	return ans, nil
}

// showsLine is what the model is told a picture shows: "photo, light: a branch
// building under a blue sky; the words "RAKA Rentals"; room for a heading: the sky at
// the top". tone, when measured, is used over the model's.
func showsLine(ans describeAnswer, tone string) string {
	kind := strings.TrimSpace(ans.Kind)
	switch kind {
	case "photo", "cut-out", "logo", "illustration", "render", "screenshot", "icon", "pattern":
	default:
		kind = "picture"
	}
	if tone == "" {
		switch t := strings.TrimSpace(ans.Tone); t {
		case "light", "dark":
			tone = t
		case "mixed":
			tone = "light and dark"
		}
	}
	head := kind
	if tone != "" {
		head += ", " + tone
	}
	line := head + ": " + strings.TrimSuffix(shortLine(ans.Shows, 200), ".")
	if w := strings.Trim(shortLine(ans.Words, 120), `"' `); w != "" && !strings.EqualFold(w, "none") {
		line += fmt.Sprintf("; the words %q", w)
	}
	if s := strings.TrimSuffix(shortLine(ans.TextSpace, 100), "."); s != "" {
		if strings.EqualFold(s, "nowhere") || strings.EqualFold(s, "none") {
			line += "; no room for a heading on it"
		} else {
			line += "; room for a heading: " + lowerFirstWord(s)
		}
	}
	return line
}

// shortLine is s on one line, at most n characters, cut at a word.
func shortLine(s string, n int) string {
	s = strings.Join(strings.Fields(s), " ")
	if r := []rune(s); len(r) > n {
		cut := string(r[:n])
		if i := strings.LastIndex(cut, " "); i > n/2 {
			cut = cut[:i]
		}
		s = strings.TrimRight(cut, ",;:") + "…"
	}
	return s
}

func lowerFirstWord(s string) string {
	r := []rune(s)
	if len(r) > 1 && r[0] >= 'A' && r[0] <= 'Z' && !(r[1] >= 'A' && r[1] <= 'Z') {
		r[0] += 'a' - 'A'
	}
	return string(r)
}

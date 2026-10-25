package main

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func testHubWithPlugins(t *testing.T, plugins ...PluginInfo) (*Hub, *hubDevice) {
	t.Helper()
	h := NewHub(filepath.Join(t.TempDir(), "hub.json"), 0)
	h.lib = loadLibrary(filepath.Join(t.TempDir(), "library.json"))
	var tools []ToolInfo
	for _, p := range plugins {
		tools = append(tools, ToolInfo{ID: "plugin:" + p.ID, Have: p.Have})
	}
	worker := &hubDevice{ID: "w", Name: "Studio Mac", Owner: "Andrews", online: true, lending: true, ollamaOK: true,
		lastSeen: time.Now(), slots: 1, lendPlugins: true, profile: DeviceProfile{Tools: tools, Plugins: plugins}}
	asker := &hubDevice{ID: "a", Name: "Laptop", Owner: "Sam", online: true, lastSeen: time.Now()}
	h.st.Devices["w"], h.st.Devices["a"] = worker, asker
	h.syncPluginEntriesLocked(worker)
	return h, asker
}

var shadowPlugin = PluginInfo{ID: "perspective-shadow", Name: "Perspective studio shadow", Version: "0.1.0",
	Summary: "Gives a picture of a machine a realistic studio shadow on a clean background.", Have: true,
	Tags: []string{"shadow", "product photo"}, Accepts: []string{"image/png", "image/jpeg"}}

var otherShadow = PluginInfo{ID: "quick-shadow", Name: "Quick drop shadow", Version: "1.0.0",
	Summary: "A simple drop shadow under any cut-out.", Have: true, Tags: []string{"shadow"}, Accepts: []string{"image/*"}}

var upscaler = PluginInfo{ID: "upscale", Name: "Upscaler", Version: "1.0.0", Summary: "Makes small pictures bigger and sharper.",
	Have: true, Tags: []string{"upscale", "resolution"}, Accepts: []string{"image/png"}}

func TestPluginSearchRelevanceThenRating(t *testing.T) {
	h, asker := testHubWithPlugins(t, shadowPlugin, otherShadow, upscaler)
	// Both shadow plugins are relevant; with no ratings the prior ties them and relevance decides.
	got := h.pluginCandidatesLocked(asker, "add a soft studio shadow under this machine", "image/png", false)
	if len(got) != 2 {
		t.Fatalf("want the 2 shadow plugins, got %+v", got)
	}
	if got[0].ID != "perspective-shadow" {
		t.Fatalf("unrated: the more relevant plugin should lead, got %s", got[0].ID)
	}
	// Ratings decide between relevant plugins: quick-shadow gets 5s, perspective 2s and 3s.
	for _, r := range []int{5, 5, 5} {
		h.ratePluginLocked("quick-shadow", r)
	}
	for _, r := range []int{2, 3} {
		h.ratePluginLocked("perspective-shadow", r)
	}
	got = h.pluginCandidatesLocked(asker, "add a soft studio shadow under this machine", "image/png", false)
	if got[0].ID != "quick-shadow" || got[0].Rating != 5 || got[0].Rated != 3 {
		t.Fatalf("the better rated plugin should lead: %+v", got[0])
	}
	// An irrelevant request finds neither shadow plugin.
	if got := h.pluginCandidatesLocked(asker, "make this picture bigger and sharper", "image/png", false); len(got) != 1 || got[0].ID != "upscale" {
		t.Fatalf("want only the upscaler, got %+v", got)
	}
	// A JPEG can't go to a PNG-only plugin.
	for _, c := range h.pluginCandidatesLocked(asker, "upscale", "image/jpeg", false) {
		if c.ID == "upscale" {
			t.Fatal("upscale only takes PNG")
		}
	}
}

func TestPluginNotLentToOthers(t *testing.T) {
	h, asker := testHubWithPlugins(t, shadowPlugin)
	h.st.Devices["w"].lendPlugins = false
	if got := h.pluginCandidatesLocked(asker, "shadow", "image/png", false); len(got) != 0 {
		t.Fatalf("a device that doesn't lend plugins must not be offered: %+v", got)
	}
	st := &hubStep{Kind: "run_plugin", Plugin: "perspective-shadow", RequesterOwner: "Sam", Exclude: map[string]bool{}}
	if _, _, ok := h.fits(h.st.Devices["w"], st); ok {
		t.Fatal("fits must refuse another owner's step when plugins aren't lent")
	}
	st.RequesterOwner = "Andrews" // the owner's own request still runs
	if _, _, ok := h.fits(h.st.Devices["w"], st); !ok {
		t.Fatal("the owner's own plugin step should fit")
	}
}

func TestPluginFlaggedAfterBadRatings(t *testing.T) {
	h, asker := testHubWithPlugins(t, shadowPlugin)
	for i := 0; i < 3; i++ {
		h.ratePluginLocked("perspective-shadow", 1)
	}
	if e := h.pluginEntryLocked("perspective-shadow"); e.Status != "flagged" {
		t.Fatalf("want flagged, got %s", e.Status)
	}
	if got := h.pluginCandidatesLocked(asker, "shadow", "image/png", false); len(got) != 0 {
		t.Fatal("a flagged plugin isn't picked")
	}
}

func TestPluginVerifiedByFirstRun(t *testing.T) {
	h, _ := testHubWithPlugins(t, shadowPlugin)
	st := &hubStep{Kind: "run_plugin", Plugin: "perspective-shadow", RequesterOwner: "Sam", Files: []StepFile{{Name: "a.png"}}}
	h.pluginStepDoneLocked(st, h.st.Devices["w"], "done")
	e := h.pluginEntryLocked("perspective-shadow")
	if e.Status != "verified" || e.Uses != 1 || len(e.Checks) != 1 || e.Checks[0].Kind != "run" {
		t.Fatalf("want verified after a run that returned files: %+v", e)
	}
	// A new version keeps its ratings but proves itself again.
	e.Stars, e.Rated = 9, 2
	newer := shadowPlugin
	newer.Version = "0.2.0"
	h.st.Devices["w"].profile.Plugins = []PluginInfo{newer}
	h.syncPluginEntriesLocked(h.st.Devices["w"])
	if e.Status != "unverified" || e.Version != "0.2.0" || e.Rated != 2 {
		t.Fatalf("new version: %+v", e)
	}
}

func TestCleanOptions(t *testing.T) {
	var schema optionSchema
	raw := `{"type":"object","properties":{
		"style":{"type":"string","enum":["soft","left","right"]},
		"darkness":{"type":"number","minimum":0.1,"maximum":1},
		"samples":{"type":"integer","minimum":16,"maximum":1024},
		"accurate_3d":{"type":"boolean"},
		"outputs":{"type":"array","items":{"type":"string","enum":["background","transparent","shadow_only"]}}}}`
	if err := json.Unmarshal([]byte(raw), &schema); err != nil {
		t.Fatal(err)
	}
	got := cleanOptions(schema, map[string]any{
		"style": "left", "darkness": 3.0, "samples": 99.6, "accurate_3d": "yes", "outputs": []any{"transparent", "bogus"},
		"rm_rf": true,
	})
	if got["style"] != "left" || got["darkness"] != 1.0 || got["samples"] != 100.0 {
		t.Fatalf("got %+v", got)
	}
	if _, ok := got["accurate_3d"]; ok {
		t.Fatal("a string isn't a boolean")
	}
	if _, ok := got["rm_rf"]; ok {
		t.Fatal("unknown options are dropped")
	}
	if o := got["outputs"].([]any); len(o) != 1 || o[0] != "transparent" {
		t.Fatalf("outputs: %+v", got["outputs"])
	}
	if got := cleanOptions(schema, map[string]any{"style": "upside-down"}); len(got) != 0 {
		t.Fatal("values outside the enum are dropped")
	}
}

func TestReadManifestRejectsBadPlugins(t *testing.T) {
	dir := t.TempDir()
	write := func(m string) {
		if err := os.WriteFile(filepath.Join(dir, "plugin.json"), []byte(m), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	write(`{"id":"Bad ID","entry":"run.py"}`)
	if _, _, err := readManifest(dir); err == nil {
		t.Fatal("bad id accepted")
	}
	write(`{"id":"ok-plugin","entry":"../../etc/run.py"}`)
	if _, _, err := readManifest(dir); err == nil {
		t.Fatal("entry outside the folder accepted")
	}
	write(`{"id":"ok-plugin","entry":"run.py","timeout_s":999999}`)
	m, _, err := readManifest(dir)
	if err != nil || m.TimeoutS != 7200 || m.Name != "ok-plugin" {
		t.Fatalf("got %+v %v", m, err)
	}
}

func TestCollectPluginFilesStaysInOutputFolder(t *testing.T) {
	root := t.TempDir()
	out := filepath.Join(root, "out")
	os.MkdirAll(out, 0o755)
	os.WriteFile(filepath.Join(root, "secret.txt"), []byte("no"), 0o644)
	os.WriteFile(filepath.Join(out, "a.png"), pngHeader(640, 480), 0o644)
	var po pluginOutput
	json.Unmarshal([]byte(`{"ok":true,"files":[{"path":"../secret.txt"}]}`), &po)
	if files, err := collectPluginFiles(out, po); err == nil && len(files) == 1 && files[0].Name == "secret.txt" {
		t.Fatal("read a file outside the output folder")
	}
	json.Unmarshal([]byte(`{"ok":true,"files":[{"path":"a.png"}]}`), &po)
	files, err := collectPluginFiles(out, po)
	if err != nil || len(files) != 1 || files[0].Width != 640 || files[0].Height != 480 || files[0].MIME != "image/png" {
		t.Fatalf("got %+v %v", files, err)
	}
	// No list: everything in the folder.
	files, err = collectPluginFiles(out, pluginOutput{OK: true})
	if err != nil || len(files) != 1 {
		t.Fatalf("got %+v %v", files, err)
	}
}

func TestMacPluginSandboxProfile(t *testing.T) {
	dir := t.TempDir()
	// as installed: the plugin, the step's run folder and the cache all live in Chimera's data folder
	data := filepath.Join(dir, "data")
	plug := filepath.Join(data, "plugins", "x")
	run, cache := filepath.Join(data, "plugin-runs", "x-1"), filepath.Join(data, "plugin-cache", "x")
	for _, d := range []string{plug, cache, run} {
		os.MkdirAll(d, 0o755)
	}
	// the probe names a folder that contains the data folder, plus a missing and a relative path
	p := macPluginSandboxProfile("/usr/bin/python3", []string{plug, dir, "/does/not/exist", "relative/path"}, []string{run, cache}, []string{data}, false)
	lines := strings.Split(p, "\n")
	at := func(line string) int {
		for i, l := range lines {
			if l == line {
				return i
			}
		}
		t.Fatalf("profile lacks the line %s:\n%s", line, p)
		return -1
	}
	sub := func(ps ...string) string {
		var b strings.Builder
		for _, x := range ps {
			b.WriteString(` (subpath "` + x + `")`)
		}
		return b.String()
	}
	homes := at(`(deny file-read* (subpath "/Users") (subpath "/Volumes") (subpath "/private/var/root"))`)
	reads := at(`(allow file-read*` + sub(plug, dir, "/usr", run, cache) + `)`)
	hidden := at(`(deny file-read*` + sub(data) + `)`)
	back := at(`(allow file-read*` + sub(plug, run, cache) + `)`)
	if !(homes < reads && reads < hidden && hidden < back) {
		t.Fatalf("the data folder must be hidden after the reads are allowed (a read folder contains it), then only the plugin, run and cache allowed back:\n%s", p)
	}
	if !strings.HasSuffix(p, `(deny file-write*`+sub(data)+`)`+"\n"+`(allow file-write*`+sub(run, cache)+`)`) {
		t.Fatalf("the data folder isn't writable except the run and cache folders:\n%s", p)
	}
	at("(deny network*)")
	at("(deny file-write*)")
	meta := lines[at(lines[hidden+2])]
	if !strings.HasPrefix(meta, "(allow file-read-metadata") || !strings.Contains(meta, `(literal "`+dir+`")`) ||
		strings.Contains(meta, `(literal "/")`) || strings.Contains(meta, "subpath") {
		t.Fatalf("the folders above the allowed ones are stat-able (literal only, not /):\n%s", meta)
	}
	if strings.Contains(p, "/does/not/exist") || strings.Contains(p, "relative/path") {
		t.Fatalf("missing or relative paths must be left out:\n%s", p)
	}
	writes := p[strings.Index(p, "(allow file-write*"):]
	if !strings.Contains(writes, run) || !strings.Contains(writes, cache) || strings.Contains(writes, plug) {
		t.Fatalf("writes only to the run and cache folders:\n%s", writes)
	}
	for _, l := range lines {
		if strings.HasPrefix(l, "(allow file-") && !strings.Contains(l, "(subpath ") && !strings.Contains(l, "(literal ") {
			t.Fatalf("an allow rule with no filter applies to every path: %s\n%s", l, p)
		}
	}
	// nothing to allow: no unfiltered allow rule appears
	none := macPluginSandboxProfile("/no/such/python", nil, nil, nil, false)
	for _, l := range strings.Split(none, "\n") {
		if l == "(allow file-read*)" || l == "(allow file-read-metadata)" || l == "(allow file-write*)" {
			t.Fatalf("an empty list must leave the rule out, not allow everything:\n%s", none)
		}
	}
}

func pngHeader(w, h int) []byte {
	b := []byte("\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR")
	b = binary.BigEndian.AppendUint32(b, uint32(w))
	b = binary.BigEndian.AppendUint32(b, uint32(h))
	return append(b, 8, 6, 0, 0, 0, 0, 0, 0, 0)
}

func TestImageSize(t *testing.T) {
	if w, h := imageSize(pngHeader(1080, 720)); w != 1080 || h != 720 {
		t.Fatalf("png %dx%d", w, h)
	}
	// VP8X: 24-bit sizes minus one at bytes 24..29
	webp := make([]byte, 40)
	copy(webp, "RIFF")
	copy(webp[8:], "WEBPVP8X")
	webp[24], webp[25], webp[26] = 0x37, 0x04, 0 // 1080-1 = 0x437
	webp[27], webp[28], webp[29] = 0xCF, 0x02, 0 // 720-1 = 0x2CF
	if w, h := imageSize(webp); w != 1080 || h != 720 {
		t.Fatalf("webp %dx%d", w, h)
	}
}

func TestFilesAreServedSafely(t *testing.T) {
	a := &App{sessions: NewSessionStore(t.TempDir())}
	svg := []byte(`<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><script>fetch("/api/quit",{method:"POST",headers:{"X-Chimera":"1"}})</script></svg>`)
	png := pngHeader(4, 4)
	fs, _ := a.sessions.SaveFile("abc123", "evil.svg", "image/png", svg)
	fp, _ := a.sessions.SaveFile("abc123", "ok.png", "image/png", png)
	mux := http.NewServeMux()
	a.fileRoutes(mux)
	get := func(id string) *httptest.ResponseRecorder {
		rr := httptest.NewRecorder()
		mux.ServeHTTP(rr, httptest.NewRequest("GET", "/api/files/abc123/"+id, nil))
		return rr
	}
	if rr := get(fs.ID); rr.Header().Get("Content-Type") != "application/octet-stream" || rr.Header().Get("Content-Disposition") != "attachment" ||
		!strings.Contains(rr.Header().Get("Content-Security-Policy"), "sandbox") {
		t.Fatalf("an SVG must download, never render: %v", rr.Header())
	}
	if rr := get(fp.ID); rr.Header().Get("Content-Type") != "image/png" || rr.Header().Get("Content-Disposition") != "" {
		t.Fatalf("a PNG shows inline: %v", rr.Header())
	}
	if rr := get("Not.A-Valid_ID"); rr.Code != 404 {
		t.Fatalf("bad ids are refused, got %d", rr.Code)
	}
	if rr := get("../../etc"); rr.Code == 200 { // the router cleans the path and redirects away
		t.Fatalf("a dotted path must not be served")
	}
}

func TestCollectPluginFilesRefusesSymlinkedFolders(t *testing.T) {
	root := t.TempDir()
	out, secret := filepath.Join(root, "out"), filepath.Join(root, "private")
	os.MkdirAll(out, 0o755)
	os.MkdirAll(secret, 0o755)
	os.WriteFile(filepath.Join(secret, "id_rsa"), []byte("key"), 0o600)
	if err := os.Symlink(secret, filepath.Join(out, "link")); err != nil {
		t.Skip(err)
	}
	var po pluginOutput
	json.Unmarshal([]byte(`{"ok":true,"files":[{"path":"link/id_rsa"}]}`), &po)
	if files, err := collectPluginFiles(out, po); err == nil {
		t.Fatalf("read %s through a symlinked folder", files[0].Name)
	}
	// with no list, only regular files at the top are taken (the link is not)
	if files, err := collectPluginFiles(out, pluginOutput{OK: true}); err != nil || len(files) != 0 {
		t.Fatalf("got %v %v", files, err)
	}
}

func TestPluginRatingsNeedARealRun(t *testing.T) {
	h, asker := testHubWithPlugins(t, shadowPlugin)
	worker := h.st.Devices["w"]
	post := func(d *hubDevice, body string) {
		rr := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/v1/feedback", strings.NewReader(body))
		h.handleFeedback(rr, req, d)
	}
	for i := 0; i < 3; i++ { // ratings out of nowhere don't count
		post(asker, `{"rating":1,"plugin":"perspective-shadow","response":"x"}`)
		post(asker, `{"rating":1,"plugin":"perspective-shadow","step_id":"made-up","response":"x"}`)
	}
	if e := h.pluginEntryLocked("perspective-shadow"); e.Rated != 0 || e.Status == "flagged" {
		t.Fatalf("forged ratings counted: %+v", e)
	}
	st := &hubStep{ID: "s1", Kind: "run_plugin", Plugin: "perspective-shadow", RequesterOwner: "Sam", Files: []StepFile{{Name: "a.png"}}}
	h.pluginStepDoneLocked(st, worker, "done")
	post(worker, `{"rating":5,"plugin":"perspective-shadow","step_id":"s1","response":"x"}`) // not the asker
	post(asker, `{"rating":4,"plugin":"perspective-shadow","step_id":"s1","response":"x"}`)
	post(asker, `{"rating":4,"plugin":"perspective-shadow","step_id":"s1","response":"x"}`) // only once
	if e := h.pluginEntryLocked("perspective-shadow"); e.Rated != 1 || e.Stars != 4 {
		t.Fatalf("want exactly the asker's one rating: %+v", e)
	}
}

func TestPluginEntriesOwnedAndCapped(t *testing.T) {
	h, _ := testHubWithPlugins(t, shadowPlugin)
	e := h.pluginEntryLocked("perspective-shadow")
	e.Status = "verified"
	// another member claims a newer version of the same id: the entry isn't rewritten
	evil := shadowPlugin
	evil.Version, evil.Summary = "9.9.9", "totally different"
	other := &hubDevice{ID: "x", Name: "Other", Owner: "Mallory", online: true, lastSeen: time.Now(),
		profile: DeviceProfile{Plugins: []PluginInfo{evil}}}
	h.syncPluginEntriesLocked(other)
	if e.Version != "0.1.0" || e.Status != "verified" || e.Summary == "totally different" {
		t.Fatalf("a stranger rewrote the entry: %+v", e)
	}
	// a flood of made-up plugins stops at the cap
	var many []PluginInfo
	for i := 0; i < maxPluginEntries+50; i++ {
		many = append(many, PluginInfo{ID: fmt.Sprintf("fake-%d", i), Name: "x", Version: "1", Have: true})
	}
	other.profile.Plugins = many
	h.syncPluginEntriesLocked(other)
	if n := h.pluginEntryCountLocked(); n != maxPluginEntries {
		t.Fatalf("want the cap of %d entries, got %d", maxPluginEntries, n)
	}
}

func TestPluginChargeUsesTheHubsClock(t *testing.T) {
	h, _ := testHubWithPlugins(t, shadowPlugin)
	worker := h.st.Devices["w"]
	st := &hubStep{ID: "s2", Kind: "run_plugin", Plugin: "perspective-shadow", RequesterOwner: "Sam",
		AssignedAt: time.Now().Add(-60 * time.Second), Stats: ChatStats{TotalDuration: int64(365 * 24 * time.Hour)}}
	h.st.Balances[ownerKey("Sam")] = 100
	credits, free := h.chargeLocked(st, worker)
	if free || credits < 1.9 || credits > 2.2 {
		t.Fatalf("a year reported, a minute seen: want about 2 credits, got %v", credits)
	}
}

func TestPluginReadPathsMustBeSpecific(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	inside := filepath.Join(home, "Desktop", "Perspective")
	data := filepath.Join(home, "Library", "Chimera")
	own := filepath.Join(data, "plugins", "x")
	for _, d := range []string{inside, own, filepath.Join(data, "sessions")} {
		os.MkdirAll(d, 0o755)
	}
	os.WriteFile(filepath.Join(data, "config.json"), []byte("{}"), 0o600)
	got := pluginReadPaths("x", []string{"/", "/Users", "/home", "/root", "/Users/someone", "/home/someone", home, home + "/",
		filepath.Dir(home), data, filepath.Join(data, "config.json"), filepath.Join(data, "sessions"), filepath.Join(own, "models"),
		inside, "/Users/Shared/Models", "/opt/tool", "relative/path", " "}, data, own)
	want := []string{filepath.Join(own, "models"), inside, "/Users/Shared/Models", "/opt/tool"}
	if strings.Join(got, "|") != strings.Join(want, "|") {
		t.Fatalf("only specific folders outside the data folder (or in the plugin's own) may be read:\n got %q\nwant %q", got, want)
	}
}

func TestBwrapHidesTheDataFolderAfterTheReads(t *testing.T) {
	data := "/srv/chimera"
	plug, run := data+"/plugins/x", data+"/plugin-runs/x-1"
	argv := strings.Join(bwrapArgs("bwrap", "python3", []string{"run.py"}, []string{"/srv", plug, "/usr"}, []string{run}, []string{data}, false), " ")
	order := []string{"--tmpfs /home", "--ro-bind /srv /srv", "--ro-bind /usr /usr", "--tmpfs " + data, "--ro-bind " + plug + " " + plug, "--bind " + run + " " + run, "--chdir " + run + " -- python3 run.py"}
	at := -1
	for _, o := range order {
		i := strings.Index(argv, o)
		if i <= at {
			t.Fatalf("bwrap mounts out of order at %q (a folder the plugin reads contains the data folder):\n%s", o, argv)
		}
		at = i
	}
	if strings.Count(argv, "--ro-bind /srv ") != 1 || strings.Count(argv, "--ro-bind "+plug) != 1 {
		t.Fatalf("each folder is bound once:\n%s", argv)
	}
}

// A Head that talks to a server on this computer gets loopback only on macOS,
// and keeps the network namespace under bubblewrap; everything else stays shut.
func TestLocalhostNetworkSandbox(t *testing.T) {
	p := macPluginSandboxProfile("/usr/bin/python3", nil, []string{t.TempDir()}, nil, true)
	if !strings.Contains(p, "(deny network*)") || !strings.Contains(p, `(allow network* (remote ip "localhost:*"))`) {
		t.Fatalf("macOS profile should deny the network then allow localhost only:\n%s", p)
	}
	off := macPluginSandboxProfile("/usr/bin/python3", nil, []string{t.TempDir()}, nil, false)
	if strings.Contains(off, "localhost") {
		t.Fatalf("a Head without network: localhost must get no loopback rule:\n%s", off)
	}
	argv := strings.Join(bwrapArgs("bwrap", "python3", []string{"run.py"}, nil, []string{t.TempDir()}, nil, true), " ")
	if !strings.Contains(argv, "--unshare-all --die-with-parent --new-session --share-net") {
		t.Fatalf("bwrap should share the network for a localhost Head: %s", argv)
	}
	plain := strings.Join(bwrapArgs("bwrap", "python3", []string{"run.py"}, nil, []string{t.TempDir()}, nil, false), " ")
	if strings.Contains(plain, "--share-net") {
		t.Fatalf("bwrap must not share the network for an ordinary Head: %s", plain)
	}
}

// Words-only requests keep the words that name what a Head makes; with a picture
// attached those words are noise.
func TestPluginTermsWithAndWithoutInput(t *testing.T) {
	with := strings.Join(pluginTerms("add a shadow to this picture", true), " ")
	if strings.Contains(with, "picture") || !strings.Contains(with, "shadow") {
		t.Fatalf("with a picture, 'picture' is noise: %q", with)
	}
	without := strings.Join(pluginTerms("generate an image of a red car", false), " ")
	if !strings.Contains(without, "image") || !strings.Contains(without, "generate") {
		t.Fatalf("without a picture, 'image' is the point: %q", without)
	}
}

// A 3D-mesh Head's .glb must survive the asker's "does it make what it said" filter: by bytes
// alone a GLB is just octet-stream, so the name's extension has to count.
func TestMeshFilesKeepTheirType(t *testing.T) {
	glb := append([]byte("glTF\x02\x00\x00\x00"), make([]byte, 64)...)
	if m := sniffMIME("mesh.glb", glb); m != "model/gltf-binary" {
		t.Fatalf("sniffMIME(mesh.glb) = %q", m)
	}
	if !acceptsType([]string{"model/gltf-binary"}, sniffMIME("mesh.glb", glb)) {
		t.Fatal("a Head that produces model/gltf-binary should keep its .glb")
	}
	if acceptsType([]string{"model/gltf-binary"}, sniffMIME("mesh.glb", []byte("\x89PNG\r\n\x1a\n"))) {
		t.Fatal("a PNG claiming to be a mesh must still be refused")
	}
}

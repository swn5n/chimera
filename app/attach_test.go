package main

import (
	"archive/zip"
	"bytes"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"image"
	"image/color"
	"image/jpeg"
	"image/png"
	"math"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestAttachedPathsStayInTheFolderAndKeepTheirNames(t *testing.T) {
	for in, want := range map[string]string{
		"logo.png":                             "logo.png",
		"Raka/Backing Photos/hero (5).png":     "Raka/Backing Photos/hero (5).png", // names stay as they are
		`site\img\a.png`:                       "site/img/a.png",
		"a/./b//c.txt":                         "a/b/c.txt",
		"Backing Photos : Headers : etc/x.png": "Backing Photos - Headers - etc/x.png", // ":" can read as a web address's scheme
		"what?#100%.png":                       "what--100-.png",
		"/abs/path.png":                        "abs/path.png",
	} {
		got, err := cleanAttachPath(in)
		if err != nil || got != want {
			t.Errorf("%q: %q %v, want %q", in, got, err, want)
		}
	}
	for _, bad := range []string{"../x.png", "a/../../b.png", ".DS_Store", "site/.git/config", "", "///", strings.Repeat("a/", 17) + "x"} {
		if got, err := cleanAttachPath(bad); err == nil {
			t.Errorf("%q should be refused, got %q", bad, got)
		}
	}
	if got, _ := cleanAttachPath(strings.Repeat("n", 140) + ".webp"); len(got) != 100 || !strings.HasSuffix(got, ".webp") {
		t.Errorf("a long name: %q", got)
	}
}

// stage puts bytes where an upload would, and returns its id.
func stage(t *testing.T, dir string, data []byte) string {
	t.Helper()
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	id := randomID(12)
	if err := os.WriteFile(filepath.Join(dir, id), data, 0o600); err != nil {
		t.Fatal(err)
	}
	return id
}

func TestAttachedFilesLandInTheFolderOnceEach(t *testing.T) {
	up, folder := t.TempDir(), t.TempDir()
	if err := os.WriteFile(filepath.Join(folder, "same.txt"), []byte("same"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(folder, "taken.txt"), []byte("someone else's"), 0o644); err != nil {
		t.Fatal(err)
	}
	files, err := placeAttachments(up, folder, []chatAttachment{
		{Upload: stage(t, up, []byte("new")), Path: "site/new.txt"},
		{Upload: stage(t, up, []byte("same")), Path: "same.txt"},      // already there with these bytes: used as it is
		{Upload: stage(t, up, []byte("mine")), Path: "taken.txt"},     // a different file of that name stays
		{Upload: stage(t, up, []byte("again")), Path: "site/new.txt"}, // the same path twice in one message
		{Upload: stage(t, up, []byte("odd")), Path: "a:b.txt"},
	})
	if err != nil {
		t.Fatal(err)
	}
	var paths []string
	for _, f := range files {
		paths = append(paths, f.Path)
	}
	if got := strings.Join(paths, " "); got != "site/new.txt same.txt taken-2.txt site/new-2.txt a-b.txt" {
		t.Fatalf("paths: %s", got)
	}
	if files[4].Name != "a:b.txt" || files[0].Name != "" {
		t.Errorf("names: %+v", files)
	}
	for p, want := range map[string]string{"site/new.txt": "new", "same.txt": "same", "taken.txt": "someone else's", "taken-2.txt": "mine", "site/new-2.txt": "again"} {
		if b, _ := os.ReadFile(filepath.Join(folder, p)); string(b) != want {
			t.Errorf("%s holds %q, want %q", p, b, want)
		}
	}
	if left, _ := os.ReadDir(up); len(left) != 0 {
		t.Errorf("%d uploads left behind", len(left))
	}
	if st, _ := os.Stat(filepath.Join(folder, "site/new.txt")); st.Mode().Perm() != 0o644 {
		t.Errorf("mode %v", st.Mode())
	}

	// A file that never arrived: nothing moves.
	keep := stage(t, up, []byte("x"))
	if _, err := placeAttachments(up, folder, []chatAttachment{{Upload: keep, Path: "k.txt"}, {Upload: "0123456789ab", Path: "gone.txt"}}); err == nil {
		t.Fatal("a missing upload should be refused")
	}
	if fileExists(filepath.Join(folder, "k.txt")) || !fileExists(filepath.Join(up, keep)) {
		t.Error("a refused message moved some of its files")
	}
	// A folder in the chat's folder that links out of it isn't followed.
	outside := t.TempDir()
	if err := os.Symlink(outside, filepath.Join(folder, "out")); err != nil {
		t.Fatal(err)
	}
	if _, err := placeAttachments(up, folder, []chatAttachment{{Upload: keep, Path: "out/x.txt"}}); err == nil {
		t.Fatal("a path through a link out of the folder should be refused")
	}
	if fileExists(filepath.Join(outside, "x.txt")) {
		t.Fatal("a file landed outside the chat's folder")
	}
}

func pngOf(t *testing.T, img image.Image) []byte {
	t.Helper()
	var b bytes.Buffer
	if err := png.Encode(&b, img); err != nil {
		t.Fatal(err)
	}
	return b.Bytes()
}

// cutout is a picture with a clear border and a solid middle.
func cutout(w, h int) *image.NRGBA {
	img := image.NewNRGBA(image.Rect(0, 0, w, h))
	for y := h / 4; y < h*3/4; y++ {
		for x := w / 4; x < w*3/4; x++ {
			img.Set(x, y, color.NRGBA{255, 106, 0, 255})
		}
	}
	return img
}

// jpegTurned is a JPEG of w × h whose EXIF says to turn it a quarter (as a phone held upright writes).
func jpegTurned(t *testing.T, w, h int) []byte {
	t.Helper()
	var b bytes.Buffer
	if err := jpeg.Encode(&b, image.NewGray(image.Rect(0, 0, w, h)), nil); err != nil {
		t.Fatal(err)
	}
	tiff := []byte("MM\x00\x2a\x00\x00\x00\x08\x00\x01\x01\x12\x00\x03\x00\x00\x00\x01\x00\x06\x00\x00\x00\x00\x00\x00")
	app1 := append([]byte("Exif\x00\x00"), tiff...)
	seg := []byte{0xFF, 0xE1, byte((len(app1) + 2) >> 8), byte(len(app1) + 2)}
	j := b.Bytes()
	return append(append(append([]byte{}, j[:2]...), append(seg, app1...)...), j[2:]...)
}

func glbOf(t *testing.T, doc map[string]any) []byte {
	t.Helper()
	js, _ := json.Marshal(doc)
	for len(js)%4 != 0 {
		js = append(js, ' ')
	}
	bin := make([]byte, 8)
	var b bytes.Buffer
	b.WriteString("glTF")
	binary.Write(&b, binary.LittleEndian, uint32(2))
	binary.Write(&b, binary.LittleEndian, uint32(12+8+len(js)+8+len(bin)))
	binary.Write(&b, binary.LittleEndian, uint32(len(js)))
	b.WriteString("JSON")
	b.Write(js)
	binary.Write(&b, binary.LittleEndian, uint32(len(bin)))
	b.WriteString("BIN\x00")
	b.Write(bin)
	return b.Bytes()
}

func mp4Box(typ string, body ...[]byte) []byte {
	b := bytes.Join(body, nil)
	out := make([]byte, 8, 8+len(b))
	binary.BigEndian.PutUint32(out, uint32(8+len(b)))
	copy(out[4:], typ)
	return append(out, b...)
}

// phoneVideo is an MP4 of 1920 × 1080 filmed upright (its matrix turns it), 12.5 s long.
func phoneVideo() []byte {
	mvhd := make([]byte, 100)
	binary.BigEndian.PutUint32(mvhd[12:], 1000)
	binary.BigEndian.PutUint32(mvhd[16:], 12500)
	tkhd := make([]byte, 84)
	binary.BigEndian.PutUint32(tkhd[44:], 0x00010000) // b: a quarter turn
	binary.BigEndian.PutUint32(tkhd[52:], 0xFFFF0000) // c
	binary.BigEndian.PutUint32(tkhd[72:], 0x40000000) // w
	binary.BigEndian.PutUint32(tkhd[76:], 1920<<16)
	binary.BigEndian.PutUint32(tkhd[80:], 1080<<16)
	return bytes.Join([][]byte{
		mp4Box("ftyp", []byte("isom\x00\x00\x02\x00isomiso2mp41")),
		mp4Box("mdat", make([]byte, 64)),
		mp4Box("moov", mp4Box("mvhd", mvhd), mp4Box("trak", mp4Box("tkhd", tkhd))),
	}, nil)
}

func zipOf(t *testing.T, files map[string]string) []byte {
	t.Helper()
	var b bytes.Buffer
	z := zip.NewWriter(&b)
	for name, body := range files {
		w, _ := z.Create(name)
		w.Write([]byte(body))
	}
	z.Close()
	return b.Bytes()
}

func TestTheModelIsToldWhatEachFileIs(t *testing.T) {
	folder := t.TempDir()
	write := func(rel string, data []byte) AttachedFile {
		p := filepath.Join(folder, filepath.FromSlash(rel))
		os.MkdirAll(filepath.Dir(p), 0o755)
		if err := os.WriteFile(p, data, 0o644); err != nil {
			t.Fatal(err)
		}
		return AttachedFile{Path: rel, Bytes: int64(len(data))}
	}
	opaque := image.NewRGBA(image.Rect(0, 0, 30, 20))
	for i := range opaque.Pix {
		opaque.Pix[i] = 200
		if i%4 == 3 {
			opaque.Pix[i] = 255
		}
	}
	stl := make([]byte, 84+100)
	binary.LittleEndian.PutUint32(stl[80:], 2)
	for k, v := range []float32{0, 0, 0, 10, 0, 0, 0, 20, 5} { // the first triangle's corners (after its normal)
		binary.LittleEndian.PutUint32(stl[84+12+4*k:], math.Float32bits(v))
	}
	wav := []byte("RIFF\x00\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x02\x00\x44\xac\x00\x00\x10\xb1\x02\x00\x04\x00\x10\x00data\x20\x62\x05\x00")
	heic := append(mp4Box("ftyp", []byte("heic\x00\x00\x00\x00mif1heic")), mp4Box("meta", append([]byte("\x00\x00\x00\x14ispe\x00\x00\x00\x00"), 0, 0, 0x0f, 0xc0, 0, 0, 0x0b, 0xd0))...)
	webp := []byte("RIFF\x16\x00\x00\x00WEBPVP8X\x0a\x00\x00\x00\x10\x00\x00\x00\x1f\x03\x00\x57\x02\x00")
	glb := glbOf(t, map[string]any{
		"asset":  map[string]any{"version": "2.0"},
		"scene":  0,
		"scenes": []any{map[string]any{"nodes": []int{0}}},
		// scaled 2, turned a quarter about y, moved 10 along x
		"nodes":              []any{map[string]any{"mesh": 0, "scale": []float64{2, 2, 2}, "rotation": []float64{0, 0.70710678, 0, 0.70710678}, "translation": []float64{10, 0, 0}}},
		"meshes":             []any{map[string]any{"primitives": []any{map[string]any{"attributes": map[string]int{"POSITION": 0}, "indices": 1}}}},
		"accessors":          []any{map[string]any{"count": 8, "min": []float64{-1, 0, -0.5}, "max": []float64{1, 2, 0.5}}, map[string]any{"count": 36}, map[string]any{"count": 30, "max": []float64{2.5}}},
		"materials":          []any{map[string]any{}},
		"images":             []any{map[string]any{"bufferView": 0}},
		"animations":         []any{map[string]any{"name": "Spin", "samplers": []any{map[string]any{"input": 2}}}},
		"extensionsRequired": []string{"KHR_draco_mesh_compression"},
	})
	files := []AttachedFile{
		write("logo.png", pngOf(t, cutout(40, 20))),
		write("photo.png", pngOf(t, opaque)),
		write("phone.jpg", jpegTurned(t, 40, 20)),
		write("hero.webp", webp),
		write("mark.svg", []byte(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 40"><rect width="120" height="40" fill="#ff6a00"/></svg>`)),
		write("models/excavator.glb", glb),
		write("models/scene.gltf", []byte(`{"asset":{"version":"2.0"},"buffers":[{"uri":"scene.bin"}],"images":[{"uri":"tex%20a.png"}]}`)),
		write("models/tex a.png", pngOf(t, opaque)),
		write("models/m.mtl", []byte("newmtl paint\nKd 1 0.4 0\nmap_Kd tex a.png\nnewmtl glass\nmap_Bump -bm 0.5 missing.png\n")),
		write("models/box.obj", []byte("mtllib m.mtl\no box\nv 0 0 0\nv 2 0 0\nv 2 1 0\nv 0 1 3\nusemtl paint\nf 1 2 3 4\nf 1 2 3\n")),
		write("models/lone.obj", []byte("mtllib lone.mtl\nv 0 0 0\nv 1 1 1\nv 1 0 0\nf 1 2 3\n")),
		write("models/part.stl", stl),
		write("clip.mp4", phoneVideo()),
		write("ding.wav", wav),
		write("IMG_0339.HEIC", heic),
		write("prices.csv", []byte("size,price\nsmall,10\nlarge,20\n")),
		write("notes.txt", []byte("Phone: 888-404-RAKA\nOpen 7-5\n")),
		write("sheet.numbers", zipOf(t, map[string]string{"Index/Document.iwa": "x"})),
		write("about.docx", zipOf(t, map[string]string{"word/document.xml": `<w:document><w:body><w:p><w:r><w:t>Raka Rentals</w:t></w:r></w:p><w:p><w:r><w:t xml:space="preserve">Lifts &amp; loaders</w:t></w:r></w:p></w:body></w:document>`})),
		write("brochure.pdf", []byte("%PDF-1.7\n")),
	}
	for i := 0; i < 6; i++ { // a turn of six frames
		files = append(files, write("frames/f0"+string(rune('0'+i))+".png", pngOf(t, cutout(8, 8))))
	}
	files, note := describeAttachments(folder, files, 20000)
	if len(files) != 26 {
		t.Fatalf("%d files", len(files))
	}
	for _, want := range []string{
		"Attached files: 26 (",
		"copied into this chat's folder, " + folder + ".",
		"(a path with spaces or brackets works as it is in HTML and in a script; in CSS, put it in quotes",
		"- `logo.png`: picture, PNG, 40 × 20, transparent background, ",
		"- `photo.png`: picture, PNG, 30 × 20, " + humanBytes(files[1].Bytes) + "\n", // opaque: nothing said about see-through
		"- `phone.jpg`: picture, JPEG, 20 × 40, ",                                    // shown upright
		"- `hero.webp`: picture, WebP, 800 × 600, with transparency, 30 bytes",
		"- `mark.svg`: picture, SVG, 120 × 40, ",
		"- `models/excavator.glb`: 3D model, glTF binary (.glb), ",
		"1 mesh, 12 triangles, 1 material, 1 texture inside the file, animation: \"Spin\" (2.5 s); about 2 × 4 × 4 m (x × y × z), from (9, 0, -2) to (11, 4, 2), y up. A browser shows it only through a 3D library (three.js's GLTFLoader, for one). Its meshes are Draco-compressed",
		"It needs scene.bin beside it, which wasn't attached",
		"- `models/m.mtl`: 3D model, OBJ materials (.mtl), ",
		"2 materials; its textures: `models/tex a.png`. It names missing.png, which wasn't attached",
		"- `models/box.obj`: 3D model, OBJ, ",
		"4 vertices, 3 triangles, 1 material; spans 2 × 1 × 3 (x × y × z), from (0, 0, 0) to (2, 1, 3) (OBJ doesn't store its units: often metres, y up); its materials are in `models/m.mtl`",
		"It names lone.mtl for its materials, which wasn't attached, so it would show without its colours and textures",
		"- `models/part.stl`: 3D model, STL, 184 bytes. 2 triangles; spans 10 × 20 × 5 (x × y × z)",
		"- `clip.mp4`: video, MP4, 1080 × 1920, 12.5 s, ",
		"- `ding.wav`: sound, WAV, 2 s, ",
		"- `IMG_0339.HEIC`: picture, HEIC, 4032 × 3024, ",
		"Only Safari shows HEIC",
		"- `prices.csv`: text, CSV, 29 bytes. 3 lines",
		"- `sheet.numbers`: document, Numbers, ",
		"export it as CSV",
		"- `brochure.pdf`: document, PDF, 9 bytes. A page can link to it",
		"- `frames/f00.png` to `frames/f05.png`: 6 pictures, PNG, 8 × 8, transparent background, ",
		"numbered 00 to 05",
		"The text files' words:",
		"`notes.txt`:\n~~~text\nPhone: 888-404-RAKA\nOpen 7-5\n~~~",
		"`prices.csv`:\n~~~csv\nsize,price",
		"`about.docx`:\n~~~text\nRaka Rentals\nLifts & loaders\n~~~",
		"`models/m.mtl`:\n~~~text\nnewmtl paint",
		"`mark.svg`:\n~~~xml\n<svg",
		"Only these facts about the pictures come with this message, not what they show.",
	} {
		if !strings.Contains(note, want) {
			t.Errorf("the note lacks %q", want)
		}
	}
	if strings.Contains(note, "`frames/f01.png`") {
		t.Error("the frames weren't put on one line")
	}
	if strings.Contains(note, "`models/box.obj`:\n~~~") {
		t.Error("an OBJ's numbers went to the model as text")
	}
	if t.Failed() {
		t.Log(note)
	}
	kinds := map[string]string{}
	for _, f := range files {
		kinds[f.Path] = f.Kind
	}
	if kinds["logo.png"] != "picture" || kinds["models/excavator.glb"] != "3d" || kinds["notes.txt"] != "text" || kinds["clip.mp4"] != "video" {
		t.Errorf("kinds: %v", kinds)
	}
	if files[2].Width != 20 || files[2].Height != 40 {
		t.Errorf("phone.jpg: %d × %d", files[2].Width, files[2].Height)
	}
}

func TestALongTextFileIsCutAtItsBudget(t *testing.T) {
	folder := t.TempDir()
	var long strings.Builder
	for i := 0; i < 2000; i++ {
		long.WriteString("row ")
		long.WriteString(strings.Repeat("x", 40))
		long.WriteString("\n")
	}
	os.WriteFile(filepath.Join(folder, "big.txt"), []byte(long.String()), 0o644)
	os.WriteFile(filepath.Join(folder, "small.txt"), []byte("tiny"), 0o644)
	files := []AttachedFile{{Path: "big.txt", Bytes: int64(long.Len())}, {Path: "small.txt", Bytes: 4}}
	_, note := describeAttachments(folder, files, 5000)
	if !strings.Contains(note, "`big.txt` (its first 1") || !strings.Contains(note, "of 2,000 lines; a page can load all of it from its path)") {
		t.Errorf("the cut isn't said:\n%s", note[:min(len(note), 600)])
	}
	if !strings.Contains(note, "`small.txt`: not included, since this message has a lot of text already") {
		t.Errorf("the file past the budget isn't named:\n%s", note[len(note)-400:])
	}
	if len(note) > 7000 {
		t.Errorf("the note is %d characters for a budget of 5,000", len(note))
	}
	os.WriteFile(filepath.Join(folder, "app.min.js"), []byte(strings.Repeat("a=1;", 3000)), 0o644)
	_, note = describeAttachments(folder, []AttachedFile{{Path: "app.min.js", Bytes: 12000}}, 5000)
	if !strings.Contains(note, "`app.min.js` (its first 5,000 of 12,000 characters;") {
		t.Errorf("a one-line file's cut:\n%s", note[:min(len(note), 500)])
	}
}

func TestOnlyTheFirstLinesOfAHugeListAreWritten(t *testing.T) {
	folder := t.TempDir()
	var files []AttachedFile
	for i := 0; i < attachListMax+50; i++ {
		name := filepath.Join(folder, "pics", randomID(4)+".bin")
		os.MkdirAll(filepath.Dir(name), 0o755)
		os.WriteFile(name, []byte{0, 1, 2}, 0o644)
		files = append(files, AttachedFile{Path: "pics/" + filepath.Base(name), Bytes: 3})
	}
	_, note := describeAttachments(folder, files, 1000)
	if n := strings.Count(note, "\n- `"); n != attachListMax {
		t.Errorf("%d lines listed", n)
	}
	if !strings.Contains(note, "- and 50 more not listed here (50 files; 150 bytes), in `pics/` (50)") {
		t.Errorf("the rest aren't counted:\n%s", note[len(note)-300:])
	}
}

func TestUploadsKeepFilesUntilTheyreSent(t *testing.T) {
	a := NewApp(t.TempDir(), 0, 0, "http://127.0.0.1:1")
	mux := http.NewServeMux()
	mux.HandleFunc("POST /api/uploads", a.handleUpload)
	post := func(name, body string) *httptest.ResponseRecorder {
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, httptest.NewRequest("POST", "/api/uploads?name="+url.QueryEscape(name), strings.NewReader(body)))
		return w
	}
	w := post("site/a.txt", "hello")
	var r struct {
		ID    string `json:"id"`
		Bytes int64  `json:"bytes"`
	}
	if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &r) != nil || r.Bytes != 5 || !validID(r.ID) {
		t.Fatalf("%d %s", w.Code, w.Body)
	}
	if b, _ := os.ReadFile(filepath.Join(a.uploadDir(), r.ID)); string(b) != "hello" {
		t.Fatalf("kept %q", b)
	}
	for _, bad := range []string{"../a.txt", ".env", ""} {
		if w := post(bad, "x"); w.Code != 400 {
			t.Errorf("%q: %d", bad, w.Code)
		}
	}
	old := filepath.Join(a.uploadDir(), "aaaaaaaaaaaa")
	os.WriteFile(old, []byte("x"), 0o600)
	when := time.Now().Add(-25 * time.Hour)
	os.Chtimes(old, when, when)
	sweepUploads(a.uploadDir(), uploadKeep)
	if fileExists(old) || !fileExists(filepath.Join(a.uploadDir(), r.ID)) {
		t.Error("the sweep should take only what's over a day old")
	}
}

// waitSaved waits for a reply to be saved in its chat (waitFinal's pause can be
// too short on a busy machine, and the next message is refused until then).
func waitSaved(t *testing.T, a *App, gen *generation) {
	t.Helper()
	waitFinal(t, gen)
	for end := time.Now().Add(10 * time.Second); time.Now().Before(end); time.Sleep(20 * time.Millisecond) {
		sess, err := a.sessions.Get(gen.sessionID)
		if err != nil {
			t.Fatal(err)
		}
		pending := false
		for _, m := range sess.Messages {
			pending = pending || m.Status == "pending"
		}
		if !pending {
			return
		}
	}
	t.Fatal("the reply was never saved")
}

func TestAnEngineChatGetsItsFilesInItsFolder(t *testing.T) {
	home := t.TempDir()
	os.MkdirAll(filepath.Join(home, "Documents"), 0o755)
	t.Setenv("HOME", home)
	a, logPath := engineApp(t, nil)
	mux := http.NewServeMux()
	mux.HandleFunc("POST /api/uploads", a.handleUpload)
	mux.HandleFunc("GET /api/sessions/{id}/attached/{path...}", a.serveAttached)
	up := func(name string, data []byte) chatAttachment {
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, httptest.NewRequest("POST", "/api/uploads?name="+url.QueryEscape(name), bytes.NewReader(data)))
		var r struct{ ID string }
		if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &r) != nil {
			t.Fatalf("upload %s: %d %s", name, w.Code, w.Body)
		}
		return chatAttachment{Upload: r.ID, Path: name}
	}
	logo := pngOf(t, cutout(40, 20))
	if _, err := a.gens.Start(chatReq{Message: "x", Model: "gemma4:12b", Attachments: []chatAttachment{up("a.txt", []byte("a"))}}); err == nil || !strings.Contains(err.Error(), "this computer's own models") {
		t.Fatalf("files for a model of the network: %v", err)
	}
	gen, err := a.gens.Start(chatReq{Message: "Build a page with my logo", Model: "engine:fake", Thinking: "off",
		Attachments: []chatAttachment{up("site/logo.png", logo), up("site/notes.txt", []byte("Phone: 888-404-RAKA\n"))}})
	if err != nil {
		t.Fatal(err)
	}
	waitSaved(t, a, gen)
	sess, _ := a.sessions.Get(gen.sessionID)
	if r := sess.Messages[1]; r.Status != "" || r.Content != "Hello there." {
		t.Fatalf("the reply: %+v", r)
	}
	want := filepath.Join(home, "Documents", "Chimera", "Build a page with my logo")
	if sess.Folder != want {
		t.Fatalf("folder %q, want %q", sess.Folder, want)
	}
	if b, _ := os.ReadFile(filepath.Join(want, "site", "logo.png")); !bytes.Equal(b, logo) {
		t.Fatal("the logo isn't in the chat's folder")
	}
	m := sess.Messages[0]
	if m.Content != "Build a page with my logo" || len(m.Attached) != 2 || m.AttachedIn != want ||
		!strings.Contains(m.FilesNote, "- `site/logo.png`: picture, PNG, 40 × 20, transparent background") || !strings.Contains(m.FilesNote, "Phone: 888-404-RAKA") {
		t.Fatalf("the message: %+v", m)
	}
	lastUser := func() string {
		msgs := lastRequest(t, logPath)["messages"].([]any)
		return msgs[len(msgs)-1].(map[string]any)["content"].(string)
	}
	firstUser := func() string {
		return lastRequest(t, logPath)["messages"].([]any)[0].(map[string]any)["content"].(string)
	}
	if got := lastUser(); got != "Build a page with my logo\n\n"+m.FilesNote {
		t.Fatalf("the engine got %q", got)
	}

	// Written again, changed, and later in the chat: the message keeps its files.
	g2, err := a.gens.Start(chatReq{SessionID: sess.ID, Regenerate: true, Model: "engine:fake"})
	if err != nil {
		t.Fatal(err)
	}
	waitSaved(t, a, g2)
	if got := lastUser(); got != "Build a page with my logo\n\n"+m.FilesNote {
		t.Fatalf("written again, the engine got %q", got)
	}
	zero := 0
	g3, err := a.gens.Start(chatReq{SessionID: sess.ID, Message: "Build it darker", Model: "engine:fake", EditAt: &zero})
	if err != nil {
		t.Fatal(err)
	}
	waitSaved(t, a, g3)
	if got := lastUser(); got != "Build it darker\n\n"+m.FilesNote {
		t.Fatalf("changed, the engine got %q", got)
	}
	g4, err := a.gens.Start(chatReq{SessionID: sess.ID, Message: "thanks", Model: "engine:fake"})
	if err != nil {
		t.Fatal(err)
	}
	waitSaved(t, a, g4)
	if got := firstUser(); !strings.HasSuffix(got, m.FilesNote) {
		t.Fatalf("later, the first message went as %q", got)
	}
	sess, _ = a.sessions.Get(sess.ID)
	if len(sess.Messages[0].Attached) != 2 || sess.Messages[0].Content != "Build it darker" {
		t.Fatalf("after the edit: %+v", sess.Messages[0])
	}

	// The same logo again uses the copy that's there; another file of that name gets a number.
	other := pngOf(t, cutout(8, 8))
	g5, err := a.gens.Start(chatReq{SessionID: sess.ID, Model: "engine:fake", Attachments: []chatAttachment{up("site/logo.png", logo), up("site/logo.png", other)}})
	if err != nil {
		t.Fatal(err)
	}
	waitSaved(t, a, g5)
	sess, _ = a.sessions.Get(sess.ID)
	last := sess.Messages[len(sess.Messages)-2]
	if len(last.Attached) != 2 || last.Attached[0].Path != "site/logo.png" || last.Attached[1].Path != "site/logo-2.png" || last.Content != "" {
		t.Fatalf("again: %+v", last)
	}
	if got := lastUser(); got != last.FilesNote {
		t.Fatalf("files alone went as %q", got)
	}

	// The chat page's thumbnails: pictures a message names, nothing else.
	get := func(p string) *httptest.ResponseRecorder {
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, httptest.NewRequest("GET", "/api/sessions/"+sess.ID+"/attached/"+p, nil))
		return w
	}
	if w := get("site/logo.png"); w.Code != 200 || w.Header().Get("Content-Type") != "image/png" || !strings.Contains(w.Header().Get("Content-Security-Policy"), "sandbox") {
		t.Fatalf("logo: %d %v", w.Code, w.Header())
	}
	for _, p := range []string{"site/notes.txt", "site/nothing.png"} {
		if w := get(p); w.Code != 404 {
			t.Errorf("%s: %d", p, w.Code)
		}
	}
	if w := get("../../x.png"); w.Code == 200 {
		t.Error("a path out of the folder was served")
	}
}

func TestTheChatsOwnFolderDroppedInIsUsedWhereItIs(t *testing.T) {
	up, folder := t.TempDir(), filepath.Join(t.TempDir(), "Raka site")
	os.MkdirAll(filepath.Join(folder, "img"), 0o755)
	os.WriteFile(filepath.Join(folder, "img", "a.png"), []byte("A"), 0o644)
	files, err := placeAttachments(up, folder, []chatAttachment{
		{Upload: stage(t, up, []byte("A")), Path: "Raka site/img/a.png"},   // the very file: used where it is
		{Upload: stage(t, up, []byte("B")), Path: "Raka site/img/new.png"}, // not there, so another folder of that name: copied
	})
	if err != nil {
		t.Fatal(err)
	}
	if files[0].Path != "img/a.png" || files[1].Path != "Raka site/img/new.png" {
		t.Fatalf("%+v", files)
	}
	if fileExists(filepath.Join(folder, "Raka site", "img", "a.png")) {
		t.Fatal("the folder was copied into itself")
	}
}

func TestBrokenFilesDontBreakTheList(t *testing.T) {
	folder := t.TempDir()
	png := pngOf(t, cutout(8, 8))
	heads := [][]byte{
		png[:20], png[:40], []byte("\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR"),
		[]byte("\xff\xd8\xff\xe1\x00\x02"), []byte("\xff\xd8\xff\xe1\xff\xffExif\x00\x00MM\x00\x2a\xff\xff\xff\xff"),
		[]byte("GIF89a\x01"), []byte("RIFF\x00\x00\x00\x00WEBPVP8X"), []byte("RIFF\x00\x00\x00\x00WEBPVP8L\x00\x00\x00\x00\x2f"),
		[]byte("RIFF\x00\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x02\x00\x44\xac\x00\x00\x10"), // cut inside its fmt chunk []byte("RIFF\x00\x00\x00\x00WAVEdata\xff\xff\xff\xff"),
		[]byte("\x00\x00\x00\x18ftypisom"), []byte("\xff\xff\xff\xffftypqt  \x00\x00\x00\x00"), mp4Box("ftyp", []byte("isom")), append(mp4Box("ftyp", []byte("isom")), mp4Box("moov", mp4Box("trak", mp4Box("tkhd", make([]byte, 90))), mp4Box("mvhd", make([]byte, 8)))...),
		[]byte("glTF\x02\x00\x00\x00"), []byte("glTF\x02\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\x7fJSON"), []byte("glTF\x02\x00\x00\x00\x00\x00\x00\x00\x10\x00\x00\x00JSON{\"nodes\":[{\"children\":[0]}]}"),
		[]byte("BM\x00"), []byte("8BPS\x00"), []byte("Kaydara FBX Binary  \x00"), []byte("ply\nelement vertex x\nend_header"), []byte("PK\x03\x04broken"),
		[]byte("solid x\nvertex 1\nfacet"), make([]byte, 84), []byte("v 1 2\nf 1\nmtllib\nusemtl"), []byte("newmtl\nmap_Kd\nmap_Kd -bm"),
		[]byte(`{"nodes":[{"mesh":5,"children":[0,1,-3]}],"meshes":[{"primitives":[{"attributes":{"POSITION":9},"indices":-1}]}],"scenes":[{"nodes":[0]}],"scene":7}`),
		[]byte("<svg width='x' viewBox='0 0'>"), {0xff, 0xfe, 0x00}, {},
	}
	var files []AttachedFile
	for i, h := range heads {
		for _, ext := range []string{".png", ".jpg", ".gif", ".webp", ".wav", ".mp4", ".mov", ".heic", ".glb", ".gltf", ".obj", ".mtl", ".stl", ".ply", ".fbx", ".docx", ".zip", ".svg", ".bmp", ".txt"} {
			name := fmt.Sprintf("b%02d%s", i, ext)
			os.WriteFile(filepath.Join(folder, name), h, 0o644)
			files = append(files, AttachedFile{Path: name, Bytes: int64(len(h))})
		}
	}
	for i := 0; i < 200; i++ { // and random bytes under every name
		b := []byte(randomID(1 + i%40))
		name := fmt.Sprintf("r%03d%s", i, []string{".glb", ".mp4", ".png", ".webp", ".jpg", ".stl", ".obj"}[i%7])
		os.WriteFile(filepath.Join(folder, name), b, 0o644)
		files = append(files, AttachedFile{Path: name, Bytes: int64(len(b))})
	}
	_, note := describeAttachments(folder, files, 20000) // it must not panic
	if !strings.HasPrefix(note, "Attached files: ") {
		t.Fatalf("%.200s", note)
	}
}

package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"hash/crc32"
	"image"
	"image/color"
	"image/gif"
	"image/jpeg"
	"image/png"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// logoOn is a w × h picture: see-through, with a solid block of c in the middle.
func logoOn(w, h int, c color.NRGBA) *image.NRGBA {
	img := image.NewNRGBA(image.Rect(0, 0, w, h))
	for y := h / 4; y < 3*h/4; y++ {
		for x := w / 4; x < 3*w/4; x++ {
			img.SetNRGBA(x, y, c)
		}
	}
	return img
}

func flat(w, h int, c color.NRGBA) *image.NRGBA {
	img := image.NewNRGBA(image.Rect(0, 0, w, h))
	for i := 0; i < len(img.Pix); i += 4 {
		img.Pix[i], img.Pix[i+1], img.Pix[i+2], img.Pix[i+3] = c.R, c.G, c.B, c.A
	}
	return img
}

func jpegBytes(t *testing.T, img image.Image) []byte {
	t.Helper()
	var b bytes.Buffer
	if err := jpeg.Encode(&b, img, &jpeg.Options{Quality: 90}); err != nil {
		t.Fatal(err)
	}
	return b.Bytes()
}

func copyFor(t *testing.T, dir, name string, data []byte) (image.Image, string, string, error) {
	t.Helper()
	p := filepath.Join(dir, name)
	if err := os.WriteFile(p, data, 0o644); err != nil {
		t.Fatal(err)
	}
	x := readFacts(p, name, int64(len(data)), func(string) bool { return false })
	out, filled, tone, err := visionCopy(context.Background(), p, x)
	if err != nil {
		return nil, filled, tone, err
	}
	img, err := jpeg.Decode(bytes.NewReader(out))
	if err != nil {
		t.Fatalf("%s: the copy isn't a JPEG: %v", name, err)
	}
	return img, filled, tone, nil
}

func TestTheVisionModelSeesASmallCopyOnAGreyThatStandsOut(t *testing.T) {
	dir := t.TempDir()
	// A white logo on a clear background: on dark grey, and it's light.
	img, filled, tone, err := copyFor(t, dir, "white.png", pngOf(t, logoOn(2000, 1000, color.NRGBA{255, 255, 255, 255})))
	if err != nil || filled != "dark" || tone != "light" || img.Bounds().Dx() != 1024 || img.Bounds().Dy() != 512 {
		t.Fatalf("white logo: %v %q %q %v", err, filled, tone, img.Bounds())
	}
	if r, _, _, _ := img.At(5, 5).RGBA(); r>>8 > 70 {
		t.Errorf("white logo: its corner is %d, not dark grey", r>>8)
	}
	if r, _, _, _ := img.At(512, 256).RGBA(); r>>8 < 230 {
		t.Errorf("white logo: its middle is %d, not white", r>>8)
	}
	// A black one: on light grey, and it's dark.
	img, filled, tone, err = copyFor(t, dir, "black.png", pngOf(t, logoOn(400, 200, color.NRGBA{0, 0, 0, 255})))
	if err != nil || filled != "light" || tone != "dark" || img.Bounds().Dx() != 400 {
		t.Fatalf("black logo: %v %q %q %v", err, filled, tone, img.Bounds())
	}
	if r, _, _, _ := img.At(3, 3).RGBA(); r>>8 < 190 {
		t.Errorf("black logo: its corner is %d, not light grey", r>>8)
	}
	// A photo with nothing see-through is only shrunk (never enlarged), and measured.
	img, filled, tone, err = copyFor(t, dir, "photo.jpg", jpegBytes(t, flat(300, 200, color.NRGBA{120, 130, 125, 255})))
	if err != nil || filled != "" || tone != "mid-toned" || img.Bounds().Dx() != 300 || img.Bounds().Dy() != 200 {
		t.Fatalf("photo: %v %q %q %v", err, filled, tone, img.Bounds())
	}
	pal := image.NewPaletted(image.Rect(0, 0, 50, 50), []color.Color{color.Black, color.White})
	var g bytes.Buffer
	gif.Encode(&g, pal, nil)
	if _, _, tone, err = copyFor(t, dir, "dark.gif", g.Bytes()); err != nil || tone != "dark" {
		t.Fatalf("gif: %v %q", err, tone)
	}
	if _, _, _, err = copyFor(t, dir, "logo.svg", []byte(`<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>`)); err == nil {
		t.Fatal("an SVG can't be looked at")
	}
}

func TestAPhonePhotoIsSeenTheWayUp(t *testing.T) {
	// A 3 × 2 picture with every pixel its own: where each corner lands, per orientation.
	src := image.NewNRGBA(image.Rect(0, 0, 3, 2))
	for y := 0; y < 2; y++ {
		for x := 0; x < 3; x++ {
			src.SetNRGBA(x, y, color.NRGBA{R: uint8(10*x + y), A: 255})
		}
	}
	px := func(img *image.NRGBA, x, y int) int { return int(img.NRGBAAt(x, y).R) }
	tl, tr, bl := 0, 20, 1                  // the source's top-left, top-right and bottom-left
	for o, want := range map[int][3][2]int{ // where they go: {x, y} of each
		1: {{0, 0}, {2, 0}, {0, 1}},
		2: {{2, 0}, {0, 0}, {2, 1}},
		3: {{2, 1}, {0, 1}, {2, 0}},
		4: {{0, 1}, {2, 1}, {0, 0}},
		5: {{0, 0}, {0, 2}, {1, 0}},
		6: {{1, 0}, {1, 2}, {0, 0}},
		7: {{1, 2}, {1, 0}, {0, 2}},
		8: {{0, 2}, {0, 0}, {1, 2}},
	} {
		got := orient(src, o)
		for k, v := range []int{tl, tr, bl} {
			if p := px(got, want[k][0], want[k][1]); p != v {
				t.Errorf("orientation %d: corner %d is %d at %v", o, k, p, want[k])
			}
		}
	}
	// A JPEG that says to turn it a quarter reaches the model upright: taller than wide.
	dir := t.TempDir()
	img, _, _, err := copyFor(t, dir, "phone.jpg", jpegTurned(t, 400, 300))
	if err != nil || img.Bounds().Dx() != 300 || img.Bounds().Dy() != 400 {
		t.Fatalf("turned photo: %v %v", err, img)
	}
	// A header claiming more pixels than can be decoded is refused before decoding.
	big := pngOf(t, flat(4, 4, color.NRGBA{A: 255}))
	binary.BigEndian.PutUint32(big[16:], 100000)
	binary.BigEndian.PutUint32(big[20:], 100000)
	binary.BigEndian.PutUint32(big[29:], crc32.ChecksumIEEE(big[12:29])) // a header that reads, so only its size refuses it
	if c, err := png.DecodeConfig(bytes.NewReader(big)); err != nil || c.Width != 100000 {
		t.Fatalf("the made header doesn't read: %v", err)
	}
	os.WriteFile(filepath.Join(dir, "huge.png"), big, 0o644)
	if _, err := decodeFile(filepath.Join(dir, "huge.png")); err == nil || !strings.Contains(err.Error(), "here") {
		t.Fatalf("a 10-gigapixel header should be refused before decoding: %v", err)
	}
}

// On a Mac, sips reads what Go can't: here a TIFF, and an HEIC if this Mac can write one.
func TestSipsReadsWhatGoCant(t *testing.T) {
	if runtime.GOOS != "darwin" || !fileExists("/usr/bin/sips") {
		t.Skip("needs macOS's sips")
	}
	dir := t.TempDir()
	src := filepath.Join(dir, "src.png")
	os.WriteFile(src, pngOf(t, logoOn(1600, 800, color.NRGBA{250, 250, 250, 255})), 0o644)
	for _, f := range []string{"tiff", "heic"} {
		out := filepath.Join(dir, "pic."+f)
		if err := exec.Command("/usr/bin/sips", "-s", "format", f, src, "--out", out).Run(); err != nil {
			if f == "heic" {
				continue
			}
			t.Fatal(err)
		}
		x := readFacts(out, "pic."+f, 0, func(string) bool { return false })
		data, _, tone, err := visionCopy(context.Background(), out, x)
		if err != nil || tone != "light" {
			t.Fatalf("%s: %v %q", f, err, tone)
		}
		img, err := jpeg.Decode(bytes.NewReader(data))
		if err != nil || img.Bounds().Dx() != 1024 {
			t.Fatalf("%s: %v %v", f, err, img)
		}
	}
}

func TestWhatThePictureShowsReadsAsOneLine(t *testing.T) {
	var got map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewDecoder(r.Body).Decode(&got)
		w.Write([]byte(`{"message":{"role":"assistant","content":"{\"shows\":\"The RAKA Rentals logo, white letters with an orange R.\",\"kind\":\"logo\",\"words\":\"RAKA Rentals\",\"tone\":\"dark\",\"text_space\":\"Nowhere\"}"}}`))
	}))
	defer srv.Close()
	ans, err := askDescribe(context.Background(), NewOllamaClient(srv.URL), "qwen3.8:27b", []byte("\xff\xd8\xff"), "dark")
	if err != nil {
		t.Fatal(err)
	}
	msgs := got["messages"].([]any)
	user := msgs[1].(map[string]any)
	if got["model"] != "qwen3.8:27b" || got["think"] != false || got["format"] == nil || !strings.Contains(user["content"].(string), "filled with plain dark grey here") {
		t.Fatalf("request: %v", got)
	}
	if b, _ := base64.StdEncoding.DecodeString(user["images"].([]any)[0].(string)); !bytes.Equal(b, []byte("\xff\xd8\xff")) {
		t.Fatal("the picture didn't go as it was made")
	}
	// The measured tone wins over the model's.
	if line := showsLine(ans, "light"); line != `logo, light: The RAKA Rentals logo, white letters with an orange R; the words "RAKA Rentals"; no room for a heading on it` {
		t.Fatalf("line: %s", line)
	}
	if line := showsLine(describeAnswer{Shows: strings.Repeat("a long sentence ", 30), Kind: "nonsense", Tone: "mixed", Words: "", TextSpace: "The open sky at the top left."}, ""); !strings.HasPrefix(line, "picture, light and dark: a long sentence") ||
		!strings.Contains(line, "…; room for a heading: the open sky at the top left") || len(line) > 320 {
		t.Fatalf("long line: %s", line)
	}
}

func TestFreeMemoryIsReadFromVMStat(t *testing.T) {
	out := `Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                              100000.
Pages active:                            759421.
Pages inactive:                          200000.
Pages speculative:                        50000.
Pages throttled:                              0.
Pages wired down:                        900000.
Pages purgeable:                          10000.
`
	if n, ok := vmStatFree(out); !ok || n != 360000*16384 {
		t.Fatalf("%d %v", n, ok)
	}
	if _, ok := vmStatFree("nothing"); ok {
		t.Fatal("no page size, no answer")
	}
	if ok, _ := roomBeside(18e9, 30<<30, true); !ok {
		t.Error("18 GB fits in 30 free")
	}
	if ok, why := roomBeside(18e9, 12<<30, true); ok || !strings.Contains(why, "12 GB is free") {
		t.Errorf("18 GB in 12: %v %s", ok, why)
	}
	if ok, _ := roomBeside(1e9, 0, false); ok {
		t.Error("unknown memory is no room")
	}
	if runtime.GOOS == "darwin" {
		if n, ok := freeMemory(); !ok || n <= 0 {
			t.Errorf("this Mac's free memory: %d %v", n, ok)
		}
	}
}

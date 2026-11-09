package main

// What an attached file is, read from its own bytes: enough for a model that
// reads only text to use it in a page. Pictures give their size in pixels and
// whether they're cut out; videos and sounds their length; 3D models their
// parts and their size in the scene; text files their words (attach.go).

import (
	"archive/zip"
	"bufio"
	"bytes"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"image"
	"image/gif"
	"image/jpeg"
	"image/png"
	"io"
	"math"
	"net/url"
	"os"
	"path"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

type fileFacts struct {
	Kind          string // picture, text, 3d, video, audio, font, document, archive, other
	Format        string // "PNG", "glTF binary", …
	Width, Height int
	Alpha         string  // "transparent background", "with transparency"
	Frames        int     // an animated picture's frames
	Secs          float64 // a video's or a sound's length
	Detail        string  // more, in words: a 3D model's parts and size
	Warn          string  // what a browser can't do with it, and what would work
	Parts         string  // a 3D model's parts by name, for a page to find and move them
	Text          bool    // its words go to the model (read from the file as it is)
	Words         string  // or these words, read out of it (a Word file's)
}

const textMax = 8 << 20 // bigger text files are listed, not read

// readFacts says what the file at full is (rel is its path in the chat's folder;
// has says whether the folder holds another path, for the files a model names).
func readFacts(full, rel string, size int64, has func(string) bool) fileFacts {
	ext := strings.ToLower(path.Ext(rel))
	head := readHead(full, 64<<10)
	switch {
	case bytes.HasPrefix(head, []byte("\x89PNG\r\n\x1a\n")):
		return pngFacts(full, head, size)
	case len(head) > 3 && head[0] == 0xFF && head[1] == 0xD8 && head[2] == 0xFF:
		return jpegFacts(full, head)
	case bytes.HasPrefix(head, []byte("GIF87a")) || bytes.HasPrefix(head, []byte("GIF89a")):
		return gifFacts(full, size)
	case len(head) >= 16 && string(head[0:4]) == "RIFF" && string(head[8:12]) == "WEBP":
		return webpFacts(full, head)
	case len(head) >= 12 && string(head[0:4]) == "RIFF" && string(head[8:12]) == "WAVE":
		return wavFacts(head)
	case len(head) >= 12 && string(head[0:4]) == "RIFF" && string(head[8:12]) == "AVI ":
		return fileFacts{Kind: "video", Format: "AVI", Warn: "Browsers can't play AVI: MP4 or WebM would work"}
	case len(head) >= 12 && string(head[4:8]) == "ftyp":
		return ftypFacts(full, head, ext)
	case bytes.HasPrefix(head, []byte("glTF")):
		return gltfFacts(full, rel, head, has)
	case bytes.HasPrefix(head, []byte("BM")) && len(head) >= 26 && ext == ".bmp":
		w, h := int(int32(binary.LittleEndian.Uint32(head[18:]))), int(int32(binary.LittleEndian.Uint32(head[22:])))
		return fileFacts{Kind: "picture", Format: "BMP", Width: abs(w), Height: abs(h)}
	case bytes.HasPrefix(head, []byte("8BPS")) && len(head) >= 22:
		return fileFacts{Kind: "picture", Format: "Photoshop", Height: int(binary.BigEndian.Uint32(head[14:])), Width: int(binary.BigEndian.Uint32(head[18:])),
			Warn: "A browser can't show a Photoshop file: save it as PNG or JPEG for a page"}
	case bytes.HasPrefix(head, []byte("II*\x00")) || bytes.HasPrefix(head, []byte("MM\x00*")):
		if ext == ".tif" || ext == ".tiff" {
			return fileFacts{Kind: "picture", Format: "TIFF", Warn: "Most browsers can't show TIFF: PNG or JPEG would work"}
		}
	case bytes.HasPrefix(head, []byte("%PDF-")):
		return fileFacts{Kind: "document", Format: "PDF", Detail: "A page can link to it or show it in an <iframe>",
			Warn: "Its words aren't read here: paste the parts that matter into the message"}
	case bytes.HasPrefix(head, []byte("BLENDER")):
		return fileFacts{Kind: "3d", Format: "Blender file", Warn: "A browser can't show it: export it from Blender as glTF (.glb) for a page"}
	case bytes.HasPrefix(head, []byte("Kaydara FBX Binary")):
		x := fileFacts{Kind: "3d", Format: "FBX"}
		if len(head) >= 27 {
			v := binary.LittleEndian.Uint32(head[23:])
			x.Format = fmt.Sprintf("FBX %d.%d", v/1000, v%1000/100)
		}
		x.Warn = needs3D("FBXLoader")
		return x
	case bytes.HasPrefix(head, []byte("ply\n")) || bytes.HasPrefix(head, []byte("ply\r\n")):
		return plyFacts(head)
	case bytes.HasPrefix(head, []byte("\x1a\x45\xdf\xa3")):
		if ext == ".webm" {
			return fileFacts{Kind: "video", Format: "WebM"}
		}
		return fileFacts{Kind: "video", Format: "Matroska", Warn: "Most browsers can't play MKV: MP4 or WebM would work"}
	case bytes.HasPrefix(head, []byte("OggS")):
		if ext == ".ogv" {
			return fileFacts{Kind: "video", Format: "Ogg"}
		}
		return fileFacts{Kind: "audio", Format: "Ogg"}
	case bytes.HasPrefix(head, []byte("fLaC")):
		return fileFacts{Kind: "audio", Format: "FLAC"}
	case bytes.HasPrefix(head, []byte("ID3")) || (len(head) > 2 && head[0] == 0xFF && head[1]&0xE0 == 0xE0 && ext == ".mp3"):
		return fileFacts{Kind: "audio", Format: "MP3"}
	case bytes.HasPrefix(head, []byte("wOFF")):
		return fontFacts("WOFF")
	case bytes.HasPrefix(head, []byte("wOF2")):
		return fontFacts("WOFF2")
	case bytes.HasPrefix(head, []byte("OTTO")):
		return fontFacts("OpenType")
	case bytes.HasPrefix(head, []byte("\x00\x01\x00\x00")) && (ext == ".ttf" || ext == ".otf"), bytes.HasPrefix(head, []byte("true")) && ext == ".ttf":
		return fontFacts("TrueType")
	case bytes.HasPrefix(head, []byte("PK\x03\x04")):
		return zipFacts(full, ext)
	case bytes.HasPrefix(head, []byte("7z\xbc\xaf\x27\x1c")):
		return fileFacts{Kind: "archive", Format: "7-Zip", Warn: unpackIt}
	case bytes.HasPrefix(head, []byte("Rar!")):
		return fileFacts{Kind: "archive", Format: "RAR", Warn: unpackIt}
	case bytes.HasPrefix(head, []byte("\x1f\x8b")):
		return fileFacts{Kind: "archive", Format: "gzip", Warn: unpackIt}
	}

	switch ext {
	case ".svg":
		if utf8.Valid(trimCutRune(head)) {
			return svgFacts(head, size)
		}
	case ".gltf":
		return gltfFacts(full, rel, nil, has)
	case ".obj":
		if looksText(head) {
			return objFacts(full, rel, has)
		}
	case ".mtl":
		if looksText(head) {
			x := mtlFacts(full, rel, has)
			x.Text = size <= textMax
			return x
		}
	case ".stl":
		return stlFacts(full, head, size)
	case ".fbx":
		return fileFacts{Kind: "3d", Format: "FBX (text)", Warn: needs3D("FBXLoader")}
	case ".usdz":
		return fileFacts{Kind: "3d", Format: "USDZ", Detail: `Safari on an iPhone or iPad shows it in AR from a link with rel="ar"`, Warn: needs3D("USDZLoader")}
	case ".usd", ".usda", ".usdc":
		return fileFacts{Kind: "3d", Format: "USD", Warn: "A browser can't show it: export it as glTF (.glb) for a page"}
	case ".dae":
		return fileFacts{Kind: "3d", Format: "Collada", Warn: needs3D("ColladaLoader")}
	case ".3ds":
		return fileFacts{Kind: "3d", Format: "3DS", Warn: needs3D("TDSLoader")}
	case ".abc", ".max", ".c4d", ".ma", ".mb", ".skp", ".3dm", ".lwo", ".x3d":
		return fileFacts{Kind: "3d", Format: strings.ToUpper(ext[1:]), Warn: "A browser can't show it: export it as glTF (.glb) for a page"}
	case ".heic", ".heif", ".tif", ".tiff":
		return fileFacts{Kind: "picture", Format: strings.ToUpper(ext[1:]), Warn: "Most browsers can't show it: PNG or JPEG would work"}
	case ".mov", ".mp4", ".m4v":
		return fileFacts{Kind: "video", Format: strings.ToUpper(ext[1:])}
	case ".aac", ".m4a", ".opus", ".wav", ".mp3", ".aiff", ".aif":
		x := fileFacts{Kind: "audio", Format: strings.ToUpper(ext[1:])}
		if ext == ".aiff" || ext == ".aif" {
			x.Warn = "Only Safari plays AIFF: MP3 or WAV would work everywhere"
		}
		return x
	case ".ttf", ".otf", ".woff", ".woff2":
		return fontFacts(strings.ToUpper(ext[1:]))
	case ".numbers", ".pages", ".key", ".doc", ".xls", ".ppt":
		return officeFacts(ext)
	}
	if looksText(head) {
		x := fileFacts{Kind: "text", Format: textFormat(ext), Text: size <= textMax}
		if ext == ".csv" || ext == ".tsv" {
			if n := countLines(full); n > 0 {
				x.Detail = countOf(n, "line", "lines")
			}
		}
		return x
	}
	return fileFacts{Kind: "other", Format: strings.ToUpper(strings.TrimPrefix(ext, "."))}
}

const unpackIt = "Not unpacked: unzip it and attach the folder to use what's in it"

func needs3D(loader string) string {
	return "A browser shows it only through a 3D library (three.js's " + loader + ", for one)"
}

func fontFacts(format string) fileFacts {
	return fileFacts{Kind: "font", Format: format, Detail: "A page uses it with @font-face"}
}

func readHead(full string, n int) []byte {
	f, err := os.Open(full)
	if err != nil {
		return nil
	}
	defer f.Close()
	b := make([]byte, n)
	k, _ := io.ReadFull(f, b)
	return b[:k]
}

// looksText says whether a file's first bytes are text: UTF-8, no zero bytes.
func looksText(head []byte) bool {
	if len(head) == 0 {
		return true
	}
	return !bytes.ContainsRune(head, 0) && utf8.Valid(trimCutRune(head))
}

// trimCutRune drops a character cut in two at the end of a file's first bytes.
func trimCutRune(b []byte) []byte {
	for i := 0; i < 3 && len(b) > 0; i++ {
		if r, _ := utf8.DecodeLastRune(b); r != utf8.RuneError {
			return b
		}
		b = b[:len(b)-1]
	}
	return b
}

func countLines(full string) int {
	f, err := os.Open(full)
	if err != nil {
		return 0
	}
	defer f.Close()
	n, last := 0, byte('\n')
	buf := make([]byte, 64<<10)
	for {
		k, err := f.Read(buf)
		n += bytes.Count(buf[:k], []byte{'\n'})
		if k > 0 {
			last = buf[k-1]
		}
		if err != nil {
			break
		}
	}
	if last != '\n' {
		n++
	}
	return n
}

func textFormat(ext string) string {
	if f, ok := map[string]string{
		".txt": "plain text", ".md": "Markdown", ".markdown": "Markdown", ".html": "HTML", ".htm": "HTML", ".css": "CSS",
		".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript (React)", ".jsx": "JavaScript (React)",
		".json": "JSON", ".csv": "CSV", ".tsv": "TSV", ".xml": "XML", ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
		".ini": "settings", ".cfg": "settings", ".conf": "settings", ".env": "settings",
		".py": "Python", ".sh": "shell script", ".zsh": "shell script", ".go": "Go", ".rs": "Rust", ".c": "C", ".h": "C",
		".cpp": "C++", ".cc": "C++", ".hpp": "C++", ".java": "Java", ".kt": "Kotlin", ".swift": "Swift", ".rb": "Ruby",
		".php": "PHP", ".lua": "Lua", ".sql": "SQL", ".glsl": "GLSL shader", ".vert": "GLSL shader", ".frag": "GLSL shader",
		".log": "log", ".srt": "subtitles", ".vtt": "subtitles", ".tex": "LaTeX", ".bat": "batch file", ".ps1": "PowerShell", ".rtf": "RTF",
	}[ext]; ok {
		return f
	}
	return "plain text"
}

func countOf(n int, one, many string) string {
	if n == 1 {
		return "1 " + one
	}
	return fmtNum(n) + " " + many
}

func wasnt(n int) string {
	if n == 1 {
		return "wasn't"
	}
	return "weren't"
}

func abs(n int) int {
	if n < 0 {
		return -n
	}
	return n
}

// ---------- pictures ----------

func pngFacts(full string, head []byte, size int64) fileFacts {
	x := fileFacts{Kind: "picture", Format: "PNG"}
	alpha := false
scan:
	for off := 8; off+12 <= len(head); {
		n := int(binary.BigEndian.Uint32(head[off:]))
		body := head[off+8:]
		switch string(head[off+4 : off+8]) {
		case "IHDR":
			if len(body) >= 13 {
				x.Width, x.Height = int(binary.BigEndian.Uint32(body)), int(binary.BigEndian.Uint32(body[4:]))
				alpha = alpha || body[9] == 4 || body[9] == 6
			}
		case "tRNS":
			alpha = true
		case "acTL":
			if len(body) >= 4 {
				x.Frames = int(binary.BigEndian.Uint32(body))
			}
		case "IDAT", "IEND":
			break scan
		}
		if n < 0 || n > len(head) {
			break
		}
		off += 12 + n
	}
	if x.Frames == 1 {
		x.Frames = 0
	}
	if alpha {
		x.Alpha = "with transparency"
		if size <= 12<<20 {
			if f, err := os.Open(full); err == nil {
				if img, err := png.Decode(f); err == nil {
					x.Alpha = alphaKind(img)
				}
				f.Close()
			}
		}
	}
	return x
}

// alphaKind looks at a picture's see-through parts: a border that's almost all
// clear is a cut-out ("transparent background").
func alphaKind(img image.Image) string {
	b := img.Bounds()
	w, h := b.Dx(), b.Dy()
	if w == 0 || h == 0 {
		return ""
	}
	clear := func(x, y int) bool {
		_, _, _, a := img.At(b.Min.X+x, b.Min.Y+y).RGBA()
		return a < 0x1000
	}
	edge, edgeClear := 0, 0
	for x := 0; x < w; x += max(1, w/100) {
		edge += 2
		if clear(x, 0) {
			edgeClear++
		}
		if clear(x, h-1) {
			edgeClear++
		}
	}
	for y := 0; y < h; y += max(1, h/100) {
		edge += 2
		if clear(0, y) {
			edgeClear++
		}
		if clear(w-1, y) {
			edgeClear++
		}
	}
	if edgeClear*10 >= edge*8 {
		return "transparent background"
	}
	if edgeClear > 0 {
		return "with transparency"
	}
	for y := 0; y < h; y += max(1, h/64) {
		for x := 0; x < w; x += max(1, w/64) {
			if _, _, _, a := img.At(b.Min.X+x, b.Min.Y+y).RGBA(); a < 0xff00 {
				return "with transparency"
			}
		}
	}
	return ""
}

func jpegFacts(full string, head []byte) fileFacts {
	x := fileFacts{Kind: "picture", Format: "JPEG"}
	if f, err := os.Open(full); err == nil {
		if c, err := jpeg.DecodeConfig(f); err == nil {
			x.Width, x.Height = c.Width, c.Height
		}
		f.Close()
	}
	// A phone held upright saves the picture on its side and says to turn it;
	// browsers turn it, so the page sees it the other way round.
	if o := exifOrientation(head); o >= 5 && o <= 8 {
		x.Width, x.Height = x.Height, x.Width
	}
	return x
}

// exifOrientation reads the turn a camera wrote into a JPEG (1 to 8; 0 if none).
func exifOrientation(b []byte) int {
	for i := 2; i+4 <= len(b); {
		if b[i] != 0xFF {
			return 0
		}
		m := b[i+1]
		if m == 0xD8 || m == 0x01 || (m >= 0xD0 && m <= 0xD7) {
			i += 2
			continue
		}
		if m == 0xDA || m == 0xD9 {
			return 0
		}
		n := int(binary.BigEndian.Uint16(b[i+2:]))
		if n < 2 {
			return 0
		}
		end := min(len(b), i+2+n)
		if seg := b[i+4 : end]; m == 0xE1 && bytes.HasPrefix(seg, []byte("Exif\x00\x00")) {
			return tiffOrientation(seg[6:])
		}
		i += 2 + n
	}
	return 0
}

func tiffOrientation(t []byte) int {
	if len(t) < 8 {
		return 0
	}
	var bo binary.ByteOrder
	switch string(t[:2]) {
	case "II":
		bo = binary.LittleEndian
	case "MM":
		bo = binary.BigEndian
	default:
		return 0
	}
	ifd := int(bo.Uint32(t[4:]))
	if ifd < 8 || ifd+2 > len(t) {
		return 0
	}
	for k, n := 0, int(bo.Uint16(t[ifd:])); k < n; k++ {
		e := ifd + 2 + 12*k
		if e+12 > len(t) {
			return 0
		}
		if bo.Uint16(t[e:]) == 0x0112 {
			return int(bo.Uint16(t[e+8:]))
		}
	}
	return 0
}

func gifFacts(full string, size int64) fileFacts {
	x := fileFacts{Kind: "picture", Format: "GIF"}
	f, err := os.Open(full)
	if err != nil {
		return x
	}
	defer f.Close()
	if size <= 16<<20 {
		if g, err := gif.DecodeAll(f); err == nil {
			x.Width, x.Height = g.Config.Width, g.Config.Height
			if len(g.Image) > 1 {
				x.Frames = len(g.Image)
			}
			if len(g.Image) > 0 {
				x.Alpha = alphaKind(g.Image[0])
			}
			return x
		}
		if _, err := f.Seek(0, io.SeekStart); err != nil {
			return x
		}
	}
	if c, err := gif.DecodeConfig(f); err == nil {
		x.Width, x.Height = c.Width, c.Height
	}
	return x
}

func webpFacts(full string, head []byte) fileFacts {
	x := fileFacts{Kind: "picture", Format: "WebP"}
	if len(head) < 30 {
		return x
	}
	switch string(head[12:16]) {
	case "VP8X":
		flags := head[20]
		x.Width = 1 + (int(head[24]) | int(head[25])<<8 | int(head[26])<<16)
		x.Height = 1 + (int(head[27]) | int(head[28])<<8 | int(head[29])<<16)
		if flags&0x10 != 0 {
			x.Alpha = "with transparency"
		}
		if flags&0x02 != 0 {
			x.Frames = webpFrames(full)
		}
	case "VP8L":
		v := binary.LittleEndian.Uint32(head[21:25])
		x.Width, x.Height = int(v&0x3FFF)+1, int((v>>14)&0x3FFF)+1
		if v>>28&1 == 1 {
			x.Alpha = "with transparency"
		}
	case "VP8 ":
		x.Width = int(binary.LittleEndian.Uint16(head[26:28]) & 0x3FFF)
		x.Height = int(binary.LittleEndian.Uint16(head[28:30]) & 0x3FFF)
	}
	return x
}

// webpFrames counts an animated WebP's frames (its ANMF chunks).
func webpFrames(full string) int {
	f, err := os.Open(full)
	if err != nil {
		return 0
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return 0
	}
	n := 0
	hdr := make([]byte, 8)
	for off, k := int64(12), 0; off+8 <= st.Size() && k < 100000; k++ {
		if _, err := f.ReadAt(hdr, off); err != nil {
			break
		}
		if string(hdr[:4]) == "ANMF" {
			n++
		}
		size := int64(binary.LittleEndian.Uint32(hdr[4:]))
		off += 8 + size + size&1
	}
	return n
}

var (
	svgTagRe  = regexp.MustCompile(`(?is)<svg\b[^>]*>`)
	svgAttrRe = regexp.MustCompile(`(?is)\b(width|height|viewBox)\s*=\s*["']([^"']*)["']`)
)

func svgFacts(head []byte, size int64) fileFacts {
	// Its code goes to the model when it's small, as a logo's usually is.
	x := fileFacts{Kind: "picture", Format: "SVG", Text: size <= 24<<10}
	attrs := map[string]string{}
	for _, m := range svgAttrRe.FindAllSubmatch(svgTagRe.Find(head), -1) {
		attrs[strings.ToLower(string(m[1]))] = string(m[2])
	}
	w, h := svgLen(attrs["width"]), svgLen(attrs["height"])
	if vb := strings.Fields(strings.ReplaceAll(attrs["viewbox"], ",", " ")); (w == 0 || h == 0) && len(vb) == 4 {
		w, _ = strconv.ParseFloat(vb[2], 64)
		h, _ = strconv.ParseFloat(vb[3], 64)
	}
	if w > 0 && h > 0 {
		x.Width, x.Height = int(math.Round(w)), int(math.Round(h))
	}
	return x
}

func svgLen(s string) float64 {
	s = strings.TrimSuffix(strings.TrimSpace(s), "px")
	v, err := strconv.ParseFloat(strings.TrimSpace(s), 64)
	if err != nil || v <= 0 {
		return 0
	}
	return v
}

// ---------- videos and sounds ----------

func wavFacts(head []byte) fileFacts {
	x := fileFacts{Kind: "audio", Format: "WAV"}
	rate := 0
	for off := 12; off+8 <= len(head); {
		id, n := string(head[off:off+4]), int(binary.LittleEndian.Uint32(head[off+4:]))
		switch id {
		case "fmt ":
			if off+20 <= len(head) {
				rate = int(binary.LittleEndian.Uint32(head[off+16:])) // bytes a second
			}
		case "data":
			if rate > 0 {
				x.Secs = round1(float64(n) / float64(rate))
			}
			return x
		}
		off += 8 + n + n&1
	}
	return x
}

// ftypFacts reads the files that start with an "ftyp" box: MP4 and QuickTime
// videos, M4A sounds, and HEIC and AVIF pictures.
func ftypFacts(full string, head []byte, ext string) fileFacts {
	brand := string(head[8:12])
	n := int(binary.BigEndian.Uint32(head))
	brands := brand
	if n <= len(head) && n > 16 {
		brands += string(head[16:n])
	}
	switch {
	case strings.Contains(brands, "avif") || strings.Contains(brands, "avis"):
		w, h := ispeSize(head)
		return fileFacts{Kind: "picture", Format: "AVIF", Width: w, Height: h}
	case ext == ".heic" || ext == ".heif" || brand == "heic" || brand == "heix" || brand == "hevc" || brand == "mif1" || brand == "msf1":
		w, h := ispeSize(head)
		return fileFacts{Kind: "picture", Format: "HEIC", Width: w, Height: h, Warn: "Only Safari shows HEIC: Chrome and Firefox don't, so save it as JPEG or PNG for a page"}
	}
	format := map[string]string{".mov": "QuickTime (.mov)", ".m4v": "MP4", ".m4a": "M4A", ".3gp": "3GP"}[ext]
	if format == "" {
		format = "MP4"
		if brand == "qt  " {
			format = "QuickTime (.mov)"
		}
	}
	w, h, secs := mp4Facts(full)
	x := fileFacts{Kind: "video", Format: format, Width: w, Height: h, Secs: round1(secs)}
	if w == 0 && (ext == ".m4a" || ext == ".m4b" || strings.HasPrefix(brand, "M4A")) {
		x.Kind, x.Format = "audio", "M4A"
	}
	return x
}

// ispeSize is the biggest picture size an HEIF file names (its tiles name theirs too).
func ispeSize(head []byte) (int, int) {
	w, h := 0, 0
	for i := 0; ; {
		k := bytes.Index(head[i:], []byte("ispe"))
		if k < 0 {
			break
		}
		at := i + k
		if at+16 <= len(head) {
			if x, y := int(binary.BigEndian.Uint32(head[at+8:])), int(binary.BigEndian.Uint32(head[at+12:])); x*y > w*h && x < 1<<16 && y < 1<<16 {
				w, h = x, y
			}
		}
		i = at + 4
	}
	return w, h
}

// mp4Facts reads an MP4 or QuickTime file's size in pixels (as it's shown, so
// a phone video filmed upright is taller than wide) and its length.
func mp4Facts(full string) (w, h int, secs float64) {
	f, err := os.Open(full)
	if err != nil {
		return
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return
	}
	hdr := make([]byte, 16)
	for off := int64(0); off+8 <= st.Size(); {
		if _, err := f.ReadAt(hdr[:8], off); err != nil {
			return
		}
		size, hl := int64(binary.BigEndian.Uint32(hdr)), int64(8)
		if size == 1 {
			if _, err := f.ReadAt(hdr[8:16], off+8); err != nil {
				return
			}
			size, hl = int64(binary.BigEndian.Uint64(hdr[8:])), 16
		} else if size == 0 {
			size = st.Size() - off
		}
		if size < hl {
			return
		}
		if string(hdr[4:8]) == "moov" {
			if size > 64<<20 {
				return
			}
			buf := make([]byte, size-hl)
			if _, err := f.ReadAt(buf, off+hl); err != nil {
				return
			}
			return moovFacts(buf)
		}
		off += size
	}
	return
}

// mp4Boxes calls fn with each box in b.
func mp4Boxes(b []byte, fn func(typ string, body []byte)) {
	for len(b) >= 8 {
		size, hl := int(binary.BigEndian.Uint32(b)), 8
		if size == 1 {
			if len(b) < 16 {
				return
			}
			size, hl = int(binary.BigEndian.Uint64(b[8:])), 16
		} else if size == 0 {
			size = len(b)
		}
		if size < hl || size > len(b) {
			return
		}
		fn(string(b[4:8]), b[hl:size])
		b = b[size:]
	}
}

func moovFacts(moov []byte) (w, h int, secs float64) {
	mp4Boxes(moov, func(typ string, body []byte) {
		switch typ {
		case "mvhd":
			if len(body) >= 32 && body[0] == 1 {
				if ts := binary.BigEndian.Uint32(body[20:]); ts > 0 {
					secs = float64(binary.BigEndian.Uint64(body[24:])) / float64(ts)
				}
			} else if len(body) >= 20 {
				if ts := binary.BigEndian.Uint32(body[12:]); ts > 0 {
					secs = float64(binary.BigEndian.Uint32(body[16:])) / float64(ts)
				}
			}
		case "trak":
			if w > 0 {
				return
			}
			mp4Boxes(body, func(t string, b []byte) {
				if t != "tkhd" || len(b) < 84 {
					return
				}
				mo, wo := 40, 76
				if b[0] == 1 {
					mo, wo = 52, 88
				}
				if len(b) < wo+8 {
					return
				}
				tw, th := int(binary.BigEndian.Uint32(b[wo:])>>16), int(binary.BigEndian.Uint32(b[wo+4:])>>16)
				if tw == 0 || th == 0 {
					return
				}
				// a matrix turned a quarter (a phone held upright) shows it the other way round
				if a, c := int32(binary.BigEndian.Uint32(b[mo:])), int32(binary.BigEndian.Uint32(b[mo+4:])); a == 0 && c != 0 {
					tw, th = th, tw
				}
				w, h = tw, th
			})
		}
	})
	return
}

// ---------- documents and archives ----------

func zipFacts(full, ext string) fileFacts {
	switch ext {
	case ".docx":
		x := fileFacts{Kind: "document", Format: "Word"}
		if words := docxWords(full); words != "" {
			x.Detail = "Its words are below"
			x.Words = words
		} else {
			x.Warn = "Its words couldn't be read: paste the parts that matter into the message"
		}
		return x
	case ".usdz":
		return fileFacts{Kind: "3d", Format: "USDZ", Detail: `Safari on an iPhone or iPad shows it in AR from a link with rel="ar"`, Warn: needs3D("USDZLoader")}
	case ".xlsx", ".pptx", ".numbers", ".pages", ".key", ".odt", ".ods", ".odp":
		return officeFacts(ext)
	}
	x := fileFacts{Kind: "archive", Format: "ZIP", Warn: unpackIt}
	if r, err := zip.OpenReader(full); err == nil {
		x.Detail = countOf(len(r.File), "file", "files") + " inside"
		r.Close()
	}
	return x
}

func officeFacts(ext string) fileFacts {
	x := fileFacts{Kind: "document", Format: map[string]string{".xlsx": "Excel", ".xls": "Excel", ".pptx": "PowerPoint", ".ppt": "PowerPoint",
		".numbers": "Numbers", ".pages": "Pages", ".key": "Keynote", ".doc": "Word", ".odt": "OpenDocument", ".ods": "OpenDocument", ".odp": "OpenDocument"}[ext]}
	switch ext {
	case ".xlsx", ".xls", ".numbers", ".ods":
		x.Warn = "Its cells aren't read here: export it as CSV and attach that for the model to read them"
	default:
		x.Warn = "Its words aren't read here: export it as text or PDF, or paste the parts that matter into the message"
	}
	return x
}

var (
	docxParaRe = regexp.MustCompile(`</w:p>`)
	docxTextRe = regexp.MustCompile(`(?s)<w:t(?:\s[^>]*)?>(.*?)</w:t>`)
	docxTagRe  = regexp.MustCompile(`<[^>]+>`)
)

// docxWords is a Word file's text, a paragraph a line.
func docxWords(full string) string {
	r, err := zip.OpenReader(full)
	if err != nil {
		return ""
	}
	defer r.Close()
	for _, f := range r.File {
		if f.Name != "word/document.xml" || f.UncompressedSize64 > 64<<20 {
			continue
		}
		rc, err := f.Open()
		if err != nil {
			return ""
		}
		b, err := io.ReadAll(io.LimitReader(rc, 64<<20))
		rc.Close()
		if err != nil {
			return ""
		}
		var out strings.Builder
		for _, para := range docxParaRe.Split(string(b), -1) {
			var line strings.Builder
			for _, m := range docxTextRe.FindAllStringSubmatch(para, -1) {
				line.WriteString(m[1])
			}
			if t := strings.TrimSpace(xmlUnescape(docxTagRe.ReplaceAllString(line.String(), ""))); t != "" {
				out.WriteString(t + "\n")
			}
		}
		return out.String()
	}
	return ""
}

func xmlUnescape(s string) string {
	return strings.NewReplacer("&lt;", "<", "&gt;", ">", "&quot;", `"`, "&apos;", "'", "&amp;", "&").Replace(s)
}

// ---------- 3D models ----------

type vec3 [3]float64

type box3 struct {
	min, max vec3
	ok       bool
}

func (b *box3) add(p vec3) {
	if !b.ok {
		b.min, b.max, b.ok = p, p, true
		return
	}
	for i := 0; i < 3; i++ {
		b.min[i] = math.Min(b.min[i], p[i])
		b.max[i] = math.Max(b.max[i], p[i])
	}
}

// words says a box's size and where it is: "6.1 × 2.8 × 2.3 (x × y × z), from (-3, 0, -1.2) to (3.1, 2.8, 1.1)".
func (b box3) words(unit string) string {
	if !b.ok {
		return ""
	}
	d := vec3{b.max[0] - b.min[0], b.max[1] - b.min[1], b.max[2] - b.min[2]}
	return fmt.Sprintf("%s × %s × %s%s (x × y × z), from (%s, %s, %s) to (%s, %s, %s)",
		fmtLen(d[0]), fmtLen(d[1]), fmtLen(d[2]), unit,
		fmtLen(b.min[0]), fmtLen(b.min[1]), fmtLen(b.min[2]), fmtLen(b.max[0]), fmtLen(b.max[1]), fmtLen(b.max[2]))
}

// fmtLen writes a length with about three figures: 6.12, 61.2, 612.
func fmtLen(v float64) string {
	a := math.Abs(v)
	var s string
	switch {
	case a >= 100:
		s = strconv.FormatFloat(v, 'f', 0, 64)
	case a >= 10:
		s = strconv.FormatFloat(v, 'f', 1, 64)
	case a >= 1:
		s = strconv.FormatFloat(v, 'f', 2, 64)
	default:
		s = strconv.FormatFloat(v, 'f', 3, 64)
	}
	if strings.Contains(s, ".") {
		s = strings.TrimRight(strings.TrimRight(s, "0"), ".")
	}
	if s == "-0" {
		s = "0"
	}
	return s
}

type gltfDoc struct {
	Scene  *int `json:"scene"`
	Scenes []struct {
		Nodes []int `json:"nodes"`
	} `json:"scenes"`
	Nodes []struct {
		Name        string    `json:"name"`
		Mesh        *int      `json:"mesh"`
		Children    []int     `json:"children"`
		Matrix      []float64 `json:"matrix"`
		Translation []float64 `json:"translation"`
		Rotation    []float64 `json:"rotation"`
		Scale       []float64 `json:"scale"`
	} `json:"nodes"`
	Meshes []struct {
		Primitives []struct {
			Attributes map[string]int `json:"attributes"`
			Indices    *int           `json:"indices"`
			Mode       *int           `json:"mode"`
		} `json:"primitives"`
	} `json:"meshes"`
	Accessors []struct {
		Count int       `json:"count"`
		Min   []float64 `json:"min"`
		Max   []float64 `json:"max"`
	} `json:"accessors"`
	Materials []json.RawMessage `json:"materials"`
	Textures  []json.RawMessage `json:"textures"`
	Images    []struct {
		URI string `json:"uri"`
	} `json:"images"`
	Buffers []struct {
		URI string `json:"uri"`
	} `json:"buffers"`
	Animations []struct {
		Name     string `json:"name"`
		Samplers []struct {
			Input int `json:"input"`
		} `json:"samplers"`
		Channels []struct {
			Target struct {
				Node *int `json:"node"`
			} `json:"target"`
		} `json:"channels"`
	} `json:"animations"`
	Skins []struct {
		Joints []int `json:"joints"`
	} `json:"skins"`
	Cameras            []json.RawMessage `json:"cameras"`
	ExtensionsRequired []string          `json:"extensionsRequired"`
	Extensions         struct {
		Lights *struct {
			Lights []json.RawMessage `json:"lights"`
		} `json:"KHR_lights_punctual"`
	} `json:"extensions"`
}

// gltfFacts reads a glTF model (a .glb, whose head starts "glTF", or a .gltf's
// JSON): its parts, its animations, its size in metres, and the files it needs.
func gltfFacts(full, rel string, head []byte, has func(string) bool) fileFacts {
	x := fileFacts{Kind: "3d", Format: "glTF", Warn: needs3D("GLTFLoader")}
	var js []byte
	if head != nil {
		x.Format = "glTF binary (.glb)"
		if len(head) < 20 || string(head[16:20]) != "JSON" {
			return x
		}
		n := int(binary.LittleEndian.Uint32(head[12:]))
		if n <= 0 || n > 64<<20 {
			return x
		}
		if 20+n <= len(head) {
			js = head[20 : 20+n]
		} else {
			f, err := os.Open(full)
			if err != nil {
				return x
			}
			js = make([]byte, n)
			_, err = f.ReadAt(js, 20)
			f.Close()
			if err != nil {
				return x
			}
		}
	} else {
		b, err := os.ReadFile(full)
		if err != nil || len(b) > 64<<20 {
			return x
		}
		js = b
	}
	var d gltfDoc
	if err := json.Unmarshal(js, &d); err != nil {
		x.Warn = "It doesn't read as glTF (" + err.Error() + ")"
		return x
	}
	acc := func(i int) (int, []float64, []float64, bool) {
		if i < 0 || i >= len(d.Accessors) {
			return 0, nil, nil, false
		}
		a := d.Accessors[i]
		return a.Count, a.Min, a.Max, true
	}
	var bounds box3
	own := map[int]*box3{} // each mesh node's box in the world, for its parts
	at := map[int]vec3{}   // and where its origin is
	tris := 0
	seen := 0
	var walk func(n int, parent [16]float64, depth int)
	walk = func(n int, parent [16]float64, depth int) {
		if n < 0 || n >= len(d.Nodes) || depth > 64 || seen > 100000 {
			return
		}
		seen++
		nd := d.Nodes[n]
		world := mat4Mul(parent, nodeMatrix(nd.Matrix, nd.Translation, nd.Rotation, nd.Scale))
		at[n] = vec3{world[12], world[13], world[14]}
		if nd.Mesh != nil && *nd.Mesh >= 0 && *nd.Mesh < len(d.Meshes) {
			for _, p := range d.Meshes[*nd.Mesh].Primitives {
				mode := 4
				if p.Mode != nil {
					mode = *p.Mode
				}
				pos, hasPos := p.Attributes["POSITION"]
				count, mn, mx, ok := acc(pos)
				if !hasPos || !ok {
					continue
				}
				if p.Indices != nil {
					if c, _, _, ok := acc(*p.Indices); ok {
						count = c
					}
				}
				switch mode {
				case 4:
					tris += count / 3
				case 5, 6:
					tris += max(0, count-2)
				}
				if len(mn) == 3 && len(mx) == 3 {
					for c := 0; c < 8; c++ {
						p := vec3{mn[0], mn[1], mn[2]}
						for k := 0; k < 3; k++ {
							if c>>k&1 == 1 {
								p[k] = mx[k]
							}
						}
						w := mat4Point(world, p)
						bounds.add(w)
						if own[n] == nil {
							own[n] = &box3{}
						}
						own[n].add(w)
					}
				}
			}
		}
		for _, c := range nd.Children {
			walk(c, world, depth+1)
		}
	}
	var roots []int
	if len(d.Scenes) > 0 {
		s := 0
		if d.Scene != nil && *d.Scene >= 0 && *d.Scene < len(d.Scenes) {
			s = *d.Scene
		}
		roots = d.Scenes[s].Nodes
	} else {
		child := map[int]bool{}
		for _, nd := range d.Nodes {
			for _, c := range nd.Children {
				child[c] = true
			}
		}
		for i := range d.Nodes {
			if !child[i] {
				roots = append(roots, i)
			}
		}
	}
	for _, r := range roots {
		walk(r, mat4Identity(), 0)
	}

	var parts []string
	parts = append(parts, countOf(len(d.Meshes), "mesh", "meshes"))
	if tris > 0 {
		parts = append(parts, countOf(tris, "triangle", "triangles"))
	}
	if n := len(d.Materials); n > 0 {
		parts = append(parts, countOf(n, "material", "materials"))
	}
	inside, outside := 0, []string{}
	for _, im := range d.Images {
		if im.URI == "" || strings.HasPrefix(im.URI, "data:") {
			inside++
		} else {
			outside = append(outside, im.URI)
		}
	}
	switch {
	case inside > 0 && len(outside) == 0:
		parts = append(parts, countOf(inside, "texture", "textures")+" inside the file")
	case len(outside) > 0:
		parts = append(parts, countOf(inside+len(outside), "texture", "textures")+fmt.Sprintf(" (%d as files beside it)", len(outside)))
	}
	if len(d.Skins) > 0 {
		parts = append(parts, "rigged")
	}
	if len(d.Cameras) > 0 {
		parts = append(parts, countOf(len(d.Cameras), "camera", "cameras"))
	}
	if d.Extensions.Lights != nil && len(d.Extensions.Lights.Lights) > 0 {
		parts = append(parts, countOf(len(d.Extensions.Lights.Lights), "light", "lights"))
	}
	if len(d.Animations) > 0 {
		var as []string
		for i, an := range d.Animations {
			if i == 8 {
				as = append(as, fmt.Sprintf("and %d more", len(d.Animations)-8))
				break
			}
			name := an.Name
			if name == "" {
				name = fmt.Sprintf("animation %d", i)
			}
			secs := 0.0
			for _, s := range an.Samplers {
				if _, _, mx, ok := acc(s.Input); ok && len(mx) > 0 {
					secs = math.Max(secs, mx[0])
				}
			}
			var about []string
			if secs > 0 {
				about = append(about, fmtSecs(secs))
			}
			if moves := gltfMoves(&d, i); moves != "" {
				about = append(about, "moves "+moves)
			}
			if len(about) > 0 {
				name = fmt.Sprintf("%q (%s)", name, strings.Join(about, "; "))
			} else {
				name = fmt.Sprintf("%q", name)
			}
			as = append(as, name)
		}
		label := "animation"
		if len(d.Animations) > 1 {
			label = "animations"
		}
		parts = append(parts, label+": "+strings.Join(as, ", "))
	}
	x.Detail = strings.Join(parts, ", ")
	if bounds.ok {
		x.Detail += "; about " + bounds.words(" m") + ", y up"
	}
	if named := gltfParts(&d, own); len(named) >= 2 {
		list, rest := partsWords(named, " m")
		x.Parts = fmt.Sprintf("Its parts, biggest first (glTF node names, which three.js's GLTFLoader gives its objects, for getObjectByName): %s", list)
		if rest > 0 {
			x.Parts += fmt.Sprintf(", and %s more, smaller", fmtNum(rest))
		}
		if note := threeNames(named); note != "" {
			x.Parts += ". " + note
		}
		if sameOrigin(named, at, bounds) {
			x.Parts += ". They all sit at one origin (the file puts no pivots on them), so to turn one about its own hinge, put it in a Group placed at the hinge (a Box3 of the part shows where it is)"
		}
	}
	// What it needs beside it, and what its loader needs.
	var missing []string
	need := func(uri string) {
		if uri == "" || strings.HasPrefix(uri, "data:") {
			return
		}
		u, err := url.PathUnescape(uri)
		if err != nil {
			u = uri
		}
		p := path.Join(path.Dir(rel), u)
		if strings.HasPrefix(p, "../") || !has(p) {
			missing = append(missing, u)
		}
	}
	for _, b := range d.Buffers {
		need(b.URI)
	}
	for _, u := range outside {
		need(u)
	}
	var notes []string
	if len(missing) > 0 {
		if len(missing) > 4 {
			missing = append(missing[:4], fmt.Sprintf("%d more", len(missing)-4))
		}
		notes = append(notes, "It needs "+strings.Join(missing, ", ")+" beside it, which "+wasnt(len(missing))+" attached, so it won't load whole")
	}
	for _, e := range d.ExtensionsRequired {
		switch e {
		case "KHR_draco_mesh_compression":
			notes = append(notes, "Its meshes are Draco-compressed: three.js needs a DRACOLoader for them, given to the GLTFLoader with setDRACOLoader, its decoder from the same three.js version "+
				`(new DRACOLoader().setDecoderPath("https://cdn.jsdelivr.net/npm/three@<version>/examples/jsm/libs/draco/gltf/"))`)
		case "EXT_meshopt_compression":
			notes = append(notes, "Its meshes are meshopt-compressed: three.js needs the MeshoptDecoder for them")
		case "KHR_texture_basisu":
			notes = append(notes, "Its textures are KTX2: three.js needs a KTX2Loader for them")
		}
	}
	if len(notes) > 0 {
		x.Warn += ". " + strings.Join(notes, ". ")
	}
	return x
}

// ---------- a model's parts, by name ----------

// part is a named piece of a 3D model: what a page finds by name to move it.
type part struct {
	name, parent string
	box          box3
	order        int
}

const partsMax = 40 // entries in a model's list of parts; the rest are counted

func gltfJoints(d *gltfDoc) map[int]bool {
	joint := map[int]bool{}
	for _, s := range d.Skins {
		for _, j := range s.Joints {
			joint[j] = true
		}
	}
	return joint
}

// gltfParts are a glTF model's named nodes that hold something to see: those with a
// mesh, and the groups above them (the parts that move together). A rig's bones, and
// a node that only wraps one other part, are left out. own has each mesh node's box.
func gltfParts(d *gltfDoc, own map[int]*box3) []part {
	n := len(d.Nodes)
	if n == 0 || n > 100000 {
		return nil
	}
	joint := gltfJoints(d)
	parent := make([]int, n)
	for i := range parent {
		parent[i] = -1
	}
	for i, nd := range d.Nodes {
		for _, c := range nd.Children {
			if c >= 0 && c < n && c != i && parent[c] == -1 {
				parent[c] = i
			}
		}
	}
	box := make([]box3, n) // with everything under it
	listed := make([]bool, n)
	state := make([]int8, n)
	var visit func(i, depth int)
	visit = func(i, depth int) {
		if state[i] != 0 || depth > 64 {
			return
		}
		state[i] = 1
		nd := d.Nodes[i]
		mesh := own[i] != nil && own[i].ok
		if mesh {
			box[i].add(own[i].min)
			box[i].add(own[i].max)
		}
		kids, listedKids := 0, 0
		for _, c := range nd.Children {
			if c < 0 || c >= n || parent[c] != i {
				continue
			}
			visit(c, depth+1)
			if box[c].ok {
				box[i].add(box[c].min)
				box[i].add(box[c].max)
				kids++
				if listed[c] {
					listedKids++
				}
			}
		}
		named := strings.TrimSpace(nd.Name) != "" && !joint[i]
		listed[i] = named && box[i].ok && (mesh || kids >= 2 || (kids == 1 && listedKids == 0))
	}
	for i := range d.Nodes {
		if parent[i] == -1 {
			visit(i, 0)
		}
	}
	var out []part
	for i := range d.Nodes {
		if !listed[i] {
			continue
		}
		p := part{name: d.Nodes[i].Name, box: box[i], order: i}
		for a, k := parent[i], 0; a >= 0 && k < 64; a, k = parent[a], k+1 {
			if listed[a] {
				p.parent = d.Nodes[a].Name
				break
			}
		}
		out = append(out, p)
	}
	return out
}

// sameOrigin says whether every part's origin is the same point (a model exported from
// an OBJ: Blender gives each part the same turn and no place of its own), so that none
// of them turns about itself. at has each node's origin in the world.
func sameOrigin(parts []part, at map[int]vec3, all box3) bool {
	if len(parts) < 2 || !all.ok {
		return false
	}
	eps := 1e-6 * math.Max(1, math.Max(all.max[0]-all.min[0], math.Max(all.max[1]-all.min[1], all.max[2]-all.min[2])))
	first, ok := at[parts[0].order]
	for _, p := range parts[1:] {
		o, seen := at[p.order]
		if !ok || !seen || math.Abs(o[0]-first[0]) > eps || math.Abs(o[1]-first[1]) > eps || math.Abs(o[2]-first[2]) > eps {
			return false
		}
	}
	return ok
}

// gltfMoves says what animation a moves: its nodes' names, or how many bones.
func gltfMoves(d *gltfDoc, a int) string {
	joint := gltfJoints(d)
	seen := map[int]bool{}
	var names []string
	bones, unnamed := 0, 0
	for _, ch := range d.Animations[a].Channels {
		t := ch.Target.Node
		if t == nil || *t < 0 || *t >= len(d.Nodes) || seen[*t] {
			continue
		}
		seen[*t] = true
		switch {
		case joint[*t]:
			bones++
		case strings.TrimSpace(d.Nodes[*t].Name) == "":
			unnamed++
		default:
			names = append(names, "`"+d.Nodes[*t].Name+"`")
		}
	}
	if len(names) > 8 {
		names = append(names[:8], fmt.Sprintf("%d more", len(names)-8))
	}
	var out []string
	if len(names) > 0 {
		out = append(out, strings.Join(names, ", "))
	}
	if bones > 0 {
		out = append(out, countOf(bones, "bone", "bones"))
	}
	if unnamed > 0 {
		out = append(out, countOf(unnamed, "node with no name", "nodes with no name"))
	}
	return strings.Join(out, ", ")
}

// threeName is a node's name as three.js's GLTFLoader gives it to its object
// (PropertyBinding.sanitizeNodeName): spaces become _, and [ ] . : / go.
func threeName(s string) string {
	return strings.Map(func(r rune) rune {
		switch {
		case unicode.IsSpace(r):
			return '_'
		case strings.ContainsRune("[].:/", r):
			return -1
		}
		return r
	}, s)
}

// threeNames says how three.js changes these names, when it changes any.
func threeNames(parts []part) string {
	var notes []string
	seen := map[string]bool{}
	example, twice := "", false
	for _, p := range parts {
		s := threeName(p.name)
		if s != p.name && example == "" {
			example = fmt.Sprintf("`%s` is `%s` there", p.name, s)
		}
		twice = twice || seen[s]
		seen[s] = true
	}
	if example != "" {
		notes = append(notes, "In three.js spaces become _ and [ ] . : / are left out ("+example+")")
	}
	if twice {
		notes = append(notes, "a name that comes twice gets _1, _2… in three.js after the first")
	}
	return strings.Join(notes, "; ")
}

// partsWords lists parts biggest first (each with its longest side, in unit), at
// most partsMax entries, a numbered run of names in one place as one entry ("`Bolt_0`
// to `Bolt_5`"), and says how many parts that leaves out.
func partsWords(parts []part, unit string) (string, int) {
	type entry struct {
		first, last, parent string
		size                float64
		order, n            int
	}
	size := func(b box3) float64 {
		if !b.ok {
			return -1
		}
		return math.Max(b.max[0]-b.min[0], math.Max(b.max[1]-b.min[1], b.max[2]-b.min[2]))
	}
	type runKey struct{ parent, prefix, suffix string }
	num := func(s string) int {
		n, _ := strconv.Atoi(numberedRe.FindStringSubmatch(s)[2])
		return n
	}
	runs := map[runKey][]int{}
	var keys []runKey
	var entries []entry
	for i, p := range parts {
		if m := numberedRe.FindStringSubmatch(p.name); m != nil && len(m[2]) <= 4 {
			k := runKey{p.parent, m[1], m[3]}
			if runs[k] == nil {
				keys = append(keys, k)
			}
			runs[k] = append(runs[k], i)
			continue
		}
		entries = append(entries, entry{first: p.name, parent: p.parent, size: size(p.box), order: p.order, n: 1})
	}
	for _, k := range keys {
		idx := runs[k]
		sort.SliceStable(idx, func(a, b int) bool { return num(parts[idx[a]].name) < num(parts[idx[b]].name) })
		for s := 0; s < len(idx); {
			e := s
			for e+1 < len(idx) && num(parts[idx[e+1]].name) == num(parts[idx[e]].name)+1 {
				e++
			}
			ent := entry{first: parts[idx[s]].name, parent: k.parent, size: -1, order: parts[idx[s]].order, n: e - s + 1}
			if e > s {
				ent.last = parts[idx[e]].name
			}
			for j := s; j <= e; j++ {
				ent.size = math.Max(ent.size, size(parts[idx[j]].box))
				ent.order = min(ent.order, parts[idx[j]].order)
			}
			entries = append(entries, ent)
			s = e + 1
		}
	}
	sort.SliceStable(entries, func(a, b int) bool {
		if entries[a].size != entries[b].size {
			return entries[a].size > entries[b].size
		}
		return entries[a].order < entries[b].order
	})
	var words []string
	shown := 0
	for _, e := range entries {
		if len(words) == partsMax {
			break
		}
		w := "`" + e.first + "`"
		if e.last != "" {
			w += " to `" + e.last + "`"
		}
		var about []string
		if e.size > 0 {
			about = append(about, fmtLen(e.size)+unit)
		}
		if e.parent != "" {
			about = append(about, "in `"+e.parent+"`")
		}
		if len(about) > 0 {
			w += " (" + strings.Join(about, ", ") + ")"
		}
		words = append(words, w)
		shown += e.n
	}
	return strings.Join(words, ", "), len(parts) - shown
}

func mat4Identity() [16]float64 {
	return [16]float64{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1}
}

// nodeMatrix is a glTF node's own transform (column-major, as glTF stores it).
func nodeMatrix(m, t, r, s []float64) [16]float64 {
	if len(m) == 16 {
		var out [16]float64
		copy(out[:], m)
		return out
	}
	tx, ty, tz := 0.0, 0.0, 0.0
	if len(t) == 3 {
		tx, ty, tz = t[0], t[1], t[2]
	}
	qx, qy, qz, qw := 0.0, 0.0, 0.0, 1.0
	if len(r) == 4 {
		qx, qy, qz, qw = r[0], r[1], r[2], r[3]
	}
	sx, sy, sz := 1.0, 1.0, 1.0
	if len(s) == 3 {
		sx, sy, sz = s[0], s[1], s[2]
	}
	return [16]float64{
		(1 - 2*(qy*qy+qz*qz)) * sx, 2 * (qx*qy + qz*qw) * sx, 2 * (qx*qz - qy*qw) * sx, 0,
		2 * (qx*qy - qz*qw) * sy, (1 - 2*(qx*qx+qz*qz)) * sy, 2 * (qy*qz + qx*qw) * sy, 0,
		2 * (qx*qz + qy*qw) * sz, 2 * (qy*qz - qx*qw) * sz, (1 - 2*(qx*qx+qy*qy)) * sz, 0,
		tx, ty, tz, 1,
	}
}

func mat4Mul(a, b [16]float64) [16]float64 {
	var out [16]float64
	for c := 0; c < 4; c++ {
		for r := 0; r < 4; r++ {
			v := 0.0
			for k := 0; k < 4; k++ {
				v += a[k*4+r] * b[c*4+k]
			}
			out[c*4+r] = v
		}
	}
	return out
}

func mat4Point(m [16]float64, p vec3) vec3 {
	return vec3{
		m[0]*p[0] + m[4]*p[1] + m[8]*p[2] + m[12],
		m[1]*p[0] + m[5]*p[1] + m[9]*p[2] + m[13],
		m[2]*p[0] + m[6]*p[1] + m[10]*p[2] + m[14],
	}
}

// objFacts reads an OBJ model: its parts, its size, and its materials file.
func objFacts(full, rel string, has func(string) bool) fileFacts {
	x := fileFacts{Kind: "3d", Format: "OBJ"}
	f, err := os.Open(full)
	if err != nil {
		return x
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 64<<10), 8<<20)
	var bounds box3
	verts, tris, objects := 0, 0, 0
	mats := map[string]bool{}
	var libs []string
	// Its parts: the names on its o and g lines, each measured by the vertices its
	// faces use (an OBJ's parts have no transforms of their own, so that's where they are).
	var pts [][3]float32
	var named []part
	partAt := map[string]int{}
	cur := -1
	for sc.Scan() {
		line := bytes.TrimSpace(sc.Bytes())
		if len(line) < 2 {
			continue
		}
		switch {
		case line[0] == 'v' && (line[1] == ' ' || line[1] == '\t'):
			verts++
			fs := bytes.Fields(line[2:])
			var p vec3
			ok := len(fs) >= 3
			for k := 0; ok && k < 3; k++ {
				v, err := strconv.ParseFloat(string(fs[k]), 64)
				if err != nil {
					ok = false
					break
				}
				p[k] = v
			}
			if ok {
				bounds.add(p)
			} else {
				p = vec3{math.NaN(), 0, 0}
			}
			if len(pts) < objVertsMax {
				pts = append(pts, [3]float32{float32(p[0]), float32(p[1]), float32(p[2])})
			}
		case line[0] == 'f' && (line[1] == ' ' || line[1] == '\t'):
			fs := bytes.Fields(line[2:])
			if n := len(fs); n >= 3 {
				tris += n - 2
			}
			if cur >= 0 && verts <= objVertsMax {
				for _, fld := range fs {
					if i := objIndex(fld, len(pts)); i >= 0 && !math.IsNaN(float64(pts[i][0])) {
						named[cur].box.add(vec3{float64(pts[i][0]), float64(pts[i][1]), float64(pts[i][2])})
					}
				}
			}
		case (line[0] == 'o' || line[0] == 'g') && (line[1] == ' ' || line[1] == '\t'):
			objects++
			if name := string(bytes.TrimSpace(line[2:])); name != "" {
				i, ok := partAt[name]
				if !ok {
					i = len(named)
					partAt[name] = i
					named = append(named, part{name: name, order: i})
				}
				cur = i
			}
		case bytes.HasPrefix(line, []byte("usemtl ")):
			mats[string(bytes.TrimSpace(line[7:]))] = true
		case bytes.HasPrefix(line, []byte("mtllib ")):
			libs = append(libs, strings.Fields(string(line[7:]))...)
		}
	}
	var parts []string
	if objects > 1 {
		parts = append(parts, countOf(objects, "object", "objects"))
	}
	parts = append(parts, countOf(verts, "vertex", "vertices"), countOf(tris, "triangle", "triangles"))
	if len(mats) > 0 {
		parts = append(parts, countOf(len(mats), "material", "materials"))
	}
	x.Detail = strings.Join(parts, ", ")
	if bounds.ok {
		x.Detail += "; spans " + bounds.words("") + " (OBJ doesn't store its units: often metres, y up)"
	}
	var have, missing []string
	for _, l := range libs {
		p := path.Join(path.Dir(rel), l)
		if has(p) {
			have = append(have, "`"+p+"`")
		} else {
			missing = append(missing, l)
		}
	}
	if len(have) > 0 {
		x.Detail += "; its materials are in " + strings.Join(have, ", ")
	}
	x.Warn = needs3D("OBJLoader, with MTLLoader for its materials")
	if len(libs) == 0 {
		x.Warn = needs3D("OBJLoader")
	}
	if len(missing) > 0 {
		x.Warn += ". It names " + strings.Join(missing, ", ") + " for its materials, which " + wasnt(len(missing)) + " attached, so it would show without its colours and textures"
	}
	if len(named) >= 2 {
		if verts > objVertsMax { // too many to keep: names in the file's order, no sizes
			for i := range named {
				named[i].box = box3{}
			}
		}
		list, rest := partsWords(named, "")
		x.Parts = "Its parts, biggest first (the names on its o and g lines, which three.js's OBJLoader gives its meshes, for getObjectByName): " + list
		if rest > 0 {
			x.Parts += fmt.Sprintf(", and %s more, smaller", fmtNum(rest))
		}
		x.Parts += ". They all share one origin, so to turn one about its own hinge, put it in a Group placed at the hinge (a Box3 of the part shows where it is)"
	}
	return x
}

const objVertsMax = 8 << 20 // an OBJ's vertices kept to measure its parts (12 bytes each)

// objIndex is the vertex a face's field names ("12/5/7", "-3//2"), counted from 0,
// or -1 if there's no such vertex.
func objIndex(f []byte, n int) int {
	i, neg := 0, false
	if i < len(f) && (f[i] == '-' || f[i] == '+') {
		neg = f[i] == '-'
		i++
	}
	v, start := 0, i
	for i < len(f) && f[i] >= '0' && f[i] <= '9' && i-start < 10 {
		v = v*10 + int(f[i]-'0')
		i++
	}
	if i == start {
		return -1
	}
	if neg {
		v = n - v
	} else {
		v--
	}
	if v < 0 || v >= n {
		return -1
	}
	return v
}

// mtlFacts reads an OBJ model's materials file: its materials and the pictures they use.
func mtlFacts(full, rel string, has func(string) bool) fileFacts {
	x := fileFacts{Kind: "3d", Format: "OBJ materials (.mtl)"}
	b, err := os.ReadFile(full)
	if err != nil {
		return x
	}
	mats := 0
	var have, missing []string
	seen := map[string]bool{}
	for _, line := range strings.Split(string(b), "\n") {
		fs := strings.Fields(line)
		if len(fs) < 2 {
			continue
		}
		switch k := strings.ToLower(fs[0]); {
		case k == "newmtl":
			mats++
		case strings.HasPrefix(k, "map_") || k == "bump" || k == "disp" || k == "decal" || k == "norm" || k == "refl":
			name := mtlMapName(fs)
			if name == "" || seen[name] {
				continue
			}
			seen[name] = true
			p := path.Join(path.Dir(rel), name)
			if has(p) {
				have = append(have, "`"+p+"`")
			} else {
				missing = append(missing, name)
			}
		}
	}
	x.Detail = countOf(mats, "material", "materials")
	if len(have) > 0 {
		x.Detail += "; its textures: " + strings.Join(have, ", ")
	}
	if len(missing) > 0 {
		x.Warn = "It names " + strings.Join(missing, ", ") + ", which " + wasnt(len(missing)) + " attached"
	}
	return x
}

// mtlMapName is the picture a materials line names, after its options
// ("map_Bump -bm 0.5 bumps.png"); a name may have spaces in it.
func mtlMapName(fs []string) string {
	i := 1
	for i < len(fs)-1 && strings.HasPrefix(fs[i], "-") {
		i++
		for i < len(fs)-1 {
			if _, err := strconv.ParseFloat(fs[i], 64); err != nil && fs[i] != "on" && fs[i] != "off" && !(len(fs[i]) == 1 && strings.Contains("rgbmlz", fs[i])) {
				break
			}
			i++
		}
	}
	return strings.ReplaceAll(strings.Join(fs[i:], " "), "\\", "/")
}

// stlFacts reads an STL model (binary or text): its triangles and its size.
func stlFacts(full string, head []byte, size int64) fileFacts {
	x := fileFacts{Kind: "3d", Format: "STL", Warn: needs3D("STLLoader")}
	var bounds box3
	tris := 0
	f, err := os.Open(full)
	if err != nil {
		return x
	}
	defer f.Close()
	if len(head) >= 84 && 84+50*int64(binary.LittleEndian.Uint32(head[80:])) == size {
		n := int(binary.LittleEndian.Uint32(head[80:]))
		tris = n
		buf := make([]byte, 50*4096)
		r := bufio.NewReaderSize(io.NewSectionReader(f, 84, size-84), 1<<20)
		for done := 0; done < n; {
			k := min(4096, n-done)
			if _, err := io.ReadFull(r, buf[:50*k]); err != nil {
				break
			}
			for t := 0; t < k; t++ {
				tri := buf[50*t:]
				for v := 0; v < 3; v++ {
					o := 12 + 12*v
					bounds.add(vec3{
						float64(math.Float32frombits(binary.LittleEndian.Uint32(tri[o:]))),
						float64(math.Float32frombits(binary.LittleEndian.Uint32(tri[o+4:]))),
						float64(math.Float32frombits(binary.LittleEndian.Uint32(tri[o+8:]))),
					})
				}
			}
			done += k
		}
	} else {
		x.Format = "STL (text)"
		sc := bufio.NewScanner(f)
		sc.Buffer(make([]byte, 64<<10), 1<<20)
		for sc.Scan() {
			fs := strings.Fields(sc.Text())
			if len(fs) == 0 {
				continue
			}
			switch fs[0] {
			case "facet":
				tris++
			case "vertex":
				if len(fs) >= 4 {
					var p vec3
					for k := 0; k < 3; k++ {
						p[k], _ = strconv.ParseFloat(fs[k+1], 64)
					}
					bounds.add(p)
				}
			}
		}
	}
	x.Detail = countOf(tris, "triangle", "triangles")
	if bounds.ok {
		x.Detail += "; spans " + bounds.words("") + " (STL doesn't store its units: often millimetres)"
	}
	return x
}

// plyFacts reads a PLY model's header: its points and faces.
func plyFacts(head []byte) fileFacts {
	x := fileFacts{Kind: "3d", Format: "PLY", Warn: needs3D("PLYLoader")}
	var parts []string
	for _, line := range strings.Split(string(head), "\n") {
		fs := strings.Fields(line)
		if len(fs) == 0 {
			continue
		}
		if fs[0] == "end_header" {
			break
		}
		if fs[0] == "format" && len(fs) > 1 && fs[1] != "ascii" {
			x.Format = "PLY (binary)"
		}
		if fs[0] == "element" && len(fs) == 3 {
			if n, err := strconv.Atoi(fs[2]); err == nil {
				switch fs[1] {
				case "vertex":
					parts = append(parts, countOf(n, "vertex", "vertices"))
				case "face":
					parts = append(parts, countOf(n, "face", "faces"))
				}
			}
		}
	}
	x.Detail = strings.Join(parts, ", ")
	return x
}

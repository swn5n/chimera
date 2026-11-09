package main

// Files attached to a message for one of this computer's engines (like DeepSeek
// on InferSSD). The browser uploads each one first (POST /api/uploads), and the
// message names them; Start copies them into the chat's folder (making one in
// Documents/Chimera when the chat has none), where a page the model writes is
// previewed and saved, and the model is told each file's path and what it is.
// The model reads only text: it gets a text file's words and the facts of a
// picture or a 3D model (its size, its parts, its length), never what a
// picture shows.

import (
	"bytes"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"
)

const (
	attachFileMax  = 4 << 30 // one file
	attachCountMax = 2000    // files in one message
	attachListMax  = 200     // lines of the list the model gets; the files after them are counted by folder
	uploadKeep     = 24 * time.Hour
)

// chatAttachment is a file a message brings: uploaded first, then named here.
type chatAttachment struct {
	Upload string `json:"upload"` // the id POST /api/uploads gave it
	Path   string `json:"path"`   // its path in what was attached: "logo.png", or "site/img/logo.png" from a folder
}

// AttachedFile is a file attached to a message, as it is in the chat's folder.
type AttachedFile struct {
	Path   string `json:"path"`           // in the folder, with / between folders
	Name   string `json:"name,omitempty"` // its own name, when that had to change to be safe in a page
	Bytes  int64  `json:"bytes"`
	Kind   string `json:"kind,omitempty"` // picture, text, 3d, video, audio, font, document, archive, other
	Width  int    `json:"width,omitempty"`
	Height int    `json:"height,omitempty"`
	// Made by Chimera for this message, not attached: "turntable" (a frame or the
	// poster of From's turntable, turntable.go) or "glb" (From saved for web pages).
	Made string `json:"made,omitempty"`
	From string `json:"from,omitempty"`
	// A 3D model's turntable: the folder of its frames, or why none could be made.
	Turntable string `json:"turntable,omitempty"`
	NoTurn    string `json:"no_turn,omitempty"`
	// A 3D model's copy for web pages (webglb.go), or why none could be made.
	GLB   string `json:"glb,omitempty"`
	NoGLB string `json:"no_glb,omitempty"`
	// What a vision model saw in a picture (describe.go).
	Shows string `json:"shows,omitempty"`
}

// noteExtras is what the note says of a message's files as a whole.
type noteExtras struct {
	DescribedBy  string // the vision model that wrote the "What it shows" lines
	NotDescribed string // why some pictures have none (the rest weren't looked at)
}

func (a *App) uploadDir() string { return filepath.Join(a.dataDir, "uploads") }

// handleUpload keeps one file for a message that's about to be sent:
// POST /api/uploads?name=<its path in what was attached>, with the bytes as the body.
func (a *App) handleUpload(w http.ResponseWriter, r *http.Request) {
	if _, err := cleanAttachPath(r.URL.Query().Get("name")); err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	dir := a.uploadDir()
	if err := os.MkdirAll(dir, 0o700); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	sweepUploadsSometimes(dir)
	id := randomID(12)
	p := filepath.Join(dir, id)
	f, err := os.OpenFile(p, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	n, err := io.Copy(f, http.MaxBytesReader(w, r.Body, attachFileMax))
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	if err != nil {
		_ = os.Remove(p)
		var tooBig *http.MaxBytesError
		if errors.As(err, &tooBig) {
			writeErr(w, 413, fmt.Sprintf("A file can be up to %d GB.", attachFileMax>>30))
			return
		}
		writeErr(w, 500, "couldn't keep that file: "+err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"id": id, "bytes": n})
}

var uploadSweeps = struct {
	sync.Mutex
	at map[string]time.Time
}{at: map[string]time.Time{}}

// sweepUploadsSometimes removes what was uploaded for messages never sent, at
// most every ten minutes (a folder of 2,000 files is uploaded one by one).
func sweepUploadsSometimes(dir string) {
	uploadSweeps.Lock()
	last := uploadSweeps.at[dir]
	due := time.Since(last) > 10*time.Minute
	if due {
		uploadSweeps.at[dir] = time.Now()
	}
	uploadSweeps.Unlock()
	if due {
		sweepUploads(dir, uploadKeep)
	}
}

func sweepUploads(dir string, keep time.Duration) {
	entries, _ := os.ReadDir(dir)
	for _, e := range entries {
		if info, err := e.Info(); err == nil && time.Since(info.ModTime()) > keep {
			_ = os.Remove(filepath.Join(dir, e.Name()))
		}
	}
}

// cleanAttachPath makes an attached file's path safe in the chat's folder and
// in a page: nothing can leave the folder, nothing hidden comes in, and the
// characters that break a web address (# ? % : and the like) become "-". Names
// otherwise stay as they were, so files that name each other (a .gltf and its
// textures, an .obj and its .mtl, a site's pages) still find each other.
func cleanAttachPath(p string) (string, error) {
	var parts []string
	for _, seg := range strings.Split(strings.ReplaceAll(p, "\\", "/"), "/") {
		seg = strings.TrimSpace(seg)
		if seg == "" || seg == "." {
			continue
		}
		if seg == ".." {
			return "", errors.New("a file's path can't leave its folder")
		}
		if strings.HasPrefix(seg, ".") {
			return "", errors.New("hidden files aren't attached")
		}
		parts = append(parts, safeAttachName(seg))
	}
	if len(parts) == 0 {
		return "", errors.New("that file has no name")
	}
	if len(parts) > 16 {
		return "", errors.New("that file is too many folders deep")
	}
	return strings.Join(parts, "/"), nil
}

func safeAttachName(seg string) string {
	out := strings.TrimSpace(strings.Map(func(r rune) rune {
		if r < 32 || r == 0x7f || unicode.Is(unicode.Cf, r) || strings.ContainsRune(`#?%:\"<>|*`, r) {
			return '-'
		}
		return r
	}, seg))
	if out == "" || strings.HasPrefix(out, ".") {
		out = "file" + out
	}
	if r := []rune(out); len(r) > 100 { // keep the extension when cutting a long name
		ext := []rune(path.Ext(out))
		if len(ext) > 12 {
			ext = nil
		}
		out = string(r[:100-len(ext)]) + string(ext)
	}
	return out
}

// newChatFolder makes a folder for a chat's files and pages, named after the
// chat, in Documents/Chimera (or ~/Chimera where there's no Documents).
func newChatFolder(title string) (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	base := filepath.Join(home, "Documents")
	if st, err := os.Stat(base); err != nil || !st.IsDir() {
		base = home
	}
	root := filepath.Join(base, "Chimera")
	if err := os.MkdirAll(root, 0o755); err != nil {
		return "", err
	}
	name := folderNameFrom(title)
	for n := 1; n < 1000; n++ {
		cand := name
		if n > 1 {
			cand = fmt.Sprintf("%s %d", name, n)
		}
		p := filepath.Join(root, cand)
		err := os.Mkdir(p, 0o755)
		if err == nil {
			return p, nil
		}
		if !errors.Is(err, os.ErrExist) {
			return "", err
		}
		if entries, err := os.ReadDir(p); err == nil && len(entries) == 0 {
			return p, nil
		}
	}
	return "", errors.New("couldn't make a folder for this chat in " + root)
}

func folderNameFrom(title string) string {
	t := strings.Map(func(r rune) rune {
		if r < 32 || strings.ContainsRune(`/\:*?"<>|`, r) {
			return ' '
		}
		return r
	}, strings.TrimSuffix(title, "…"))
	t = strings.Trim(strings.Join(strings.Fields(t), " "), ". ")
	if r := []rune(t); len(r) > 60 {
		t = strings.TrimSpace(string(r[:60]))
	}
	if t == "" || t == "New chat" {
		t = "Chat " + time.Now().Format("2006-01-02")
	}
	return t
}

// placeAttachments moves uploaded files into folder, at their own paths. A file
// already there with the same bytes is used as it is (attaching a folder twice
// copies nothing twice); a different file with that name gets a number
// ("logo-2.png"). Nothing is moved unless every file can be.
func placeAttachments(uploads, folder string, atts []chatAttachment) ([]AttachedFile, error) {
	type item struct {
		src, rel, name string
		size           int64
	}
	items := make([]item, 0, len(atts))
	for _, at := range atts {
		if !validID(at.Upload) {
			return nil, errors.New("a file didn't arrive in one piece: attach it again")
		}
		src := filepath.Join(uploads, at.Upload)
		st, err := os.Stat(src)
		if err != nil || !st.Mode().IsRegular() {
			return nil, fmt.Errorf("%s didn't arrive (or was sent over a day ago): attach it again", path.Base(at.Path))
		}
		rel, err := cleanAttachPath(at.Path)
		if err != nil {
			return nil, fmt.Errorf("%s: %v", at.Path, err)
		}
		name := path.Base(strings.ReplaceAll(strings.TrimSpace(at.Path), "\\", "/"))
		if name == path.Base(rel) {
			name = ""
		}
		items = append(items, item{src: src, rel: rel, name: name, size: st.Size()})
	}
	root, err := filepath.EvalSymlinks(folder)
	if err != nil {
		return nil, fmt.Errorf("the chat's folder isn't there: %v", err)
	}
	taken := map[string]bool{} // this message's paths (in any case: most Mac disks don't tell case apart)
	out := make([]AttachedFile, 0, len(items))
	for _, it := range items {
		// The chat's own folder dropped in (to show the model what's there): its
		// files are in place already, so they're used where they are.
		if first, rest, ok := strings.Cut(it.rel, "/"); ok && strings.EqualFold(first, filepath.Base(folder)) && !taken[strings.ToLower(rest)] {
			if st, err := os.Lstat(filepath.Join(root, filepath.FromSlash(rest))); err == nil && st.Mode().IsRegular() && st.Size() == it.size &&
				sameBytes(it.src, filepath.Join(root, filepath.FromSlash(rest))) {
				if full, err := insideFolder(root, rest); err == nil && full != "" {
					_ = os.Remove(it.src)
					taken[strings.ToLower(rest)] = true
					out = append(out, AttachedFile{Path: rest, Name: it.name, Bytes: it.size})
					continue
				}
			}
		}
		rel, same, err := freeAttachPath(root, it.rel, it.src, it.size, taken)
		if err != nil {
			return out, fmt.Errorf("%s: %v", it.rel, err)
		}
		taken[strings.ToLower(rel)] = true
		dst := filepath.Join(root, filepath.FromSlash(rel))
		if same {
			_ = os.Remove(it.src)
		} else if err := moveFile(it.src, dst); err != nil {
			return out, fmt.Errorf("couldn't copy %s into the chat's folder: %v", rel, err)
		}
		out = append(out, AttachedFile{Path: rel, Name: it.name, Bytes: it.size})
	}
	return out, nil
}

// freeAttachPath finds where a file goes: its own path if that's free (or holds
// the same bytes already), else the same name with a number.
func freeAttachPath(root, rel, src string, size int64, taken map[string]bool) (string, bool, error) {
	ext := path.Ext(rel)
	stem := strings.TrimSuffix(rel, ext)
	for n := 1; n < 1000; n++ {
		cand := rel
		if n > 1 {
			cand = fmt.Sprintf("%s-%d%s", stem, n, ext)
		}
		if taken[strings.ToLower(cand)] {
			continue
		}
		dst := filepath.Join(root, filepath.FromSlash(cand))
		dir := filepath.Dir(dst)
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return "", false, err
		}
		// A folder on the way may be a link: the file must still land inside.
		real, err := filepath.EvalSymlinks(dir)
		if err != nil || (real != root && !strings.HasPrefix(real, root+string(filepath.Separator))) {
			return "", false, errors.New("that path leads out of the chat's folder")
		}
		st, err := os.Lstat(dst)
		if errors.Is(err, os.ErrNotExist) {
			return cand, false, nil
		}
		if err == nil && st.Mode().IsRegular() && st.Size() == size && sameBytes(src, dst) {
			return cand, true, nil
		}
	}
	return "", false, errors.New("too many files with that name")
}

func sameBytes(a, b string) bool {
	sum := func(p string) []byte {
		f, err := os.Open(p)
		if err != nil {
			return nil
		}
		defer f.Close()
		h := sha256.New()
		if _, err := io.Copy(h, f); err != nil {
			return nil
		}
		return h.Sum(nil)
	}
	x, y := sum(a), sum(b)
	return x != nil && bytes.Equal(x, y)
}

// moveFile moves src to dst (copying when they're on different disks), as a
// file anyone on this computer can read, like one saved from a browser.
func moveFile(src, dst string) error {
	if err := os.Rename(src, dst); err != nil {
		in, err := os.Open(src)
		if err != nil {
			return err
		}
		defer in.Close()
		out, err := os.OpenFile(dst, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
		if err != nil {
			return err
		}
		if _, err := io.Copy(out, in); err != nil {
			out.Close()
			_ = os.Remove(dst)
			return err
		}
		if err := out.Close(); err != nil {
			_ = os.Remove(dst)
			return err
		}
		_ = os.Remove(src)
	}
	return os.Chmod(dst, 0o644)
}

// ---------- what the model is told ----------

// describeAttachments fills in each file's kind and size in pixels, and writes
// what the model is told about them: the folder they're in, each file's path and
// facts, and the words of the text files, as far as textBudget characters go.
func describeAttachments(folder string, files []AttachedFile, textBudget int) ([]AttachedFile, string) {
	return describeAttachmentsWith(folder, files, textBudget, noteExtras{})
}

// attachFacts reads each file's facts, and fills in its kind and size in pixels.
// Chimera's own turntable frames are cut-outs, whatever their header says.
func attachFacts(folder string, files []AttachedFile) []fileFacts {
	present := map[string]bool{} // what the folder holds now, for the files a model or a page needs next to it
	facts := make([]fileFacts, len(files))
	for i := range files {
		present[strings.ToLower(files[i].Path)] = true
	}
	has := func(rel string) bool {
		if present[strings.ToLower(rel)] {
			return true
		}
		full, err := insideFolder(folder, rel)
		return err == nil && fileExists(full)
	}
	for i := range files {
		x := readFacts(filepath.Join(folder, filepath.FromSlash(files[i].Path)), files[i].Path, files[i].Bytes, has)
		if files[i].Made == "turntable" && x.Kind == "picture" {
			x.Alpha = "transparent background"
		}
		facts[i] = x
		files[i].Kind, files[i].Width, files[i].Height = x.Kind, x.Width, x.Height
	}
	return facts
}

// attachOrder is the files' order in the list: as people sort names.
func attachOrder(files []AttachedFile) []int {
	order := make([]int, len(files))
	for i := range order {
		order[i] = i
	}
	sort.SliceStable(order, func(i, j int) bool { return natLess(files[order[i]].Path, files[order[j]].Path) })
	return order
}

func describeAttachmentsWith(folder string, files []AttachedFile, textBudget int, ex noteExtras) ([]AttachedFile, string) {
	if len(files) == 0 {
		return files, ""
	}
	facts := attachFacts(folder, files)
	order := attachOrder(files)

	var total, madeBytes int64
	made, frames, glbs := 0, 0, 0
	turned := map[string]bool{} // the models with a turntable here
	for _, f := range files {
		if f.Made != "" {
			made++
			madeBytes += f.Bytes
			if f.Made == "glb" {
				glbs++
			} else {
				frames++
				turned[f.From] = true
			}
		} else {
			total += f.Bytes
		}
	}
	var b strings.Builder
	switch attached := len(files) - made; {
	case attached == 1 && made == 0:
		fmt.Fprintf(&b, "Attached file (%s), copied into this chat's folder, %s.", humanBytes(total), folder)
	case made == 0:
		fmt.Fprintf(&b, "Attached files: %s (%s in all), copied into this chat's folder, %s.", fmtNum(attached), humanBytes(total), folder)
	default: // what Chimera made of them is there too: turntables, copies for pages
		var what, whose []string
		if frames > 0 {
			what = append(what, countOf(frames, "picture", "pictures"))
			whose = append(whose, countOf(len(turned), "turntable", "turntables"))
		}
		if glbs > 0 {
			what = append(what, countOf(glbs, "GLB", "GLBs"))
			whose = append(whose, countOf(glbs, "copy for web pages", "copies for web pages"))
		}
		them := "them"
		if attached == 1 {
			them = "it"
		}
		fmt.Fprintf(&b, "Attached files: %s (%s in all), copied into this chat's folder, %s, with %s Chimera made from %s (%s): %s.",
			fmtNum(attached), humanBytes(total), folder, strings.Join(what, " and "), them, humanBytes(madeBytes), strings.Join(whose, " and "))
	}
	b.WriteString(" A page written in this chat is shown and saved in that folder, so it can use them by these paths, relative to the page, written exactly as here")
	for _, f := range files {
		if strings.ContainsAny(f.Path, " ()'") {
			b.WriteString(` (a path with spaces or brackets works as it is in HTML and in a script; in CSS, put it in quotes: url("…"))`)
			break
		}
	}
	b.WriteString(":\n")

	lines := attachLines(files, facts, order)
	shown := 0
	for _, l := range lines {
		if shown == attachListMax {
			break
		}
		b.WriteString(l.text + "\n")
		shown++
	}
	if shown < len(lines) {
		b.WriteString(moreLine(files, facts, lines[shown:]) + "\n")
	}

	// The words of the text files, in the order they're listed, while the budget lasts.
	var texts strings.Builder
	left := textBudget
	for _, l := range lines[:shown] {
		x := facts[l.idx]
		if l.seq || (!x.Text && x.Words == "") {
			continue
		}
		f := files[l.idx]
		if left < 2000 {
			fmt.Fprintf(&texts, "\n`%s`: not included, since this message has a lot of text already (a page can load it from its path).\n", f.Path)
			continue
		}
		var body string
		var cut bool
		var lineCount int
		if x.Words != "" {
			body, cut, lineCount = cutText(x.Words, left)
		} else if raw, err := os.ReadFile(filepath.Join(folder, filepath.FromSlash(f.Path))); err == nil {
			body, cut, lineCount = cutText(string(bytes.TrimPrefix(raw, []byte("\xef\xbb\xbf"))), left)
		} else {
			continue
		}
		left -= len(body)
		head := "`" + f.Path + "`"
		switch n := strings.Count(body, "\n") + 1; {
		case cut && n < lineCount:
			head += fmt.Sprintf(" (its first %s of %s lines; a page can load all of it from its path)", fmtNum(n), fmtNum(lineCount))
		case cut: // one long line, like a minified script
			head += fmt.Sprintf(" (its first %s of %s characters; a page can load all of it from its path)", fmtNum(len(body)), fmtNum(int(f.Bytes)))
		}
		fence := codeFence(body)
		fmt.Fprintf(&texts, "\n%s:\n%s%s\n%s\n%s\n", head, fence, fenceLang(f.Path), strings.TrimRight(body, "\n"), fence)
	}
	if texts.Len() > 0 {
		b.WriteString("\nThe text files' words:\n")
		b.WriteString(texts.String())
	}
	// Pictures by line: a numbered run is one, described by its first frame, and a
	// turntable's poster is its frame 0 again.
	pics, seen := 0, 0
	for _, l := range lines {
		f := files[l.idx]
		if facts[l.idx].Kind != "picture" || (f.Made == "turntable" && !l.seq) {
			continue
		}
		pics++
		if f.Shows != "" {
			seen++
		}
	}
	switch {
	case seen > 0:
		fmt.Fprintf(&b, "\nThe \"what it shows\" parts were written by %s, a vision model on this computer, from a copy at most %s px across: it can be wrong about details, so treat words it read with care.", ex.DescribedBy, fmtNum(describePx))
		if seen < pics {
			why := ex.NotDescribed
			if why == "" {
				why = "they weren't looked at"
			}
			b.WriteString(" The pictures without one come with only their facts (" + why + ").")
		}
		b.WriteString("\n")
	case pics == 1 && len(files) == 1:
		b.WriteString("\nOnly these facts about the picture come with this message, not what it shows.\n")
	case pics > 0:
		b.WriteString("\nOnly these facts about the pictures come with this message, not what they show.\n")
	}
	return files, strings.TrimRight(b.String(), "\n")
}

type attachLine struct {
	text  string
	idx   int  // the file (the first of a numbered run)
	seq   bool // a numbered run of files on one line
	count int
	bytes int64
}

var numberedRe = regexp.MustCompile(`^(.*?)(\d+)(\D*)$`)

// attachLines lists the files, one line each, except that a run of numbered
// files alike in kind and size ("f00.webp" … "f71.webp", the frames of a turn)
// goes on one line. Text files always get a line of their own (their words go
// to the model).
func attachLines(files []AttachedFile, facts []fileFacts, order []int) []attachLine {
	type run struct {
		nums []int
		idx  []int
	}
	runs := map[string]*run{}
	keyOf := func(i int) (string, int, bool) {
		dir, base := path.Split(files[i].Path)
		m := numberedRe.FindStringSubmatch(base)
		x := facts[i]
		if m == nil || len(m[2]) > 9 || x.Text {
			return "", 0, false
		}
		n, _ := strconv.Atoi(m[2])
		return strings.Join([]string{dir, m[1], m[3], x.Kind, x.Format, strconv.Itoa(x.Width), strconv.Itoa(x.Height), x.Alpha}, "\x00"), n, true
	}
	for _, i := range order {
		if k, n, ok := keyOf(i); ok {
			if runs[k] == nil {
				runs[k] = &run{}
			}
			runs[k].nums = append(runs[k].nums, n)
			runs[k].idx = append(runs[k].idx, i)
		}
	}
	inRun := map[int]*run{}
	for _, r := range runs {
		if len(r.idx) < 4 {
			continue
		}
		sort.Sort(byNum{r.nums, r.idx})
		// One step apart, and written one way: all padded to one width ("f00"
		// … "f71") or none padded ("f1" … "f72").
		ok, width, padded := true, -1, false
		for j, i := range r.idx {
			d := numberIn(files[i].Path)
			if j > 0 && r.nums[j] != r.nums[j-1]+1 {
				ok = false
				break
			}
			if len(d) > 1 && d[0] == '0' {
				padded = true
			}
			if width == -1 {
				width = len(d)
			} else if width != len(d) {
				width = 0
			}
		}
		if padded && width <= 0 {
			ok = false
		}
		if ok {
			for _, i := range r.idx {
				inRun[i] = r
			}
		}
	}
	var lines []attachLine
	done := map[*run]bool{}
	for _, i := range order {
		if r := inRun[i]; r != nil {
			if done[r] {
				continue
			}
			done[r] = true
			var sum int64
			for _, j := range r.idx {
				sum += files[j].Bytes
			}
			first, last := files[r.idx[0]], files[r.idx[len(r.idx)-1]]
			x := facts[r.idx[0]]
			text := fmt.Sprintf("- `%s` to `%s`: %s, %s in all, numbered %s to %s",
				first.Path, last.Path, factsWords(x, 0, len(r.idx)), humanBytes(sum),
				numberIn(first.Path), numberIn(last.Path))
			if first.Made == "turntable" && first.From != "" {
				text += ". " + turnWords(first.From, len(r.idx))
			}
			if first.Shows != "" {
				text += fmt.Sprintf(". What `%s` shows: %s", path.Base(first.Path), first.Shows)
			}
			lines = append(lines, attachLine{idx: r.idx[0], seq: true, count: len(r.idx), bytes: sum, text: text})
			continue
		}
		lines = append(lines, attachLine{idx: i, count: 1, bytes: files[i].Bytes, text: attachFileLine(files[i], facts[i], files)})
	}
	return lines
}

type byNum struct {
	nums []int
	idx  []int
}

func (b byNum) Len() int           { return len(b.nums) }
func (b byNum) Less(i, j int) bool { return b.nums[i] < b.nums[j] }
func (b byNum) Swap(i, j int) {
	b.nums[i], b.nums[j] = b.nums[j], b.nums[i]
	b.idx[i], b.idx[j] = b.idx[j], b.idx[i]
}

func numberIn(p string) string {
	if m := numberedRe.FindStringSubmatch(path.Base(p)); m != nil {
		return m[2]
	}
	return ""
}

func attachFileLine(f AttachedFile, x fileFacts, all []AttachedFile) string {
	line := "- `" + f.Path + "`: " + factsWords(x, f.Bytes, 1)
	if f.Name != "" {
		line += fmt.Sprintf(" (originally %q)", f.Name)
	}
	if f.Made == "turntable" && f.From != "" {
		line += fmt.Sprintf(". Frame 0 of the turntable of `%s`, a little sharper: to show until the frames load", f.From)
	}
	if f.Made == "glb" && f.From != "" {
		var fromSize int64
		for _, g := range all {
			if g.Path == f.From {
				fromSize = g.Bytes
			}
		}
		line += ". " + webWords(f.From, f.Bytes, fromSize)
	}
	if x.Detail != "" {
		line += ". " + x.Detail
	}
	if x.Warn != "" {
		line += ". " + x.Warn
	}
	glb := ""
	for _, g := range all {
		if f.GLB != "" && g.Path == f.GLB && g.Made == "glb" {
			glb = g.Path
			line += fmt.Sprintf(". Chimera saved a copy of it for web pages, much quicker to load: `%s` (%s)", g.Path, humanBytes(g.Bytes))
		}
	}
	if f.Turntable != "" {
		frames := 0
		for _, g := range all {
			if g.Made == "turntable" && g.From == f.Path && numberIn(g.Path) != "" {
				frames++
			}
		}
		line += fmt.Sprintf(". Without a 3D library, its turntable will do: Chimera rendered %d frames of it turning, in `%s/`", frames, f.Turntable)
	}
	switch {
	case x.Parts != "" && glb != "": // the copy's line lists them, as a page that loads it finds them
		line += fmt.Sprintf(". Its parts are listed with `%s`", glb)
	case x.Parts != "":
		line += ". " + x.Parts
	}
	switch {
	case f.NoTurn != "" && f.NoTurn == f.NoGLB:
		line += ". Chimera couldn't make a turntable or a copy for web pages of it: " + strings.TrimSuffix(f.NoTurn, ".")
	case f.NoTurn != "" || f.NoGLB != "":
		if f.NoTurn != "" {
			line += ". No turntable could be made of it here: " + strings.TrimSuffix(f.NoTurn, ".")
		}
		if f.NoGLB != "" {
			line += ". No copy for web pages could be made of it here: " + strings.TrimSuffix(f.NoGLB, ".")
		}
	}
	if f.Shows != "" {
		line += ". What it shows: " + f.Shows
	}
	return line
}

// factsWords says what a file is: "picture, PNG, 2000 × 653, transparent
// background, 120 KB". With n > 1 it says it of n files alike (no size).
func factsWords(x fileFacts, size int64, n int) string {
	kind := kindWord(x.Kind)
	if n > 1 {
		kind = fmt.Sprintf("%d %s", n, kindPlural(x.Kind))
	}
	parts := []string{kind}
	if x.Format != "" {
		parts = append(parts, x.Format)
	}
	if x.Width > 0 && x.Height > 0 {
		parts = append(parts, fmt.Sprintf("%d × %d", x.Width, x.Height))
	}
	if x.Frames > 1 {
		parts = append(parts, fmt.Sprintf("animated, %d frames", x.Frames))
	}
	if x.Secs > 0 {
		parts = append(parts, fmtSecs(x.Secs))
	}
	if x.Alpha != "" {
		parts = append(parts, x.Alpha)
	}
	if n == 1 {
		parts = append(parts, humanBytes(size))
	}
	return strings.Join(parts, ", ")
}

func kindWord(k string) string {
	switch k {
	case "picture", "video", "font", "document", "archive":
		return k
	case "text":
		return "text"
	case "3d":
		return "3D model"
	case "audio":
		return "sound"
	}
	return "file"
}

func kindPlural(k string) string {
	switch k {
	case "text":
		return "text files"
	case "3d":
		return "3D models"
	case "audio":
		return "sounds"
	case "picture", "video", "font", "document", "archive":
		return k + "s"
	}
	return "files"
}

// moreLine counts the files the list leaves out, by kind and by folder.
func moreLine(files []AttachedFile, facts []fileFacts, rest []attachLine) string {
	n := 0
	var size int64
	kinds := map[string]int{}
	dirs := map[string]int{}
	for _, l := range rest {
		n += l.count
		size += l.bytes
		kinds[facts[l.idx].Kind] += l.count
		d := path.Dir(files[l.idx].Path)
		if d == "." {
			d = "the top of the folder"
		} else {
			d = "`" + d + "/`"
		}
		dirs[d] += l.count
	}
	var ks []string
	for k, c := range kinds {
		ks = append(ks, fmt.Sprintf("%d %s", c, map[bool]string{true: kindWord(k), false: kindPlural(k)}[c == 1]))
	}
	sort.Strings(ks)
	var ds []string
	for d, c := range dirs {
		ds = append(ds, fmt.Sprintf("%s (%d)", d, c))
	}
	sort.Strings(ds)
	if len(ds) > 12 {
		ds = append(ds[:12], "and more")
	}
	return fmt.Sprintf("- and %s more not listed here (%s; %s), in %s", fmtNum(n), strings.Join(ks, ", "), humanBytes(size), strings.Join(ds, ", "))
}

// natLess orders paths as people do: "f2" before "f10", folders together.
func natLess(a, b string) bool {
	al, bl := strings.ToLower(a), strings.ToLower(b)
	for al != "" && bl != "" {
		ad, bd := leadingDigits(al), leadingDigits(bl)
		if ad != "" && bd != "" {
			an, _ := strconv.Atoi(strings.TrimLeft(ad, "0") + "0")
			bn, _ := strconv.Atoi(strings.TrimLeft(bd, "0") + "0")
			if an != bn {
				return an < bn
			}
			al, bl = al[len(ad):], bl[len(bd):]
			continue
		}
		if al[0] != bl[0] {
			// a folder's files ("a/x") come before the names after it ("a-b")
			if al[0] == '/' {
				return true
			}
			if bl[0] == '/' {
				return false
			}
			return al[0] < bl[0]
		}
		al, bl = al[1:], bl[1:]
	}
	if len(al) != len(bl) {
		return len(al) < len(bl)
	}
	return a < b
}

func leadingDigits(s string) string {
	i := 0
	for i < len(s) && i < 9 && s[i] >= '0' && s[i] <= '9' {
		i++
	}
	return s[:i]
}

// cutText is a text, or as much of it as fits in limit bytes (cut at a line),
// whether it was cut, and how many lines it has in all.
func cutText(s string, limit int) (string, bool, int) {
	s = strings.ReplaceAll(s, "\r\n", "\n")
	lines := strings.Count(strings.TrimRight(s, "\n"), "\n") + 1
	if len(s) <= limit {
		return s, false, lines
	}
	for limit > 0 && !utf8RuneStart(s[limit]) {
		limit--
	}
	cut := s[:limit]
	if i := strings.LastIndexByte(cut, '\n'); i > 0 {
		cut = cut[:i]
	}
	return cut, true, lines
}

// codeFence is a fence the text can't close: longer than any run of ~ in it.
func codeFence(s string) string {
	longest, run := 0, 0
	for _, r := range s {
		if r == '~' {
			run++
			if run > longest {
				longest = run
			}
		} else {
			run = 0
		}
	}
	if longest < 3 {
		return "~~~"
	}
	return strings.Repeat("~", longest+1)
}

func fenceLang(p string) string {
	switch strings.ToLower(path.Ext(p)) {
	case ".html", ".htm":
		return "html"
	case ".css":
		return "css"
	case ".js", ".mjs", ".cjs":
		return "js"
	case ".ts", ".tsx":
		return "ts"
	case ".jsx":
		return "jsx"
	case ".json", ".gltf":
		return "json"
	case ".py":
		return "python"
	case ".md", ".markdown":
		return "markdown"
	case ".csv":
		return "csv"
	case ".svg", ".xml":
		return "xml"
	case ".sh":
		return "sh"
	case ".go":
		return "go"
	case ".yaml", ".yml":
		return "yaml"
	}
	return "text"
}

func withFilesNote(text, note string) string {
	switch {
	case note == "":
		return text
	case text == "":
		return note
	}
	return text + "\n\n" + note
}

func humanBytes(n int64) string {
	switch {
	case n >= 1<<30:
		return trimZero(fmt.Sprintf("%.1f", float64(n)/(1<<30))) + " GB"
	case n >= 1<<20:
		return trimZero(fmt.Sprintf("%.1f", float64(n)/(1<<20))) + " MB"
	case n >= 1<<10:
		return fmt.Sprintf("%d KB", (n+512)>>10)
	}
	return fmt.Sprintf("%d bytes", n)
}

func trimZero(s string) string { return strings.TrimSuffix(s, ".0") }

func fmtSecs(s float64) string {
	switch {
	case s >= 3600:
		return fmt.Sprintf("%d h %02d min", int(s)/3600, int(s)%3600/60)
	case s >= 60:
		return fmt.Sprintf("%d min %02d s", int(s)/60, int(s)%60)
	}
	return trimZero(fmt.Sprintf("%.1f", s)) + " s"
}

// ---------- the chat page's view of them ----------

// serveAttached shows a picture attached to one of a chat's messages (for the
// chat's own page: its thumbnails). Only pictures, only files a message names.
func (a *App) serveAttached(w http.ResponseWriter, r *http.Request) {
	sess, err := a.sessions.Get(r.PathValue("id"))
	if err != nil {
		writeErr(w, 404, "no such chat")
		return
	}
	rel := r.PathValue("path")
	folder := ""
	for _, m := range sess.Messages {
		for _, f := range m.Attached {
			if f.Path == rel && m.AttachedIn != "" {
				folder = m.AttachedIn
			}
		}
	}
	if folder == "" {
		writeErr(w, 404, "no such file")
		return
	}
	full, err := insideFolder(folder, rel)
	if err != nil {
		writeErr(w, 404, "no such file")
		return
	}
	f, err := os.Open(full)
	if err != nil {
		writeErr(w, 404, "that file isn't in the chat's folder any more")
		return
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil || !st.Mode().IsRegular() {
		writeErr(w, 404, "no such file")
		return
	}
	head := make([]byte, 512)
	n, _ := io.ReadFull(f, head)
	mime := http.DetectContentType(head[:n])
	switch mime {
	case "image/png", "image/jpeg", "image/webp", "image/gif":
	default:
		writeErr(w, 404, "only pictures are shown here")
		return
	}
	if _, err := f.Seek(0, io.SeekStart); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	w.Header().Set("Content-Type", mime)
	w.Header().Set("Content-Security-Policy", "default-src 'none'; sandbox")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Cache-Control", "private, max-age=300")
	http.ServeContent(w, r, st.Name(), st.ModTime(), f)
}

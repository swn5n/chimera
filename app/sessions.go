package main

// Chats live on your own computer, in the data folder. The hub and the
// devices that run your steps never keep them.

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

type SessionMessage struct {
	Role      string    `json:"role"`
	Content   string    `json:"content"`
	Thinking  string    `json:"thinking,omitempty"`
	Model     string    `json:"model,omitempty"`
	Device    string    `json:"device,omitempty"`
	Owner     string    `json:"owner,omitempty"`
	Tokens    int       `json:"tokens,omitempty"`
	TokPerSec float64   `json:"tok_s,omitempty"`
	Credits   float64   `json:"credits,omitempty"`
	Free      bool      `json:"free,omitempty"`
	Local     bool      `json:"local,omitempty"`
	At        time.Time `json:"at"`
	Status    string    `json:"status,omitempty"` // "", pending, error, cancelled
	Error     string    `json:"error,omitempty"`
	GenID     string    `json:"gen_id,omitempty"`
	Note      string    `json:"note,omitempty"` // e.g. "nobody was lending, so it ran here"

	Rating     int         `json:"rating,omitempty"`
	RatingNote string      `json:"rating_note,omitempty"`
	RatingSent bool        `json:"rating_sent,omitempty"` // sent to the network's library
	Task       *TaskRecord `json:"task,omitempty"`        // a Hydra long task
	TaskID     string      `json:"task_id,omitempty"`

	Files  []SessionFile `json:"files,omitempty"`   // pictures sent with a message, or made by a plugin
	Plugin string        `json:"plugin,omitempty"`  // the plugin that made this reply (its rating goes there)
	StepID string        `json:"step_id,omitempty"` // the network step that ran it (rated once, by its asker)

	// Files attached for an engine (attach.go): copied into AttachedIn (the chat's
	// folder then), and FilesNote is what the model is told about them, after your words.
	Attached   []AttachedFile `json:"attached,omitempty"`
	AttachedIn string         `json:"attached_in,omitempty"`
	FilesNote  string         `json:"files_note,omitempty"`

	PromptTokens int     `json:"prompt_tokens,omitempty"`
	ThinkLevel   string  `json:"think_level,omitempty"` // the thinking asked of an engine
	ThinkSecs    float64 `json:"think_s,omitempty"`     // how long it thought before answering
	WaitSecs     float64 `json:"wait_s,omitempty"`      // how long until its first word
	Cut          bool    `json:"cut,omitempty"`         // it stopped at its output limit
}

// SessionFile is a file kept with a chat (in sessions/files/<chat>/<id>).
type SessionFile struct {
	ID     string `json:"id"`
	Name   string `json:"name"`
	MIME   string `json:"mime"`
	Bytes  int    `json:"bytes"`
	Width  int    `json:"width,omitempty"`
	Height int    `json:"height,omitempty"`
}

type Session struct {
	ID       string           `json:"id"`
	Title    string           `json:"title"`
	Named    bool             `json:"named,omitempty"`  // the title was given by hand: keep it
	Group    string           `json:"group,omitempty"`  // the sidebar group it's in
	Folder   string           `json:"folder,omitempty"` // where its pages load their pictures and files from
	Created  time.Time        `json:"created"`
	Updated  time.Time        `json:"updated"`
	Messages []SessionMessage `json:"messages"`
}

type SessionSummary struct {
	ID      string    `json:"id"`
	Title   string    `json:"title"`
	Created time.Time `json:"created"`
	Updated time.Time `json:"updated"`
	Count   int       `json:"count"`
	Group   string    `json:"group,omitempty"`
	Folder  string    `json:"folder,omitempty"`
	Model   string    `json:"model,omitempty"`   // the last reply's model
	Pending bool      `json:"pending,omitempty"` // its last reply is still being written (or was cut off by a restart)
	Snippet string    `json:"snippet,omitempty"` // for a search: the text around the first match
}

// ChatGroup is a group of chats in the sidebar.
type ChatGroup struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	Collapsed bool   `json:"collapsed,omitempty"`
}

type SessionStore struct {
	dir string
	mu  sync.Mutex
	// What List last read of each chat file, so it only rereads the ones that changed.
	cache map[string]cachedSummary
}

type cachedSummary struct {
	mod  time.Time
	size int64
	sum  SessionSummary
}

func NewSessionStore(dataDir string) *SessionStore {
	d := filepath.Join(dataDir, "sessions")
	_ = os.MkdirAll(d, 0o755)
	return &SessionStore{dir: d, cache: map[string]cachedSummary{}}
}

func validID(id string) bool {
	if id == "" || len(id) > 64 {
		return false
	}
	for _, r := range id {
		if !(r >= 'a' && r <= 'z' || r >= '0' && r <= '9') {
			return false
		}
	}
	return true
}

func (s *SessionStore) path(id string) string { return filepath.Join(s.dir, id+".json") }

func (s *SessionStore) Get(id string) (*Session, error) {
	if !validID(id) {
		return nil, os.ErrNotExist
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	b, err := os.ReadFile(s.path(id))
	if err != nil {
		return nil, err
	}
	var sess Session
	if err := json.Unmarshal(b, &sess); err != nil {
		return nil, err
	}
	return &sess, nil
}

func (s *SessionStore) Save(sess *Session) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	sess.Updated = time.Now()
	b, err := json.MarshalIndent(sess, "", "  ")
	if err != nil {
		return err
	}
	return writeFileAtomic(s.path(sess.ID), b)
}

// Update loads, changes and saves a session atomically.
func (s *SessionStore) Update(id string, fn func(*Session)) (*Session, error) {
	return s.update(id, fn, true)
}

// Edit is Update without moving the chat to the top of the list (renaming, moving it to a group).
func (s *SessionStore) Edit(id string, fn func(*Session)) (*Session, error) {
	return s.update(id, fn, false)
}

func (s *SessionStore) update(id string, fn func(*Session), touch bool) (*Session, error) {
	if !validID(id) {
		return nil, os.ErrNotExist
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	b, err := os.ReadFile(s.path(id))
	if err != nil {
		return nil, err
	}
	var sess Session
	if err := json.Unmarshal(b, &sess); err != nil {
		return nil, err
	}
	fn(&sess)
	if touch {
		sess.Updated = time.Now()
	}
	out, _ := json.MarshalIndent(&sess, "", "  ")
	if err := writeFileAtomic(s.path(id), out); err != nil {
		return nil, err
	}
	return &sess, nil
}

func (s *SessionStore) New() *Session {
	now := time.Now()
	return &Session{ID: randomID(6), Title: "New chat", Created: now, Updated: now, Messages: []SessionMessage{}}
}

func (s *SessionStore) Delete(id string) error {
	if !validID(id) {
		return os.ErrNotExist
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	_ = os.RemoveAll(filepath.Join(s.dir, "files", id))
	return os.Remove(s.path(id))
}

// SaveFile keeps a file with a chat and describes it.
func (s *SessionStore) SaveFile(sessionID, name, mime string, data []byte) (SessionFile, error) {
	if !validID(sessionID) {
		return SessionFile{}, os.ErrNotExist
	}
	dir := filepath.Join(s.dir, "files", sessionID)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return SessionFile{}, err
	}
	f := SessionFile{ID: randomID(8), Name: cleanFileName(name), MIME: mime, Bytes: len(data)}
	f.Width, f.Height = imageSize(data)
	if err := writeFileAtomic(filepath.Join(dir, f.ID), data); err != nil {
		return SessionFile{}, err
	}
	return f, nil
}

// FilePath is where a chat's file lives, or "" for a bad id.
func (s *SessionStore) FilePath(sessionID, fileID string) string {
	if !validID(sessionID) || !validID(fileID) {
		return ""
	}
	return filepath.Join(s.dir, "files", sessionID, fileID)
}

func cleanFileName(name string) string {
	name = filepath.Base(strings.ReplaceAll(strings.TrimSpace(name), "\\", "/"))
	name = strings.Map(func(r rune) rune {
		if r < 32 || r == '"' || r == '/' || r == ':' {
			return '_'
		}
		return r
	}, name)
	if name == "" || name == "." || name == ".." {
		name = "file"
	}
	if r := []rune(name); len(r) > 100 {
		name = string(r[:100])
	}
	return name
}

func summaryOf(sess *Session) SessionSummary {
	sum := SessionSummary{ID: sess.ID, Title: sess.Title, Created: sess.Created, Updated: sess.Updated,
		Count: len(sess.Messages), Group: sess.Group, Folder: sess.Folder}
	for i := len(sess.Messages) - 1; i >= 0; i-- {
		if m := sess.Messages[i]; m.Role == "assistant" {
			sum.Model = m.Model
			if i == len(sess.Messages)-1 && m.Status == "pending" {
				sum.Pending = true
			}
			break
		}
	}
	return sum
}

// isChatFile says whether a name in the folder is a chat (not groups.json).
func isChatFile(name string) bool {
	return strings.HasSuffix(name, ".json") && validID(strings.TrimSuffix(name, ".json"))
}

func (s *SessionStore) List() []SessionSummary {
	s.mu.Lock()
	defer s.mu.Unlock()
	entries, _ := os.ReadDir(s.dir)
	out := []SessionSummary{}
	seen := map[string]bool{}
	for _, e := range entries {
		if e.IsDir() || !isChatFile(e.Name()) {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		name := e.Name()
		seen[name] = true
		if c, ok := s.cache[name]; ok && c.mod.Equal(info.ModTime()) && c.size == info.Size() {
			out = append(out, c.sum)
			continue
		}
		b, err := os.ReadFile(filepath.Join(s.dir, name))
		if err != nil {
			continue
		}
		var sess Session
		if json.Unmarshal(b, &sess) != nil {
			continue
		}
		sum := summaryOf(&sess)
		s.cache[name] = cachedSummary{mod: info.ModTime(), size: info.Size(), sum: sum}
		out = append(out, sum)
	}
	for name := range s.cache {
		if !seen[name] {
			delete(s.cache, name)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Updated.After(out[j].Updated) })
	return out
}

// Search finds the chats whose title or messages hold q (any case), newest first.
func (s *SessionStore) Search(q string) []SessionSummary {
	q = strings.ToLower(strings.TrimSpace(q))
	out := []SessionSummary{}
	if q == "" {
		return out
	}
	s.mu.Lock()
	entries, _ := os.ReadDir(s.dir)
	s.mu.Unlock()
	for _, e := range entries {
		if e.IsDir() || !isChatFile(e.Name()) {
			continue
		}
		sess, err := s.Get(strings.TrimSuffix(e.Name(), ".json"))
		if err != nil {
			continue
		}
		snippet, hit := "", strings.Contains(strings.ToLower(sess.Title), q)
		for _, m := range sess.Messages {
			if snippet != "" {
				break
			}
			low := strings.ToLower(m.Content)
			if i := strings.Index(low, q); i >= 0 {
				hit, snippet = true, snippetAround(m.Content, i, len(q))
			}
		}
		if hit {
			sum := summaryOf(sess)
			sum.Snippet = snippet
			out = append(out, sum)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Updated.After(out[j].Updated) })
	return out
}

// snippetAround is a short piece of text around a match at byte i (of n bytes).
func snippetAround(text string, i, n int) string {
	from, to := i-50, i+n+70
	if from < 0 {
		from = 0
	}
	if to > len(text) {
		to = len(text)
	}
	for from > 0 && !utf8RuneStart(text[from]) {
		from--
	}
	for to < len(text) && !utf8RuneStart(text[to]) {
		to++
	}
	out := strings.Join(strings.Fields(text[from:to]), " ")
	if from > 0 {
		out = "…" + out
	}
	if to < len(text) {
		out += "…"
	}
	return out
}

func utf8RuneStart(b byte) bool { return b&0xC0 != 0x80 }

// cleanChatFolder checks a folder for a chat's pages: an existing folder, given by its full path.
func cleanChatFolder(p string) (string, error) {
	p = strings.TrimSpace(p)
	if p == "" {
		return "", errors.New("no folder")
	}
	if strings.HasPrefix(p, "~/") {
		if h, err := os.UserHomeDir(); err == nil {
			p = filepath.Join(h, p[2:])
		}
	}
	if !filepath.IsAbs(p) {
		return "", errors.New("give the folder's full path")
	}
	p = filepath.Clean(p)
	st, err := os.Stat(p)
	if err != nil || !st.IsDir() {
		return "", errors.New("there's no folder at " + p)
	}
	return p, nil
}

// ---------- groups (sessions/groups.json) ----------

func (s *SessionStore) groupsPath() string { return filepath.Join(s.dir, "groups.json") }

func (s *SessionStore) groupsLocked() []ChatGroup {
	var gs []ChatGroup
	if b, err := os.ReadFile(s.groupsPath()); err == nil {
		_ = json.Unmarshal(b, &gs)
	}
	if gs == nil {
		gs = []ChatGroup{}
	}
	return gs
}

func (s *SessionStore) saveGroupsLocked(gs []ChatGroup) error {
	b, _ := json.MarshalIndent(gs, "", "  ")
	return writeFileAtomic(s.groupsPath(), b)
}

func (s *SessionStore) Groups() []ChatGroup {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.groupsLocked()
}

func (s *SessionStore) HasGroup(id string) bool {
	for _, g := range s.Groups() {
		if g.ID == id {
			return true
		}
	}
	return false
}

func cleanGroupName(name string) string {
	name = strings.Join(strings.Fields(name), " ")
	if r := []rune(name); len(r) > 60 {
		name = string(r[:60])
	}
	return name
}

func (s *SessionStore) AddGroup(name string) (ChatGroup, error) {
	name = cleanGroupName(name)
	if name == "" {
		return ChatGroup{}, errors.New("give the group a name")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	gs := s.groupsLocked()
	g := ChatGroup{ID: randomID(5), Name: name}
	gs = append(gs, g)
	return g, s.saveGroupsLocked(gs)
}

// UpdateGroup renames, folds or moves a group (to position at, when it's 0 or more).
func (s *SessionStore) UpdateGroup(id string, name *string, collapsed *bool, at *int) (ChatGroup, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	gs := s.groupsLocked()
	for i := range gs {
		if gs[i].ID != id {
			continue
		}
		if name != nil {
			n := cleanGroupName(*name)
			if n == "" {
				return ChatGroup{}, errors.New("give the group a name")
			}
			gs[i].Name = n
		}
		if collapsed != nil {
			gs[i].Collapsed = *collapsed
		}
		g := gs[i]
		if at != nil && *at >= 0 {
			gs = append(gs[:i], gs[i+1:]...)
			k := *at
			if k > len(gs) {
				k = len(gs)
			}
			gs = append(gs[:k], append([]ChatGroup{g}, gs[k:]...)...)
		}
		return g, s.saveGroupsLocked(gs)
	}
	return ChatGroup{}, os.ErrNotExist
}

// DeleteGroup removes a group; its chats stay, out of any group.
func (s *SessionStore) DeleteGroup(id string) error {
	s.mu.Lock()
	gs := s.groupsLocked()
	kept := gs[:0]
	found := false
	for _, g := range gs {
		if g.ID == id {
			found = true
			continue
		}
		kept = append(kept, g)
	}
	if !found {
		s.mu.Unlock()
		return os.ErrNotExist
	}
	err := s.saveGroupsLocked(kept)
	s.mu.Unlock()
	if err != nil {
		return err
	}
	for _, sum := range s.List() {
		if sum.Group == id {
			_, _ = s.Edit(sum.ID, func(x *Session) { x.Group = "" })
		}
	}
	return nil
}

func titleFrom(text string) string {
	t := strings.Join(strings.Fields(text), " ")
	if r := []rune(t); len(r) > 48 {
		t = string(r[:48]) + "…"
	}
	if t == "" {
		t = "New chat"
	}
	return t
}

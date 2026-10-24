package main

// Chats live on your own computer, in the data folder. The hub and the
// devices that run your steps never keep them.

import (
	"encoding/json"
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
}

type Session struct {
	ID       string           `json:"id"`
	Title    string           `json:"title"`
	Created  time.Time        `json:"created"`
	Updated  time.Time        `json:"updated"`
	Messages []SessionMessage `json:"messages"`
}

type SessionSummary struct {
	ID      string    `json:"id"`
	Title   string    `json:"title"`
	Updated time.Time `json:"updated"`
	Count   int       `json:"count"`
}

type SessionStore struct {
	dir string
	mu  sync.Mutex
}

func NewSessionStore(dataDir string) *SessionStore {
	d := filepath.Join(dataDir, "sessions")
	_ = os.MkdirAll(d, 0o755)
	return &SessionStore{dir: d}
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
	sess.Updated = time.Now()
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
	return os.Remove(s.path(id))
}

func (s *SessionStore) List() []SessionSummary {
	s.mu.Lock()
	defer s.mu.Unlock()
	entries, _ := os.ReadDir(s.dir)
	var out []SessionSummary
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		b, err := os.ReadFile(filepath.Join(s.dir, e.Name()))
		if err != nil {
			continue
		}
		var sess Session
		if json.Unmarshal(b, &sess) != nil {
			continue
		}
		out = append(out, SessionSummary{ID: sess.ID, Title: sess.Title, Updated: sess.Updated, Count: len(sess.Messages)})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Updated.After(out[j].Updated) })
	return out
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

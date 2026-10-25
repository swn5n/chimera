package main

// Generations: one reply being written for one of your chats. A generation
// keeps going even if you close the window, and saves into the chat when done.

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"
)

type genEvent struct {
	Type         string  `json:"type"` // started, note, queued, assigned, delta, replay, requeued, done, error, cancelled
	GenID        string  `json:"gen_id,omitempty"`
	SessionID    string  `json:"session_id,omitempty"`
	Content      string  `json:"content,omitempty"`
	Thinking     string  `json:"thinking,omitempty"`
	Device       string  `json:"device,omitempty"`
	DeviceName   string  `json:"device_name,omitempty"`
	Owner        string  `json:"owner,omitempty"`
	Model        string  `json:"model,omitempty"`
	Reason       string  `json:"reason,omitempty"`
	Error        string  `json:"error,omitempty"`
	Tokens       int     `json:"tokens,omitempty"`
	PromptTokens int     `json:"prompt_tokens,omitempty"`
	TokPerSec    float64 `json:"tok_s,omitempty"`
	Credits      float64 `json:"credits,omitempty"`
	Free         bool    `json:"free,omitempty"`
	Local        bool    `json:"local,omitempty"`
	// Plugin replies: which plugin, how far along it is, and the files it made.
	Plugin   string       `json:"plugin,omitempty"`
	Fraction float64      `json:"fraction,omitempty"`
	File     *SessionFile `json:"file,omitempty"`

	raw *StepFile // a file as it came from the hub, before it's saved with the chat
}

type generation struct {
	id, sessionID string

	mu        sync.Mutex
	content   strings.Builder
	thinking  strings.Builder
	meta      genEvent // last "assigned"
	note      string
	status    string // running, done, error, cancelled
	final     *genEvent
	subs      map[chan genEvent]struct{}
	stepID    string
	cancelFn  func()
	cancelled bool

	plugin     string // the plugin making this reply, if any
	pluginName string
	statusMsg  string // what the plugin is doing now
	fraction   float64
	files      []SessionFile // what it made
}

type GenManager struct {
	app  *App
	mu   sync.Mutex
	gens map[string]*generation
}

func NewGenManager(app *App) *GenManager {
	return &GenManager{app: app, gens: map[string]*generation{}}
}

func (g *GenManager) Get(id string) *generation {
	g.mu.Lock()
	defer g.mu.Unlock()
	return g.gens[id]
}

type chatReq struct {
	SessionID string      `json:"session_id"`
	Message   string      `json:"message"`
	Model     string      `json:"model"`
	Target    string      `json:"target"`
	Private   bool        `json:"private"`
	Images    []chatImage `json:"images,omitempty"` // a picture for a plugin to work on
}

type chatImage struct {
	Name string `json:"name"`
	Data string `json:"data"` // base64
}

const chatImageMax = 25 << 20

// decodeChatImage checks a picture sent with a message.
func decodeChatImage(img chatImage) ([]byte, string, error) {
	data, err := base64.StdEncoding.DecodeString(img.Data)
	if err != nil {
		return nil, "", errors.New("that picture didn't arrive in one piece")
	}
	if len(data) > chatImageMax {
		return nil, "", fmt.Errorf("pictures can be up to %d MB", chatImageMax>>20)
	}
	mime := http.DetectContentType(data)
	switch mime {
	case "image/png", "image/jpeg", "image/webp":
	default:
		return nil, "", errors.New("send a PNG, JPEG or WebP picture")
	}
	return data, mime, nil
}

// Start adds the message to the chat and begins writing a reply.
func (g *GenManager) Start(req chatReq) (*generation, error) {
	text := strings.TrimSpace(req.Message)
	if text == "" && len(req.Images) == 0 {
		return nil, errors.New("type a message first")
	}
	if len(req.Images) > 1 {
		return nil, errors.New("send one picture at a time for now")
	}
	var imgData []byte
	var imgMIME string
	if len(req.Images) == 1 {
		var err error
		if imgData, imgMIME, err = decodeChatImage(req.Images[0]); err != nil {
			return nil, err
		}
	}
	store := g.app.sessions
	var sess *Session
	if req.SessionID != "" {
		if s, err := store.Get(req.SessionID); err == nil {
			sess = s
		}
	}
	if sess == nil {
		sess = store.New()
	}
	for _, m := range sess.Messages {
		if m.Status == "pending" && (g.Get(m.GenID) != nil || g.app.tasks.Get(m.TaskID) != nil) {
			return nil, errors.New("a reply is still being written in this chat")
		}
	}
	gen := &generation{id: randomID(6), sessionID: sess.ID, status: "running", subs: map[chan genEvent]struct{}{}}
	if len(sess.Messages) == 0 || sess.Title == "New chat" {
		sess.Title = titleFrom(text)
		if text == "" && len(req.Images) == 1 {
			sess.Title = titleFrom(req.Images[0].Name)
		}
	}
	now := time.Now()
	history := buildHistory(sess.Messages)
	history = append(history, ChatMessage{Role: "user", Content: text})
	user := SessionMessage{Role: "user", Content: text, At: now}
	var img *SessionFile
	if imgData != nil {
		f, err := store.SaveFile(sess.ID, req.Images[0].Name, imgMIME, imgData)
		if err != nil {
			return nil, err
		}
		user.Files = []SessionFile{f}
		img = &f
	}
	sess.Messages = append(sess.Messages,
		user,
		SessionMessage{Role: "assistant", At: now, Status: "pending", GenID: gen.id, Model: req.Model},
	)
	if err := store.Save(sess); err != nil {
		return nil, err
	}
	g.mu.Lock()
	g.gens[gen.id] = gen
	g.mu.Unlock()
	switch {
	case img != nil:
		go g.runPlugin(gen, req, text, img, imgData, nil)
	case req.Model == "": // "Best available": a Head may be the best available
		go g.runWordsOrHead(gen, req, text, history)
	default:
		go g.run(gen, req, history)
	}
	return gen, nil
}

func buildHistory(msgs []SessionMessage) []ChatMessage {
	var out []ChatMessage
	for _, m := range msgs {
		if m.Role == "assistant" && (m.Status == "pending" || m.Status == "error" || m.Content == "") {
			continue
		}
		out = append(out, ChatMessage{Role: m.Role, Content: m.Content})
	}
	if len(out) > 40 {
		out = out[len(out)-40:]
	}
	return out
}

func (gen *generation) emit(ev genEvent) {
	gen.mu.Lock()
	defer gen.mu.Unlock()
	ev.GenID = gen.id
	switch ev.Type {
	case "assigned":
		gen.meta = ev
	case "note":
		gen.note = ev.Reason
	case "delta":
		gen.content.WriteString(ev.Content)
		gen.thinking.WriteString(ev.Thinking)
	case "replay":
		gen.content.Reset()
		gen.thinking.Reset()
		gen.content.WriteString(ev.Content)
		gen.thinking.WriteString(ev.Thinking)
	case "requeued":
		gen.content.Reset()
		gen.thinking.Reset()
		gen.meta = genEvent{}
		gen.statusMsg, gen.fraction = "", 0
	case "plugin":
		gen.plugin, gen.pluginName = ev.Plugin, ev.Model
	case "status":
		gen.statusMsg, gen.fraction = ev.Reason, ev.Fraction
	case "file":
		if ev.File != nil {
			gen.files = append(gen.files, *ev.File)
		}
	case "done", "error", "cancelled":
		e := ev
		gen.final = &e
		gen.status = ev.Type
	}
	for ch := range gen.subs {
		select {
		case ch <- ev:
		default:
			close(ch)
			delete(gen.subs, ch)
		}
	}
	if gen.final != nil {
		for ch := range gen.subs {
			close(ch)
		}
		gen.subs = map[chan genEvent]struct{}{}
	}
}

// Subscribe returns past events (so a reopened window catches up) and a
// channel of new ones. The channel is nil if the reply is already finished.
func (gen *generation) Subscribe() ([]genEvent, chan genEvent) {
	gen.mu.Lock()
	defer gen.mu.Unlock()
	replay := []genEvent{{Type: "started", GenID: gen.id, SessionID: gen.sessionID}}
	if gen.plugin != "" {
		replay = append(replay, genEvent{Type: "plugin", GenID: gen.id, Plugin: gen.plugin, Model: gen.pluginName})
	}
	if gen.note != "" {
		replay = append(replay, genEvent{Type: "note", GenID: gen.id, Reason: gen.note})
	}
	if gen.meta.Type != "" {
		replay = append(replay, gen.meta)
	}
	if gen.statusMsg != "" && gen.final == nil {
		replay = append(replay, genEvent{Type: "status", GenID: gen.id, Reason: gen.statusMsg, Fraction: gen.fraction})
	}
	for i := range gen.files {
		replay = append(replay, genEvent{Type: "file", GenID: gen.id, File: &gen.files[i]})
	}
	if gen.content.Len() > 0 || gen.thinking.Len() > 0 {
		replay = append(replay, genEvent{Type: "delta", GenID: gen.id, Content: gen.content.String(), Thinking: gen.thinking.String()})
	}
	if gen.final != nil {
		return append(replay, *gen.final), nil
	}
	ch := make(chan genEvent, 4096)
	gen.subs[ch] = struct{}{}
	return replay, ch
}

func (gen *generation) Unsubscribe(ch chan genEvent) {
	gen.mu.Lock()
	defer gen.mu.Unlock()
	delete(gen.subs, ch)
}

func (gen *generation) Snapshot() (content, thinking string, meta genEvent) {
	gen.mu.Lock()
	defer gen.mu.Unlock()
	return gen.content.String(), gen.thinking.String(), gen.meta
}

func (g *GenManager) Cancel(id string) error {
	gen := g.Get(id)
	if gen == nil {
		return errors.New("that reply already finished")
	}
	gen.mu.Lock()
	gen.cancelled = true
	fn := gen.cancelFn
	stepID := gen.stepID
	gen.mu.Unlock()
	if stepID != "" {
		if c, err := g.app.node.client(); err == nil {
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			if err := c.Cancel(ctx, stepID); err == nil {
				return nil
			}
		}
	}
	if fn != nil {
		fn()
	}
	return nil
}

func (g *GenManager) run(gen *generation, req chatReq, history []ChatMessage) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	gen.mu.Lock()
	gen.cancelFn = cancel
	gen.mu.Unlock()
	sreq := submitReq{Model: req.Model, Target: req.Target, Private: req.Private, Messages: history,
		NeedCtx: historyTokens(history) + 2048}
	final := g.app.runPrompt(ctx, sreq, gen.emit, func(id string) {
		gen.mu.Lock()
		gen.stepID = id
		gen.mu.Unlock()
	})
	gen.emit(final)
	g.saveResult(gen)
	time.AfterFunc(2*time.Minute, func() {
		g.mu.Lock()
		delete(g.gens, gen.id)
		g.mu.Unlock()
	})
}

func (g *GenManager) saveResult(gen *generation) {
	gen.mu.Lock()
	content, thinking, meta, note := gen.content.String(), gen.thinking.String(), gen.meta, gen.note
	files, plugin, stepID := append([]SessionFile(nil), gen.files...), gen.plugin, gen.stepID
	final := genEvent{Type: "error", Error: "stopped"}
	if gen.final != nil {
		final = *gen.final
	}
	gen.mu.Unlock()
	_, err := g.app.sessions.Update(gen.sessionID, func(s *Session) {
		for i := range s.Messages {
			m := &s.Messages[i]
			if m.GenID != gen.id {
				continue
			}
			m.Content = content
			m.Thinking = thinking
			m.Files, m.Plugin = files, plugin
			if plugin != "" {
				m.StepID = stepID
			}
			if meta.Model != "" {
				m.Model = meta.Model
			}
			m.Device, m.Owner, m.Local, m.Note = meta.DeviceName, meta.Owner, meta.Local, note
			m.Tokens, m.TokPerSec, m.Credits, m.Free = final.Tokens, final.TokPerSec, final.Credits, final.Free
			m.At = time.Now()
			switch final.Type {
			case "done":
				m.Status = ""
			case "cancelled":
				m.Status = "cancelled"
			default:
				m.Status, m.Error = "error", final.Error
			}
			m.GenID = ""
		}
	})
	if err != nil {
		log.Printf("saving chat %s: %v", gen.sessionID, err)
	}
	g.app.notify()
}

// runWordsOrHead answers a message made of words: with a Head when one is the
// right tool for it (see headForText), otherwise with a model as usual.
func (g *GenManager) runWordsOrHead(gen *generation, req chatReq, text string, history []ChatMessage) {
	ctx, cancel := context.WithCancel(context.Background())
	gen.mu.Lock()
	gen.cancelFn = cancel
	gen.mu.Unlock()
	choice := g.app.headForText(ctx, text)
	cancel()
	if choice == nil {
		g.run(gen, req, history)
		return
	}
	g.runPlugin(gen, req, text, nil, nil, choice)
}

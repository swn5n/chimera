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
	"os"
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
	DoneReason   string  `json:"done_reason,omitempty"` // "length": the model stopped at its output limit
	ThinkSecs    float64 `json:"think_s,omitempty"`     // how long it thought before answering
	ThinkAt      string  `json:"think_at,omitempty"`    // when it started thinking (on a replay, for a window that opens the chat later)
	WaitSecs     float64 `json:"wait_s,omitempty"`      // how long until its first word (reading the prompt)
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
	thinkAt    time.Time     // its first thinking
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
	// Files for an engine, uploaded first (POST /api/uploads): they're copied into the
	// chat's folder and the model is told what each one is (attach.go).
	Attachments []chatAttachment `json:"attachments,omitempty"`
	// For those files, both on unless set false: turntables of the 3D models, and a
	// line on what each picture shows (attach_prep.go).
	Turntables *bool  `json:"turntables,omitempty"`
	Describe   *bool  `json:"describe,omitempty"`
	WebGLB     *bool  `json:"web_glb,omitempty"`  // and a GLB of each OBJ, FBX, STL or PLY for web pages
	Thinking   string `json:"thinking,omitempty"` // an engine's thinking level (off, low, medium, high, max)
	// Regenerate writes the chat's last reply again (Message is ignored); EditAt
	// replaces the message at that index, and everything after it, with Message.
	Regenerate bool `json:"regenerate,omitempty"`
	EditAt     *int `json:"edit_at,omitempty"`
	// For a new chat: the group it goes in, and the folder its pages load files from.
	Group  string `json:"group,omitempty"`
	Folder string `json:"folder,omitempty"`
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
	engine, isEngine := engineID(req.Model)
	if req.Regenerate {
		req.Images, req.Attachments, text = nil, nil, ""
	} else if text == "" && len(req.Images) == 0 && len(req.Attachments) == 0 {
		return nil, errors.New("type a message first")
	}
	if len(req.Attachments) > 0 {
		switch {
		case !isEngine:
			return nil, errors.New("files go to this computer's own models (like DeepSeek): pick one in Model. Other models take one picture, for a Head")
		case len(req.Images) > 0:
			return nil, errors.New("send the picture as one of the files")
		case len(req.Attachments) > attachCountMax:
			return nil, fmt.Errorf("attach up to %s files at once", fmtNum(attachCountMax))
		case req.EditAt != nil:
			return nil, errors.New("a changed message keeps its files: send new ones with a new message")
		}
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
		if req.Regenerate || req.EditAt != nil {
			return nil, errors.New("can't find that chat")
		}
		sess = store.New()
		if req.Group != "" && store.HasGroup(req.Group) {
			sess.Group = req.Group
		}
		if f, err := cleanChatFolder(req.Folder); err == nil {
			sess.Folder = f
		}
	}
	for _, m := range sess.Messages {
		if m.Status == "pending" && (g.Get(m.GenID) != nil || g.app.tasks.Get(m.TaskID) != nil) {
			return nil, errors.New("a reply is still being written in this chat")
		}
	}
	userAt := time.Now()
	var kept SessionMessage // the message answered again, or changed: it keeps its files
	switch {
	case req.Regenerate:
		// Write the last reply again: drop it, then answer the message before it once more.
		if i := len(sess.Messages) - 1; i >= 0 && sess.Messages[i].Role == "assistant" {
			last := sess.Messages[i]
			if last.Task != nil || last.TaskID != "" {
				return nil, errors.New("a long task's result can't be written again from here: start the task again")
			}
			if last.Plugin != "" {
				return nil, errors.New("a Head made that reply: send your request again to run it again")
			}
			sess.Messages = sess.Messages[:i]
		}
		j := len(sess.Messages) - 1
		if j < 0 || sess.Messages[j].Role != "user" {
			return nil, errors.New("there's no message to answer again")
		}
		if len(sess.Messages[j].Files) > 0 {
			return nil, errors.New("that message has a picture: send it again for a Head to work on")
		}
		text, userAt, kept = sess.Messages[j].Content, sess.Messages[j].At, sess.Messages[j]
		sess.Messages = sess.Messages[:j]
	case req.EditAt != nil:
		k := *req.EditAt
		if k < 0 || k >= len(sess.Messages) || sess.Messages[k].Role != "user" {
			return nil, errors.New("can't find that message to change")
		}
		kept = sess.Messages[k]
		sess.Messages = sess.Messages[:k]
	}
	gen := &generation{id: randomID(6), sessionID: sess.ID, status: "running", subs: map[chan genEvent]struct{}{}}
	if !sess.Named && (len(sess.Messages) == 0 || sess.Title == "New chat") {
		sess.Title = titleFrom(text)
		if text == "" && len(req.Images) == 1 {
			sess.Title = titleFrom(req.Images[0].Name)
		}
		if text == "" && len(req.Attachments) > 0 {
			sess.Title = titleFrom(strings.Split(strings.Trim(strings.ReplaceAll(req.Attachments[0].Path, "\\", "/"), "/"), "/")[0])
		}
	}
	now := time.Now()
	user := SessionMessage{Role: "user", Content: text, At: userAt,
		Attached: kept.Attached, AttachedIn: kept.AttachedIn, FilesNote: kept.FilesNote}
	if len(req.Attachments) > 0 {
		if err := g.attach(sess, &user, req.Attachments, engine); err != nil {
			return nil, err
		}
	}
	history := buildHistory(sess.Messages)
	history = append(history, ChatMessage{Role: "user", Content: withFilesNote(text, user.FilesNote)})
	var img *SessionFile
	if imgData != nil {
		f, err := store.SaveFile(sess.ID, req.Images[0].Name, imgMIME, imgData)
		if err != nil {
			return nil, err
		}
		user.Files = []SessionFile{f}
		img = &f
	}
	reply := SessionMessage{Role: "assistant", At: now, Status: "pending", GenID: gen.id, Model: req.Model}
	if isEngine && img == nil {
		reply.Model, reply.ThinkLevel = g.app.engines.Name(engine), req.Thinking
	}
	sess.Messages = append(sess.Messages, user, reply)
	if err := store.Save(sess); err != nil {
		return nil, err
	}
	g.mu.Lock()
	g.gens[gen.id] = gen
	g.mu.Unlock()
	var prep *attachPrep
	if p := (attachPrep{text: text, turntables: req.Turntables == nil || *req.Turntables, describe: req.Describe == nil || *req.Describe,
		webGLB: req.WebGLB == nil || *req.WebGLB}); len(req.Attachments) > 0 && wantsPrep(user.Attached, p) {
		prep = &p
	}
	switch {
	case img != nil:
		go g.runPlugin(gen, req, text, img, imgData, nil)
	case isEngine: // a model of this computer's own, outside Ollama: never through the network
		go g.runEngine(gen, req, engine, history, prep)
	case req.Model == "": // "Best available": a Head may be the best available
		go g.runWordsOrHead(gen, req, text, history)
	default:
		go g.run(gen, req, history)
	}
	return gen, nil
}

// runEngine writes a reply with one of this computer's engines (engines.go).
// These replies can take hours, so what's written so far is kept in the chat as
// it goes: if Chimera stops halfway, the chat still has it. A message's files may
// first get turntables and descriptions (prep, attach_prep.go).
func (g *GenManager) runEngine(gen *generation, req chatReq, engine string, history []ChatMessage, prep *attachPrep) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	gen.mu.Lock()
	gen.cancelFn = cancel
	gen.mu.Unlock()
	if prep != nil {
		if note := g.prepAttachments(ctx, gen, engine, *prep); note != "" && len(history) > 0 {
			history[len(history)-1].Content = withFilesNote(prep.text, note)
		}
		if ctx.Err() != nil {
			gen.emit(genEvent{Type: "cancelled", Local: true})
			g.saveResult(gen)
			g.forgetLater(gen)
			return
		}
	}
	stop := make(chan struct{})
	go func() {
		t := time.NewTicker(30 * time.Second)
		defer t.Stop()
		saved := -1
		for {
			select {
			case <-stop:
				return
			case <-t.C:
				saved = g.savePartial(gen, saved)
			}
		}
	}()
	final := g.app.engines.Run(ctx, engine, history, req.Thinking, gen.emit)
	close(stop)
	gen.emit(final)
	g.saveResult(gen)
	g.forgetLater(gen)
}

// forgetLater drops a finished reply from the ones a window can still follow.
func (g *GenManager) forgetLater(gen *generation) {
	time.AfterFunc(2*time.Minute, func() {
		g.mu.Lock()
		delete(g.gens, gen.id)
		g.mu.Unlock()
	})
}

// savePartial keeps what a reply has written so far in its chat (it stays pending).
// It returns the length saved, and does nothing if that hasn't changed.
func (g *GenManager) savePartial(gen *generation, saved int) int {
	content, thinking, _ := gen.Snapshot()
	n := len(content) + len(thinking)
	if n == saved {
		return saved
	}
	_, err := g.app.sessions.Update(gen.sessionID, func(s *Session) {
		for i := range s.Messages {
			if m := &s.Messages[i]; m.GenID == gen.id && m.Status == "pending" {
				m.Content, m.Thinking = content, thinking
			}
		}
	})
	if err != nil {
		return saved
	}
	return n
}

// usingLocal says whether one of this computer's chats is writing with this Ollama model now.
func (g *GenManager) usingLocal(model string) bool {
	g.mu.Lock()
	gens := make([]*generation, 0, len(g.gens))
	for _, gen := range g.gens {
		gens = append(gens, gen)
	}
	g.mu.Unlock()
	for _, gen := range gens {
		gen.mu.Lock()
		busy := gen.status == "running" && gen.meta.Local && normModel(gen.meta.Model) == normModel(model)
		gen.mu.Unlock()
		if busy {
			return true
		}
	}
	return false
}

// attach copies a message's files into its chat's folder (making one when the
// chat has none) and writes what the model is told about them.
func (g *GenManager) attach(sess *Session, user *SessionMessage, atts []chatAttachment, engine string) error {
	if sess.Folder == "" {
		f, err := newChatFolder(sess.Title)
		if err != nil {
			return fmt.Errorf("couldn't make a folder for this chat's files: %v", err)
		}
		sess.Folder = f
	} else if err := os.MkdirAll(sess.Folder, 0o755); err != nil {
		return fmt.Errorf("couldn't open the chat's folder: %v", err)
	}
	files, err := placeAttachments(g.app.uploadDir(), sess.Folder, atts)
	if err != nil {
		return err
	}
	user.Attached, user.FilesNote = describeAttachments(sess.Folder, files, g.app.engines.TextBudget(engine))
	user.AttachedIn = sess.Folder
	return nil
}

func buildHistory(msgs []SessionMessage) []ChatMessage {
	var out []ChatMessage
	for _, m := range msgs {
		if m.Role == "assistant" && (m.Status == "pending" || m.Status == "error" || m.Content == "") {
			continue
		}
		content := m.Content
		if m.Role == "user" {
			content = withFilesNote(content, m.FilesNote)
		}
		out = append(out, ChatMessage{Role: m.Role, Content: content})
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
		if ev.Thinking != "" && gen.thinkAt.IsZero() {
			gen.thinkAt = time.Now()
		}
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
		d := genEvent{Type: "delta", GenID: gen.id, Content: gen.content.String(), Thinking: gen.thinking.String()}
		if !gen.thinkAt.IsZero() {
			d.ThinkAt = gen.thinkAt.Format(time.RFC3339Nano)
		}
		replay = append(replay, d)
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
			m.ThinkSecs, m.WaitSecs, m.Cut = final.ThinkSecs, final.WaitSecs, final.DoneReason == "length"
			if final.PromptTokens > 0 {
				m.PromptTokens = final.PromptTokens
			}
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
	choice := g.app.headForText(ctx, text, req.pluginScope())
	cancel()
	if choice == nil {
		g.run(gen, req, history)
		return
	}
	g.runPlugin(gen, req, text, nil, nil, choice)
}

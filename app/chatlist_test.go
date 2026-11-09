package main

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func saveChat(t *testing.T, st *SessionStore, title string, msgs ...string) *Session {
	t.Helper()
	s := st.New()
	s.Title = title
	for i, m := range msgs {
		role := "user"
		if i%2 == 1 {
			role = "assistant"
		}
		s.Messages = append(s.Messages, SessionMessage{Role: role, Content: m, At: time.Now()})
	}
	if err := st.Save(s); err != nil {
		t.Fatal(err)
	}
	return s
}

func TestGroupsHoldChatsAndDeletingOneKeepsThem(t *testing.T) {
	st := NewSessionStore(t.TempDir())
	a, _ := st.AddGroup("  Raka   website ")
	b, _ := st.AddGroup("Blender")
	if a.Name != "Raka website" || !st.HasGroup(a.ID) {
		t.Fatalf("%+v", a)
	}
	if _, err := st.AddGroup("   "); err == nil {
		t.Fatal("a group with no name")
	}
	c := saveChat(t, st, "site", "make a site")
	if _, err := st.Edit(c.ID, func(s *Session) { s.Group = a.ID }); err != nil {
		t.Fatal(err)
	}
	name, folded, at := "Raka", true, 0
	if _, err := st.UpdateGroup(b.ID, nil, nil, &at); err != nil {
		t.Fatal(err)
	}
	if _, err := st.UpdateGroup(a.ID, &name, &folded, nil); err != nil {
		t.Fatal(err)
	}
	gs := st.Groups()
	if len(gs) != 2 || gs[0].ID != b.ID || gs[1].Name != "Raka" || !gs[1].Collapsed {
		t.Fatalf("%+v", gs)
	}
	if err := st.DeleteGroup(a.ID); err != nil {
		t.Fatal(err)
	}
	s, err := st.Get(c.ID)
	if err != nil || s.Group != "" {
		t.Fatalf("the chat should stay, out of the group: %+v %v", s, err)
	}
	if st.HasGroup(a.ID) {
		t.Fatal("the group is still there")
	}
}

func TestTheListSeesChangesAndRenamesDontReorderIt(t *testing.T) {
	st := NewSessionStore(t.TempDir())
	older := saveChat(t, st, "older", "q")
	time.Sleep(20 * time.Millisecond)
	newer := saveChat(t, st, "newer", "q")
	l := st.List()
	if len(l) != 2 || l[0].ID != newer.ID {
		t.Fatalf("%+v", l)
	}
	time.Sleep(20 * time.Millisecond)
	if _, err := st.Edit(older.ID, func(s *Session) { s.Title = "older, renamed" }); err != nil {
		t.Fatal(err)
	}
	l = st.List()
	if l[0].ID != newer.ID || l[1].Title != "older, renamed" {
		t.Fatalf("a rename moved the chat or wasn't seen: %+v", l)
	}
	if err := st.Delete(newer.ID); err != nil {
		t.Fatal(err)
	}
	if l = st.List(); len(l) != 1 {
		t.Fatalf("%+v", l)
	}
	// groups.json sits in the same folder: it's not a chat.
	st.AddGroup("g")
	if l = st.List(); len(l) != 1 {
		t.Fatalf("groups.json listed as a chat: %+v", l)
	}
}

func TestSearchFindsTitlesAndWhatWasSaid(t *testing.T) {
	st := NewSessionStore(t.TempDir())
	saveChat(t, st, "Lift quote", "How tall is the JLG 600S?", "It reaches about sixty feet of platform height.")
	saveChat(t, st, "Other", "nothing here")
	r := st.Search("SIXTY feet")
	if len(r) != 1 || r[0].Title != "Lift quote" || !strings.Contains(r[0].Snippet, "sixty feet") {
		t.Fatalf("%+v", r)
	}
	if r = st.Search("other"); len(r) != 1 || r[0].Snippet != "" {
		t.Fatalf("title match: %+v", r)
	}
	if r = st.Search("   "); len(r) != 0 {
		t.Fatal("an empty search finds nothing")
	}
}

// chatServer is the app's API for these tests, with a chat that has a folder.
func chatServer(t *testing.T) (*App, *httptest.Server, *Session, string) {
	t.Helper()
	a := NewApp(t.TempDir(), 0, 0, "http://127.0.0.1:1")
	folder := t.TempDir()
	os.MkdirAll(filepath.Join(folder, "assets"), 0o755)
	os.WriteFile(filepath.Join(folder, "assets", "logo.svg"), []byte("<svg/>"), 0o644)
	os.WriteFile(filepath.Join(folder, ".secret"), []byte("hidden"), 0o644)
	outside := filepath.Join(t.TempDir(), "outside.txt")
	os.WriteFile(outside, []byte("not yours"), 0o644)
	os.Symlink(outside, filepath.Join(folder, "assets", "link.txt"))
	sess := saveChat(t, a.sessions, "site", "make a site")
	sess.Folder = folder
	a.sessions.Save(sess)
	srv := httptest.NewServer(a.routes())
	t.Cleanup(srv.Close)
	return a, srv, sess, folder
}

func call(t *testing.T, srv *httptest.Server, method, path string, body any, chimera bool) (int, http.Header, []byte) {
	t.Helper()
	var rd io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		rd = bytes.NewReader(b)
	}
	req, _ := http.NewRequest(method, srv.URL+path, rd)
	if chimera {
		req.Header.Set("X-Chimera", "1")
	}
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	b, _ := io.ReadAll(res.Body)
	return res.StatusCode, res.Header, b
}

func TestAPreviewRunsSandboxedAndOnlySeesItsChatsFolder(t *testing.T) {
	_, srv, sess, _ := chatServer(t)
	page := `<!doctype html><html><body><img src="assets/logo.svg"></body></html>`
	if code, _, _ := call(t, srv, "POST", "/api/preview", map[string]string{"session_id": sess.ID, "html": page}, false); code != 403 {
		t.Fatalf("a preview without the X-Chimera header: %d", code)
	}
	code, _, b := call(t, srv, "POST", "/api/preview", map[string]string{"session_id": sess.ID, "html": page}, true)
	var r struct {
		URL    string `json:"url"`
		Folder bool   `json:"folder"`
	}
	json.Unmarshal(b, &r)
	if code != 200 || !strings.HasPrefix(r.URL, "/preview/") || !r.Folder {
		t.Fatalf("%d %s", code, b)
	}
	code, h, b := call(t, srv, "GET", r.URL, nil, false)
	csp := h.Get("Content-Security-Policy")
	if code != 200 || string(b) != page || !strings.HasPrefix(csp, "sandbox") || strings.Contains(csp, "allow-same-origin") || h.Get("Referrer-Policy") != "no-referrer" {
		t.Fatalf("page: %d %q %q", code, csp, b)
	}
	if code, h, b = call(t, srv, "GET", r.URL+"assets/logo.svg", nil, false); code != 200 || string(b) != "<svg/>" || h.Get("Access-Control-Allow-Origin") != "*" || !strings.HasPrefix(h.Get("Content-Security-Policy"), "sandbox") {
		t.Fatalf("asset: %d %q", code, b)
	}
	for _, p := range []string{".secret", "assets/link.txt", "assets/%2e%2e/.secret", "assets/..%2f..%2fx", "nope.png"} {
		if code, _, _ := call(t, srv, "GET", r.URL+p, nil, false); code != 404 {
			t.Errorf("%s: %d, want 404", p, code)
		}
	}
	if code, _, _ := call(t, srv, "GET", "/preview/0123456789abcdef0123456789abcdef/", nil, false); code != 404 {
		t.Errorf("an unknown preview: %d", code)
	}
}

func TestSavingAPageNeedsAFolderAndAsksBeforeReplacing(t *testing.T) {
	a, srv, sess, folder := chatServer(t)
	path := "/api/sessions/" + sess.ID + "/save-page"
	if code, _, b := call(t, srv, "POST", path, map[string]any{"html": "<p>one</p>"}, true); code != 200 || !strings.Contains(string(b), "index.html") {
		t.Fatalf("%d %s", code, b)
	}
	code, _, b := call(t, srv, "POST", path, map[string]any{"html": "<p>two</p>"}, true)
	if code != 409 || !strings.Contains(string(b), `"exists":true`) {
		t.Fatalf("replacing without asking: %d %s", code, b)
	}
	if got, _ := os.ReadFile(filepath.Join(folder, "index.html")); string(got) != "<p>one</p>" {
		t.Fatalf("%q", got)
	}
	call(t, srv, "POST", path, map[string]any{"html": "<p>two</p>", "overwrite": true}, true)
	if got, _ := os.ReadFile(filepath.Join(folder, "index.html")); string(got) != "<p>two</p>" {
		t.Fatalf("%q", got)
	}
	if code, _, _ := call(t, srv, "POST", path, map[string]any{"html": "x", "name": "../../evil"}, true); code != 200 {
		t.Fatalf("a name with a path: %d", code)
	}
	if fileExists(filepath.Join(filepath.Dir(filepath.Dir(folder)), "evil.html")) || !fileExists(filepath.Join(folder, "evil.html")) {
		t.Fatal("the page was saved outside the chat's folder")
	}
	other := saveChat(t, a.sessions, "no folder", "q")
	if code, _, _ := call(t, srv, "POST", "/api/sessions/"+other.ID+"/save-page", map[string]any{"html": "x"}, true); code != 409 {
		t.Fatalf("a chat with no folder: %d", code)
	}
}

func TestTheSidebarAPIRenamesMovesAndDeletes(t *testing.T) {
	a, srv, sess, _ := chatServer(t)
	code, _, b := call(t, srv, "POST", "/api/chat-groups", map[string]any{"name": "Raka", "move": []string{sess.ID}}, true)
	var g ChatGroup
	json.Unmarshal(b, &g)
	if code != 200 || g.ID == "" {
		t.Fatalf("%d %s", code, b)
	}
	if s, _ := a.sessions.Get(sess.ID); s.Group != g.ID {
		t.Fatal("the chat wasn't moved into the new group")
	}
	if code, _, _ := call(t, srv, "PATCH", "/api/sessions/"+sess.ID, map[string]any{"title": "  New   name "}, true); code != 200 {
		t.Fatal(code)
	}
	if s, _ := a.sessions.Get(sess.ID); s.Title != "New name" || !s.Named {
		t.Fatalf("%+v", s)
	}
	if code, _, _ := call(t, srv, "PATCH", "/api/sessions/"+sess.ID, map[string]any{"folder": "/no/such/folder"}, true); code != 400 {
		t.Fatalf("a missing folder: %d", code)
	}
	if code, _, _ := call(t, srv, "PATCH", "/api/sessions/"+sess.ID, map[string]any{"group": "nosuchgroup"}, true); code != 404 {
		t.Fatalf("a missing group: %d", code)
	}
	two := saveChat(t, a.sessions, "two", "q")
	code, _, b = call(t, srv, "POST", "/api/sessions/delete", map[string]any{"ids": []string{sess.ID, two.ID, "bad!id"}}, true)
	if code != 200 || !strings.Contains(string(b), `"deleted":2`) {
		t.Fatalf("%d %s", code, b)
	}
	if len(a.sessions.List()) != 0 {
		t.Fatal("chats left after deleting them")
	}
	if code, _, _ := call(t, srv, "DELETE", "/api/chat-groups/"+g.ID, nil, true); code != 200 {
		t.Fatal(code)
	}
}

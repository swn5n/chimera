package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
)

// HubClient is how a device talks to the network's hub.
type HubClient struct {
	base  string
	token string
	hc    *http.Client
}

type apiError struct {
	Status int
	Msg    string
}

func (e *apiError) Error() string { return e.Msg }

func hubBase(addr string) (string, error) {
	addr = strings.TrimSpace(addr)
	if addr == "" {
		return "", errors.New("enter the host's address")
	}
	if !strings.Contains(addr, "://") {
		addr = "http://" + addr
	}
	u, err := url.Parse(addr)
	if err != nil || u.Hostname() == "" {
		return "", errors.New("that address doesn't look right; it should be like 192.168.1.20:7480")
	}
	port := u.Port()
	if port == "" {
		port = fmt.Sprint(defaultHubPort)
		if u.Scheme == "https" { // e.g. a Tailscale Funnel address: public HTTPS in front of the hub
			port = "443"
		}
	}
	return u.Scheme + "://" + net.JoinHostPort(u.Hostname(), port), nil
}

func NewHubClient(addr, token string) (*HubClient, error) {
	base, err := hubBase(addr)
	if err != nil {
		return nil, err
	}
	return &HubClient{base: base, token: token, hc: &http.Client{Transport: sharedTransport}}, nil
}

func (c *HubClient) newReq(ctx context.Context, method, path string, in any) (*http.Request, error) {
	var body io.Reader
	if in != nil {
		b, err := json.Marshal(in)
		if err != nil {
			return nil, err
		}
		body = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.base+path, body)
	if err != nil {
		return nil, err
	}
	if in != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	return req, nil
}

// call sends a request and decodes the JSON reply. It returns (false, nil)
// for 204 No Content.
func (c *HubClient) call(ctx context.Context, method, path string, in, out any) (bool, error) {
	req, err := c.newReq(ctx, method, path, in)
	if err != nil {
		return false, err
	}
	resp, err := c.hc.Do(req)
	if err != nil {
		return false, err
	}
	defer resp.Body.Close()
	if resp.StatusCode == 204 {
		return false, nil
	}
	if resp.StatusCode >= 400 {
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 8192))
		var e struct {
			Error string `json:"error"`
		}
		msg := strings.TrimSpace(string(b))
		if json.Unmarshal(b, &e) == nil && e.Error != "" {
			msg = e.Error
		}
		if msg == "" {
			msg = resp.Status
		}
		return false, &apiError{Status: resp.StatusCode, Msg: msg}
	}
	if out != nil {
		if err := json.NewDecoder(resp.Body).Decode(out); err != nil {
			return false, err
		}
	} else {
		_, _ = io.Copy(io.Discard, resp.Body)
	}
	return true, nil
}

func (c *HubClient) Ping(ctx context.Context) (string, error) {
	var v struct {
		App   string `json:"app"`
		Name  string `json:"name"`
		Proto int    `json:"proto"`
	}
	if _, err := c.call(ctx, "GET", "/v1/ping", nil, &v); err != nil {
		return "", err
	}
	if v.App != "chimera-hub" {
		return "", errors.New("something answered at that address, but it isn't a Chimera hub")
	}
	return v.Name, nil
}

func (c *HubClient) Join(ctx context.Context, req joinReq) (joinResp, error) {
	var out joinResp
	_, err := c.call(ctx, "POST", "/v1/join", req, &out)
	return out, err
}

func (c *HubClient) Leave(ctx context.Context) error {
	_, err := c.call(ctx, "POST", "/v1/leave", map[string]any{}, nil)
	return err
}

func (c *HubClient) Heartbeat(ctx context.Context, hb heartbeatReq) (NetSnapshot, error) {
	var out NetSnapshot
	_, err := c.call(ctx, "POST", "/v1/heartbeat", hb, &out)
	return out, err
}

// Poll waits for work. It returns nil when there's nothing to do.
func (c *HubClient) Poll(ctx context.Context, wait int) (*Assignment, error) {
	var a Assignment
	got, err := c.call(ctx, "GET", fmt.Sprintf("/v1/work?wait=%d", wait), nil, &a)
	if err != nil || !got {
		return nil, err
	}
	return &a, nil
}

func (c *HubClient) Progress(ctx context.Context, id, content, thinking string) (bool, error) {
	var out struct {
		Cancel bool `json:"cancel"`
	}
	_, err := c.call(ctx, "POST", "/v1/steps/"+id+"/progress", progressReq{Content: content, Thinking: thinking}, &out)
	return out.Cancel, err
}

func (c *HubClient) Complete(ctx context.Context, id string, stats ChatStats) error {
	_, err := c.call(ctx, "POST", "/v1/steps/"+id+"/complete", completeReq{Stats: stats}, nil)
	return err
}

// Status reports what a plugin step is doing; the answer says whether the
// requester wants it stopped.
func (c *HubClient) Status(ctx context.Context, id, status string, fraction float64) (bool, error) {
	var out struct {
		Cancel bool `json:"cancel"`
	}
	_, err := c.call(ctx, "POST", "/v1/steps/"+id+"/progress", progressReq{Status: status, Fraction: fraction}, &out)
	return out.Cancel, err
}

// Note sends a plugin step's line for the asker, shown above the reply.
func (c *HubClient) Note(ctx context.Context, id, note string) (bool, error) {
	var out struct {
		Cancel bool `json:"cancel"`
	}
	_, err := c.call(ctx, "POST", "/v1/steps/"+id+"/progress", progressReq{Note: note}, &out)
	return out.Cancel, err
}

// CompleteWithFiles finishes a plugin step with what it made.
func (c *HubClient) CompleteWithFiles(ctx context.Context, id string, stats ChatStats, files []StepFile) error {
	_, err := c.call(ctx, "POST", "/v1/steps/"+id+"/complete", completeReq{Stats: stats, Files: files}, nil)
	return err
}

// Plugins asks the hub which plugins could handle a request, best first, among
// those on the devices the request may run on.
func (c *HubClient) Plugins(ctx context.Context, query, accepts string, scope pluginScope) ([]PluginCandidate, error) {
	v := url.Values{}
	v.Set("q", query)
	if accepts != "" {
		v.Set("accepts", accepts)
	}
	if scope.Target != "" {
		v.Set("target", scope.Target)
	}
	if scope.Private {
		v.Set("private", "1")
	}
	var out struct {
		Plugins []PluginCandidate `json:"plugins"`
	}
	_, err := c.call(ctx, "GET", "/v1/plugins?"+v.Encode(), nil, &out)
	return out.Plugins, err
}

func (c *HubClient) Fail(ctx context.Context, id string, f failReq) error {
	_, err := c.call(ctx, "POST", "/v1/steps/"+id+"/fail", f, nil)
	return err
}

func (c *HubClient) Submit(ctx context.Context, req submitReq) (string, error) {
	var out struct {
		ID string `json:"id"`
	}
	_, err := c.call(ctx, "POST", "/v1/steps", req, &out)
	return out.ID, err
}

func (c *HubClient) Cancel(ctx context.Context, id string) error {
	_, err := c.call(ctx, "POST", "/v1/steps/"+id+"/cancel", map[string]any{}, nil)
	return err
}

// Events streams a step's events until fn returns false or the stream ends.
func (c *HubClient) Events(ctx context.Context, id string, fn func(hubEvent) bool) error {
	req, err := c.newReq(ctx, "GET", "/v1/steps/"+id+"/events", nil)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "text/event-stream")
	resp, err := c.hc.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		var e struct {
			Error string `json:"error"`
		}
		_ = json.Unmarshal(b, &e)
		return &apiError{Status: resp.StatusCode, Msg: e.Error}
	}
	sc := bufio.NewScanner(resp.Body)
	sc.Buffer(make([]byte, 64*1024), 32<<20)
	var data strings.Builder
	for sc.Scan() {
		line := sc.Text()
		if line == "" {
			if data.Len() > 0 {
				var ev hubEvent
				if err := json.Unmarshal([]byte(data.String()), &ev); err == nil {
					if !fn(ev) {
						return nil
					}
				}
				data.Reset()
			}
			continue
		}
		if v, ok := strings.CutPrefix(line, "data:"); ok {
			data.WriteString(strings.TrimPrefix(v, " "))
		}
	}
	if err := sc.Err(); err != nil {
		return err
	}
	return io.ErrUnexpectedEOF
}

// ---------- library ----------

type libQuery struct {
	Q, Kind, Status string
	Limit           int
	Full            bool
}

type libListResp struct {
	Entries []LibEntry `json:"entries"`
	Admin   bool       `json:"admin"`
}

func (c *HubClient) Library(ctx context.Context, q libQuery) (libListResp, error) {
	v := url.Values{}
	if q.Q != "" {
		v.Set("q", q.Q)
	}
	if q.Kind != "" {
		v.Set("kind", q.Kind)
	}
	if q.Status != "" {
		v.Set("status", q.Status)
	}
	if q.Limit > 0 {
		v.Set("limit", fmt.Sprint(q.Limit))
	}
	if q.Full {
		v.Set("full", "1")
	}
	var out libListResp
	_, err := c.call(ctx, "GET", "/v1/library?"+v.Encode(), nil, &out)
	return out, err
}

func (c *HubClient) LibraryGet(ctx context.Context, id string) (LibEntry, error) {
	var out LibEntry
	_, err := c.call(ctx, "GET", "/v1/library/"+url.PathEscape(id), nil, &out)
	return out, err
}

func (c *HubClient) LibraryAdd(ctx context.Context, req libAddReq) (LibEntry, error) {
	var out LibEntry
	_, err := c.call(ctx, "POST", "/v1/library", req, &out)
	return out, err
}

func (c *HubClient) LibraryReview(ctx context.Context, id, action, note string) (json.RawMessage, error) {
	var out json.RawMessage
	_, err := c.call(ctx, "POST", "/v1/library/"+url.PathEscape(id)+"/review", map[string]string{"action": action, "note": note}, &out)
	return out, err
}

func (c *HubClient) LibraryUsed(ctx context.Context, id string) error {
	_, err := c.call(ctx, "POST", "/v1/library/"+url.PathEscape(id)+"/used", map[string]any{}, nil)
	return err
}

func (c *HubClient) Feedback(ctx context.Context, req feedbackReq) (bool, error) {
	var out struct {
		Queued bool `json:"queued"`
	}
	_, err := c.call(ctx, "POST", "/v1/feedback", req, &out)
	return out.Queued, err
}

func (c *HubClient) AdminSettings(ctx context.Context, settings map[string]any) error {
	_, err := c.call(ctx, "POST", "/v1/admin/settings", settings, nil)
	return err
}

// Raw fetches a GET endpoint's body as is (for downloads).
func (c *HubClient) Raw(ctx context.Context, path string) ([]byte, error) {
	req, err := c.newReq(ctx, "GET", path, nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.hc.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	b, err := io.ReadAll(io.LimitReader(resp.Body, 256<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		var e struct {
			Error string `json:"error"`
		}
		_ = json.Unmarshal(b, &e)
		return nil, &apiError{Status: resp.StatusCode, Msg: firstNonEmpty(e.Error, resp.Status)}
	}
	return b, nil
}

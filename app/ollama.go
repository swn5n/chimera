package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

// OllamaClient talks to the Ollama server on this computer.
type OllamaClient struct {
	Base string
	hc   *http.Client
}

var sharedTransport = &http.Transport{
	Proxy:               nil, // local and LAN traffic only; never via a system proxy
	DialContext:         (&net.Dialer{Timeout: 5 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
	MaxIdleConns:        64,
	MaxIdleConnsPerHost: 16,
	IdleConnTimeout:     90 * time.Second,
}

func NewOllamaClient(base string) *OllamaClient {
	return &OllamaClient{Base: normalizeOllamaURL(base), hc: &http.Client{Transport: sharedTransport}}
}

func normalizeOllamaURL(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		s = os.Getenv("OLLAMA_HOST")
	}
	if s == "" {
		return "http://127.0.0.1:11434"
	}
	if !strings.Contains(s, "://") {
		s = "http://" + s
	}
	u, err := url.Parse(s)
	if err != nil {
		return "http://127.0.0.1:11434"
	}
	host, port := u.Hostname(), u.Port()
	if host == "" || host == "0.0.0.0" || host == "::" {
		host = "127.0.0.1"
	}
	if port == "" {
		port = "11434"
	}
	return u.Scheme + "://" + net.JoinHostPort(host, port)
}

type ChatMessage struct {
	Role     string `json:"role"`
	Content  string `json:"content"`
	Thinking string `json:"thinking,omitempty"`
}

type ChatStats struct {
	PromptEvalCount    int    `json:"prompt_eval_count"`
	EvalCount          int    `json:"eval_count"`
	TotalDuration      int64  `json:"total_duration"`
	LoadDuration       int64  `json:"load_duration"`
	PromptEvalDuration int64  `json:"prompt_eval_duration"`
	EvalDuration       int64  `json:"eval_duration"`
	DoneReason         string `json:"done_reason,omitempty"`
}

func (s ChatStats) TokPerSec() float64 {
	if s.EvalDuration <= 0 || s.EvalCount <= 0 {
		return 0
	}
	return round1(float64(s.EvalCount) / (float64(s.EvalDuration) / 1e9))
}

type ollamaTag struct {
	Name    string `json:"name"`
	Model   string `json:"model"`
	Size    int64  `json:"size"`
	Digest  string `json:"digest"`
	Details struct {
		Family            string `json:"family"`
		ParameterSize     string `json:"parameter_size"`
		QuantizationLevel string `json:"quantization_level"`
	} `json:"details"`
}

type ollamaShow struct {
	Capabilities []string       `json:"capabilities"`
	ModelInfo    map[string]any `json:"model_info"`
}

type ollamaPS struct {
	Name     string `json:"name"`
	Model    string `json:"model"`
	Size     int64  `json:"size"`
	SizeVRAM int64  `json:"size_vram"`
	Digest   string `json:"digest"`
}

func (c *OllamaClient) getJSON(ctx context.Context, path string, out any) error {
	req, _ := http.NewRequestWithContext(ctx, "GET", c.Base+path, nil)
	resp, err := c.hc.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return readOllamaError(resp)
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

func (c *OllamaClient) postJSON(ctx context.Context, path string, in, out any) error {
	b, _ := json.Marshal(in)
	req, _ := http.NewRequestWithContext(ctx, "POST", c.Base+path, bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.hc.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return readOllamaError(resp)
	}
	if out == nil {
		_, _ = io.Copy(io.Discard, resp.Body)
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

func readOllamaError(resp *http.Response) error {
	b, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
	var e struct {
		Error string `json:"error"`
	}
	if json.Unmarshal(b, &e) == nil && e.Error != "" {
		return errors.New(e.Error)
	}
	return fmt.Errorf("Ollama returned %s", resp.Status)
}

func (c *OllamaClient) Version(ctx context.Context) (string, error) {
	var v struct {
		Version string `json:"version"`
	}
	err := c.getJSON(ctx, "/api/version", &v)
	return v.Version, err
}

func (c *OllamaClient) Tags(ctx context.Context) ([]ollamaTag, error) {
	var v struct {
		Models []ollamaTag `json:"models"`
	}
	err := c.getJSON(ctx, "/api/tags", &v)
	return v.Models, err
}

func (c *OllamaClient) Show(ctx context.Context, model string) (ollamaShow, error) {
	var v ollamaShow
	err := c.postJSON(ctx, "/api/show", map[string]any{"model": model}, &v)
	return v, err
}

func (c *OllamaClient) PS(ctx context.Context) ([]ollamaPS, error) {
	var v struct {
		Models []ollamaPS `json:"models"`
	}
	err := c.getJSON(ctx, "/api/ps", &v)
	return v.Models, err
}

// Unload frees a model's memory right away.
func (c *OllamaClient) Unload(ctx context.Context, model string) error {
	return c.postJSON(ctx, "/api/generate", map[string]any{"model": model, "keep_alive": 0, "stream": false}, nil)
}

// ChatStream runs a chat and calls onDelta for each streamed piece.
func (c *OllamaClient) ChatStream(ctx context.Context, model string, msgs []ChatMessage, options map[string]any, format json.RawMessage, onDelta func(content, thinking string)) (ChatStats, error) {
	return c.ChatStreamKeep(ctx, model, msgs, options, format, "15m", onDelta)
}

// ChatStreamKeep is ChatStream with how long Ollama keeps the model loaded
// afterwards ("0s" unloads it as soon as the reply is done).
func (c *OllamaClient) ChatStreamKeep(ctx context.Context, model string, msgs []ChatMessage, options map[string]any, format json.RawMessage, keepAlive string, onDelta func(content, thinking string)) (ChatStats, error) {
	clean := make([]ChatMessage, 0, len(msgs))
	for _, m := range msgs {
		clean = append(clean, ChatMessage{Role: m.Role, Content: m.Content})
	}
	body := map[string]any{"model": model, "messages": clean, "stream": true, "keep_alive": keepAlive}
	if len(options) > 0 {
		body["options"] = options
	}
	if len(format) > 0 && string(format) != "null" {
		body["format"] = format
	}
	b, _ := json.Marshal(body)
	req, _ := http.NewRequestWithContext(ctx, "POST", c.Base+"/api/chat", bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.hc.Do(req)
	if err != nil {
		return ChatStats{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		err := readOllamaError(resp)
		if _, hasFormat := body["format"]; hasFormat && strings.Contains(strings.ToLower(err.Error()), "format") {
			// Some models don't support structured output; our prompts ask for
			// JSON anyway, so try once more without it.
			return c.ChatStreamKeep(ctx, model, msgs, options, nil, keepAlive, onDelta)
		}
		return ChatStats{}, err
	}
	dec := json.NewDecoder(resp.Body)
	for {
		var chunk struct {
			Message ChatMessage `json:"message"`
			Done    bool        `json:"done"`
			Error   string      `json:"error"`
			ChatStats
		}
		if err := dec.Decode(&chunk); err != nil {
			if ctx.Err() != nil {
				return ChatStats{}, ctx.Err()
			}
			if err == io.EOF {
				return ChatStats{}, errors.New("Ollama ended the reply early")
			}
			return ChatStats{}, err
		}
		if chunk.Error != "" {
			return ChatStats{}, errors.New(chunk.Error)
		}
		if chunk.Message.Content != "" || chunk.Message.Thinking != "" {
			onDelta(chunk.Message.Content, chunk.Message.Thinking)
		}
		if chunk.Done {
			return chunk.ChatStats, nil
		}
	}
}

type PullProgress struct {
	Status    string `json:"status"`
	Completed int64  `json:"completed"`
	Total     int64  `json:"total"`
}

// Pull downloads a model, reporting progress.
func (c *OllamaClient) Pull(ctx context.Context, model string, onProgress func(PullProgress)) error {
	b, _ := json.Marshal(map[string]any{"model": model, "stream": true})
	req, _ := http.NewRequestWithContext(ctx, "POST", c.Base+"/api/pull", bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.hc.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return readOllamaError(resp)
	}
	dec := json.NewDecoder(resp.Body)
	for {
		var p struct {
			PullProgress
			Error string `json:"error"`
		}
		if err := dec.Decode(&p); err != nil {
			if err == io.EOF {
				return nil
			}
			return err
		}
		if p.Error != "" {
			return errors.New(p.Error)
		}
		onProgress(p.PullProgress)
		if p.Status == "success" {
			return nil
		}
	}
}

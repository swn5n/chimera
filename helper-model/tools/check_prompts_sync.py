#!/usr/bin/env python3
"""Keep the helper's copies of Chimera's prompts and reply-reading code in step with app/.

    python3 tools/check_prompts_sync.py            # exit 1 if anything drifted
    python3 tools/check_prompts_sync.py --write    # regenerate helper/prompts.py from app/

helper/prompts.py holds Chimera's prompt strings verbatim (generated, never retyped).
helper/chimera_port.py re-implements the Go code that builds the messages and reads the
replies. This script checks that every Go line the port mirrors is still in app/ word for
word, and that the Go structs still have the fields and types the port decodes, so a change
in app/ fails here instead of silently skewing the eval or the training data.
"""
from __future__ import annotations

import argparse
import importlib
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # helper-model/
DEFAULT_APP = os.path.join(os.path.dirname(HERE), "app")
PROMPTS_PY = os.path.join(HERE, "helper", "prompts.py")

CONSTS = [  # python name, go file, go const (a raw `...` string)
    ("HYDRA_PLANNER_PROMPT", "prompts.go", "hydraPlannerPrompt"),
    ("HYDRA_REVIEW_PROMPT", "prompts.go", "hydraReviewPrompt"),
    ("HEAD_GATE_PROMPT", "plugin_chat.go", "headGatePrompt"),
]

# Go lines helper/chimera_port.py mirrors. Each must still appear verbatim in its file.
FRAGMENTS = {
    "hydra.go": [
        # onePass: the planner request (round 1, later rounds, library refs)
        "userMsg := contextBlock(req.history) + req.Goal",
        r'userMsg += "\n\n---\nThe previous attempt produced this result:\n" + truncate(prior, 12000) +',
        r'"\n\nWhat still needs work:\n" + critique +',
        r'"\n\nPlan the steps to improve it into a result that fully meets the task. Reuse what already works; only redo what needs it."',
        "userMsg += refsBlock(useful)",
        'planMsgs := []ChatMessage{{Role: "system", Content: hydraPlannerPrompt}, {Role: "user", Content: userMsg}}',
        'Format: json.RawMessage(`"json"`), NeedCtx: historyTokens(planMsgs) + 2048',
        "if !extractJSON(planText.String(), &plan) || len(plan.Steps) == 0 {",
        "plan = cleanPlan(plan)",
        # review
        '{Role: "system", Content: hydraReviewPrompt},',
        r'{Role: "user", Content: "The task:\n" + req.Goal + "\n\nThe result so far:\n" + truncate(result, 40000)},',
        'Format: json.RawMessage(`"json"`), NeedCtx: historyTokens(msgs) + 1024',
        "return reviewVerdict{Done: true}, ev // can't review: treat current result as final",
        "return reviewVerdict{Done: true}, genEvent{} // unparseable: stop with what we have",
        'if revTerm.Type != "" || v.Done {',
        "critique = v.Critique",
        # contextBlock
        "if len(history) > 6 {",
        "history = history[len(history)-6:]",
        r'b.WriteString("Earlier in this chat (for context only):\n")',
        r'fmt.Fprintf(&b, "\n[%s]\n%s\n", m.Role, truncate(m.Content, 2500))',
        r'b.WriteString("\n---\nThe task:\n")',
        # refsBlock
        r'''b.WriteString("\n\nKnown-good references from your network's library, checked by the network (reuse them when they fit; ignore them when they don't):\n")''',
        r'fmt.Fprintf(&b, "\n--- %s (%s) ---\n%s\n%s\n", e.Title, e.Kind, e.Summary, truncate(e.Content, 3000))',
        # cleanPlan
        "if len(p.Steps) > 8 {",
        "p.Steps = p.Steps[:8]",
        'kinds := map[string]bool{"code": true, "writing": true, "research": true, "blender": true, "general": true}',
        'p.Kind = "general"',
        'if s.ID == "" || ids[s.ID] {',
        's.ID = fmt.Sprintf("s%d", i+1)',
        "s.Kind = p.Kind",
        'if strings.TrimSpace(s.Title) == "" {',
        's.Title = fmt.Sprintf("Step %d", i+1)',
        'if strings.TrimSpace(s.Instructions) == "" {',
        "s.Instructions = s.Title",
        's.Status = "waiting"',
        "if seen[d] {",
        "seen[p.Steps[i].ID] = true",
        'p.Title = "Long task"',
    ],
    "plugin_chat.go": [
        'if strings.TrimSpace(text) == "" {',
        "use = best.Relevance >= 0.75",
        'desc := p.Name + ": " + p.Summary',
        'if p.WhenToUse != "" {',
        r'desc += "\nUse it when: " + p.WhenToUse',
        '{Role: "system", Content: headGatePrompt},',
        r'{Role: "user", Content: "Tool: " + desc + "\n\nRequest: " + text + "\n\nShould this tool handle the request?"},',
        'req := submitReq{Messages: msgs, Format: headGateSchema, Prefer: "fastest", NeedCtx: historyTokens(msgs) + 256,',
        'Options: map[string]any{"temperature": 0}',
        "gctx, cancel := context.WithTimeout(ctx, 45*time.Second)",
        "const gateWaitElsewhere = 8 * time.Second",
        'Use bool `json:"use"`',
        "if !extractJSON(reply.String(), &ans) {",
        'if mime == "" && len(p.Accepts) > 0 && !p.OptionalInput {',
        "if len(terms) > 0 && rel < pluginMinRelevance {",
    ],
    "library.go": [
        "func estimateTokens(s string) int { return len(s)/3 + 64 }",
        "s = strings.TrimSpace(s)",
        "if json.Unmarshal([]byte(s), v) == nil {",
        'start := strings.Index(s, "{")',
        'end := strings.LastIndex(s, "}")',
        "if start < 0 || end <= start {",
        "return json.Unmarshal([]byte(s[start:end+1]), v) == nil",
        "for n > 0 && !utf8.RuneStart(s[n]) {",
        r'return s[:n] + "\n…(cut)"',
        "var wordRe = regexp.MustCompile(`[a-z0-9][a-z0-9_+#.-]*`)",
        "for _, w := range wordRe.FindAllString(strings.ToLower(s), -1) {",
        'w = strings.Trim(w, ".-")',
        "if len(w) < 2 || stopWords[w] || seen[w] {",
    ],
    "hub_plugins.go": [
        "if withInput && pluginWeakWords[t] {",
        'if !withInput && (t == "it" || t == "just" || t == "thing" || t == "like" || t == "want" || t == "need") {',
        'name := strings.ToLower(p.Name + " " + p.ID)',
        'tags := strings.ToLower(strings.Join(append(append([]string{}, p.Tags...), p.TaskKinds...), " "))',
        "summary := strings.ToLower(p.Summary)",
        "when := strings.ToLower(p.WhenToUse)",
        "case strings.Contains(name, t):",
        "sum += 3",
        "case strings.Contains(tags, t):",
        "sum += 2.5",
        "case strings.Contains(summary, t):",
        "sum += 1.5",
        "case strings.Contains(when, t):",
        "sum += 1",
        "return round2(math.Min(1, sum/6))",
        'terms := pluginTerms(query, accepts != "")',
        "if len(terms) > 0 && rel < pluginMinRelevance {",
        'if accepts == "" && len(p.Accepts) > 0 && !p.OptionalInput {',
    ],
    "hub.go": [
        "func ctxBucket(need, max int) int {",
        "b := 8192",
        "case need > 65536:",
        "b = 131072",
        "case need > 30000:",
        "b = 65536",
        "case need > 7000:",
        "b = 32768",
        "if max > 0 && b > max {",
        "a.NumCtx = ctxBucket(st.NeedCtx, max)",
    ],
    "util.go": ["func round2(v float64) float64 { return math.Round(v*100) / 100 }"],
    "runprompt.go": [
        'opts := map[string]any{"num_ctx": ctxBucket(req.NeedCtx, m.CtxMax)}',
        "n += estimateTokens(m.Content)",
    ],
    "ollama.go": [
        'return c.ChatStreamKeep(ctx, model, msgs, options, format, "15m", onDelta)',
        "clean = append(clean, ChatMessage{Role: m.Role, Content: m.Content})",
        'body := map[string]any{"model": model, "messages": clean, "stream": true, "keep_alive": keepAlive}',
        'if len(format) > 0 && string(format) != "null" {',
        'if _, hasFormat := body["format"]; hasFormat && strings.Contains(strings.ToLower(err.Error()), "format") {',
    ],
}

# Go structs the port decodes replies into (file, struct, python spec name).
STRUCTS = [
    ("hydra.go", "hydraStep", "STEP_SPEC"),
    ("hydra.go", "hydraPlan", "PLAN_SPEC"),
    ("hydra.go", "reviewVerdict", "REVIEW_SPEC"),
]


def read(app, name):
    with open(os.path.join(app, name), encoding="utf-8") as f:
        return f.read()


def go_raw_const(src, name):
    m = re.search(r"const\s+" + re.escape(name) + r"\s*=\s*`([^`]*)`", src)
    if not m:
        raise SystemExit(f"can't find const {name}")
    return m.group(1)


def go_map_words(src, name):
    m = re.search(r"var\s+" + re.escape(name) + r"\s*=\s*map\[string\]bool\{(.*?)\}\n", src, re.S)
    if not m:
        raise SystemExit(f"can't find map {name}")
    return sorted(re.findall(r'"([^"]+)":\s*true', m.group(1)))


def go_struct_fields(src, name):
    m = re.search(r"type\s+" + re.escape(name) + r"\s+struct\s*\{(.*?)\n\}", src, re.S)
    if not m:
        raise SystemExit(f"can't find struct {name}")
    out = []
    for line in m.group(1).splitlines():
        f = re.match(r'\s*\w+\s+([\w.\[\]*]+)\s+`json:"([^",]*)[^"]*"`', line)
        if f:
            out.append((f.group(2), f.group(1)))
    return out


def git_head(repo):
    try:
        with open(os.path.join(repo, ".git", "HEAD")) as f:
            head = f.read().strip()
        if not head.startswith("ref: "):
            return head[:12]
        ref = head[5:]
        p = os.path.join(repo, ".git", ref)
        if os.path.exists(p):
            with open(p) as f:
                return f.read().strip()[:12]
        with open(os.path.join(repo, ".git", "packed-refs")) as f:
            for line in f:
                if line.strip().endswith(" " + ref):
                    return line.split()[0][:12]
    except OSError:
        pass
    return "unknown"


def collect(app):
    """Everything helper/prompts.py holds, read fresh from app/."""
    vals = {}
    for py, fname, go in CONSTS:
        vals[py] = go_raw_const(read(app, fname), go)
    m = re.search(r"var\s+headGateSchema\s*=\s*json\.RawMessage\(`([^`]*)`\)", read(app, "plugin_chat.go"))
    if not m:
        raise SystemExit("can't find headGateSchema")
    vals["HEAD_GATE_SCHEMA"] = m.group(1)
    vals["STOP_WORDS"] = go_map_words(read(app, "library.go"), "stopWords")
    vals["PLUGIN_WEAK_WORDS"] = go_map_words(read(app, "hub_plugins.go"), "pluginWeakWords")
    m = re.search(r"pluginMinRelevance\s*=\s*([0-9.]+)", read(app, "hub_plugins.go"))
    vals["PLUGIN_MIN_RELEVANCE"] = float(m.group(1))
    m = re.search(r'const\s+Version\s*=\s*"([^"]+)"', read(app, "main.go"))
    vals["CHIMERA_VERSION"] = m.group(1) if m else "unknown"
    return vals


def write_prompts(app):
    vals = collect(app)
    lines = [
        "# Generated by tools/check_prompts_sync.py --write. Don't edit by hand: re-run it when",
        "# Chimera's prompts change. Copied verbatim from app/prompts.go, app/plugin_chat.go,",
        "# app/library.go and app/hub_plugins.go.",
        "",
        f"CHIMERA_VERSION = {vals['CHIMERA_VERSION']!r}",
        f"CHIMERA_GIT = {git_head(os.path.dirname(app))!r}  # HEAD when copied; informational",
        "",
    ]
    for key in ("HYDRA_PLANNER_PROMPT", "HYDRA_REVIEW_PROMPT", "HEAD_GATE_PROMPT", "HEAD_GATE_SCHEMA"):
        lines.append(f"{key} = {vals[key]!r}")
        lines.append("")
    for key in ("STOP_WORDS", "PLUGIN_WEAK_WORDS"):
        lines.append(f"{key} = frozenset({vals[key]!r})")
        lines.append("")
    lines.append(f"PLUGIN_MIN_RELEVANCE = {vals['PLUGIN_MIN_RELEVANCE']!r}")
    with open(PROMPTS_PY, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {os.path.relpath(PROMPTS_PY, HERE)} from Chimera {vals['CHIMERA_VERSION']}")


def check(app):
    sys.path.insert(0, HERE)
    problems = []
    try:
        prompts = importlib.import_module("helper.prompts")
        port = importlib.import_module("helper.chimera_port")
    except Exception as e:  # noqa: BLE001
        return [f"can't import the helper package: {e}"]
    vals = collect(app)
    for key, want in vals.items():
        have = getattr(prompts, key, None)
        if key in ("STOP_WORDS", "PLUGIN_WEAK_WORDS"):
            have = sorted(have or [])
        if key == "CHIMERA_VERSION":
            if have != want:
                print(f"note: prompts.py was copied from Chimera {have}; app/ is now {want}")
            continue
        if have != want:
            problems.append(f"helper/prompts.py {key} differs from app/ (run with --write, then re-check the port)")
    for fname, frags in FRAGMENTS.items():
        src = read(app, fname)
        for frag in frags:
            if frag not in src:
                problems.append(f"app/{fname} no longer contains: {frag}")
    gotype = {"string": "string", "bool": "bool", "int": "int", "float64": "float", "time.Time": "time",
              "[]string": ("slice", "string")}
    for fname, struct, spec_name in STRUCTS:
        spec = getattr(port, spec_name)
        fields = go_struct_fields(read(app, fname), struct)
        go_view = {}
        for jname, t in fields:
            if t == "[]hydraStep":
                go_view[jname] = ("slice", ("struct", port.STEP_SPEC))
            else:
                go_view[jname] = gotype.get(t, "?" + t)
        if go_view != spec:
            problems.append(f"{struct} in app/{fname} has fields {go_view}, helper/chimera_port.py {spec_name} has {spec}")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", default=DEFAULT_APP, help="Chimera's app/ folder (default: ../app)")
    ap.add_argument("--write", action="store_true", help="regenerate helper/prompts.py, then check")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.app):
        print(f"no Chimera source at {a.app}")
        return 2
    if a.write:
        write_prompts(a.app)
    problems = check(a.app)
    for p in problems:
        print("DRIFT:", p)
    if problems:
        return 1
    n = sum(len(v) for v in FRAGMENTS.values())
    print(f"in sync with app/: {len(CONSTS) + 1} prompts/schema, {n} mirrored Go lines, {len(STRUCTS)} structs")
    return 0


if __name__ == "__main__":
    sys.exit(main())

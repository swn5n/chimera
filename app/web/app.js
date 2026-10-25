"use strict";

/* Chimera interface. State streams in from the local app at /api/stream. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let S = null;            // latest state from the app
let view = "network";

async function api(method, path, body) {
  const r = await fetch(path, {
    method,
    headers: { "X-Chimera": "1", "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  try { data = await r.json(); } catch { /* no body */ }
  if (!r.ok) throw new Error((data && data.error) || `Something went wrong (${r.status}).`);
  return data;
}

// Reads a server-sent event stream from a fetch() response.
async function readSSE(res, onEvent) {
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const data = chunk.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).replace(/^ /, "")).join("\n");
      if (data) {
        let ev;
        try { ev = JSON.parse(data); } catch { continue; }
        onEvent(ev);
      }
    }
  }
}

// ---------- small helpers ----------
let toastTimer;
function toast(msg, bad = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.toggle("bad", bad);
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), bad ? 6500 : 2400);
}
function setHTML(el, html) {
  if (el._html !== html) { el.innerHTML = html; el._html = html; }
}
const normModel = (s) => { s = String(s || "").trim().toLowerCase(); return s && !s.includes(":") ? s + ":latest" : s; };
const sameOwner = (a, b) => String(a || "").trim().toLowerCase() !== "" && String(a || "").trim().toLowerCase() === String(b || "").trim().toLowerCase();
const canChat = (m) => (m.caps && m.caps.length ? m.caps.includes("completion") : !/embed/i.test(m.name));
const fmtGB = (bytes) => { const gb = (bytes || 0) / 1e9; return gb >= 10 ? `${Math.round(gb)} GB` : `${gb.toFixed(1)} GB`; };
const fmtNum = (n) => Number(n || 0).toLocaleString();
const fmtCredits = (n) => { n = Number(n || 0); return Math.abs(n) >= 100 ? n.toFixed(1) : n.toFixed(2); };
const plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;
const gb = (v) => { v = Number(v || 0); return v >= 10 ? `${Math.round(v)} GB` : `${v.toFixed(1)} GB`; };
const ctxWord = (n) => (n >= 1024 ? `${Math.round(n / 1024)}K` : String(n || 0));
const FIT = {
  comfortable: { word: "Fits well", led: "ice" },
  tight: { word: "Tight fit", led: "amber" },
  too_big: { word: "Too big", led: "brick" },
  unsupported: { word: "Not on this computer", led: "off" },
  unknown: { word: "Checking…", led: "off" },
};
const fitOf = (f) => FIT[f] || FIT.unknown;
function listWords(items) {
  items = items.filter(Boolean);
  if (items.length <= 1) return items.join("");
  return items.slice(0, -1).join(", ") + " and " + items[items.length - 1];
}
const STAR = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.6l2.9 6.1 6.7.8-4.9 4.6 1.3 6.6L12 17.4l-5.9 3.3 1.3-6.6-4.9-4.6 6.7-.8z"/></svg>';
function agoSec(sec) {
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}
const ago = (iso) => agoSec(Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000));
// "fx's M3 Ultra", or just "M3 Ultra" when it's one of yours.
const deviceLabel = (device, owner) => (owner && S && !sameOwner(owner, S.device.owner) ? `${owner}'s ${device}` : device);

function hwLine(info) {
  if (!info || !info.os) return null;
  const ram = info.ram_gb ? `${Math.round(info.ram_gb)} GB` : "";
  const gpu = (info.gpus || [])[0];
  if (info.os === "macOS") {
    return { main: info.chip || "Mac", sub: [ram && `${ram} unified memory`, gpu && gpu.name && gpu.name !== info.chip ? gpu.name : ""].filter(Boolean).join(", ") };
  }
  if (gpu && gpu.name) {
    const name = gpu.name.replace(/^NVIDIA GeForce /, "").replace(/^NVIDIA /, "").replace(/^AMD Radeon\(TM\) /, "Radeon ").replace(/^AMD /, "");
    return { main: name, sub: [gpu.vram_gb ? `${Math.round(gpu.vram_gb)} GB VRAM` : "", ram && `${ram} RAM`].filter(Boolean).join(", ") };
  }
  return { main: info.chip || info.os, sub: ram ? `${ram} RAM` : "" };
}

// ---------- views ----------
function setView(v) {
  view = v;
  $$(".mode").forEach((b) => (b.dataset.view === v ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current")));
  $$(".view").forEach((s) => (s.hidden = s.id !== `view-${v}`));
  try { localStorage.setItem("chimera.view", v); } catch { /* private mode */ }
  if (v === "chat") enterChat();
  if (v === "library") loadLibrary();
  if (v === "models" && S) renderModels();
}

// ---------- state stream ----------
let missed = 0;
function connectStream() {
  const es = new EventSource("/api/stream");
  es.addEventListener("state", (e) => {
    missed = 0;
    $("#gone").hidden = true;
    S = JSON.parse(e.data);
    render();
  });
  es.onerror = () => {
    missed++;
    if (missed >= 2) $("#gone").hidden = false;
  };
}

function render() {
  if (!S) return;
  renderBar();
  renderDeck();
  renderRack();
  renderHelp();
  renderMine();
  renderModels();
  renderActivity();
  renderSettings();
  renderSetupGate();
  refreshPickers();
  libraryStatsChanged();
  paintDownloads();
}

function renderBar() {
  const n = S.network;
  let led = "led off", name = "Not in a network";
  if (n.joined) {
    name = n.name || "Network";
    led = n.ok ? "led ice" : "led brick";
    if (!n.ok) name += ", can't reach the hub";
  } else if (S.hosting.enabled) {
    name = S.hosting.name || "Your network";
  }
  $("#bar-led").className = led;
  $("#bar-net-name").textContent = name;
  $("#bar-net").title = n.error || name;
  $("#bar-credits").hidden = !(n.joined && n.ok);
  $("#bar-credit-num").textContent = fmtCredits(n.balance);
}

// ---------- the deck: connect / disconnect ----------
function lendState() {
  const L = S.lending;
  if (L.state === "connected" && L.running.length) return "busy";
  return L.state;
}

function renderDeck() {
  const L = S.lending, st = lendState(), sw = $("#switch");
  sw.dataset.state = st;
  const net = S.network.name || "the network";
  $("#state-word").textContent = {
    disconnected: "Disconnected", connecting: "Connecting…", connected: "Connected",
    busy: "Connected", draining: "Finishing up", paused: "Paused",
  }[st] || "Disconnected";

  let line = "", err = false;
  if (st === "disconnected") {
    if (L.error) { line = L.error; err = true; }
    else if (!S.network.joined) line = "Your GPU is all yours. Host or join a network to start lending.";
    else line = `Your GPU is all yours. Connect to lend it to ${net}.`;
  } else if (st === "connecting") {
    line = S.ollama.status === "starting" ? "Opening Ollama…" : "Getting your models ready…";
  } else if (st === "connected") {
    line = `Lending ${plural(L.shared, "model")} to ${net}. Keep using this computer for lighter things.`;
  } else if (st === "busy") {
    line = `Lending ${plural(L.shared, "model")} to ${net}, and working on a step right now.`;
  } else if (st === "draining") {
    line = `Finishing ${L.running.length === 1 ? "the current step" : plural(L.running.length, "step")}, then disconnecting.`;
  } else if (st === "paused") {
    line = L.reason || "Paused.";
  }
  const el = $("#state-line");
  el.textContent = line;
  el.classList.toggle("error", err);

  const b = $("#btn-connect");
  b.disabled = st === "connecting";
  if (st === "disconnected") { b.textContent = "Connect"; b.className = "btn primary"; }
  else if (st === "connecting") { b.textContent = "Connecting…"; b.className = "btn"; }
  else if (st === "draining") { b.textContent = "Keep lending"; b.className = "btn"; }
  else { b.textContent = "Disconnect"; b.className = "btn"; }
  $("#btn-stop-now").hidden = st !== "draining";
  sw.disabled = st === "connecting";
  sw.setAttribute("aria-label", st === "disconnected" ? "Connect" : st === "draining" ? "Keep lending" : "Disconnect");

  setHTML($("#running"), L.running.map((r) => {
    const what = r.purpose ? `${esc(r.purpose)} for <strong>${esc(r.requester)}</strong>` : `Running a step for <strong>${esc(r.requester)}</strong>`;
    const toks = r.tokens ? `, ${fmtNum(r.tokens)} tokens so far` : "";
    return `<li><span class="led ice pulse"></span><span>${what} on ${esc(r.model)}${toks}</span></li>`;
  }).join(""));
  renderOllama();
}

function renderOllama() {
  const o = S.ollama;
  let status = "", sub = "", buttons = "";
  switch (o.status) {
    case "running":
      status = `<span class="led ice"></span><span>Running, version ${esc(o.version || "?")}</span>`;
      sub = o.models.length ? `${plural(o.models.length, "model")} downloaded` : "No models downloaded yet";
      break;
    case "starting":
      status = `<span class="led amber pulse"></span><span>Opening Ollama…</span>`;
      break;
    case "stopped":
      status = `<span class="led brick"></span><span>Not running</span>`;
      sub = "Chimera needs Ollama to lend your GPU.";
      buttons = `<button class="btn primary small" data-act="open-ollama">Open Ollama</button>`;
      break;
    case "missing":
      status = `<span class="led brick"></span><span>Not installed</span>`;
      sub = "Install Ollama, open it once, then come back.";
      buttons = `<a class="btn small" href="https://ollama.com/download" target="_blank" rel="noopener">Get Ollama</a>`;
      break;
    default:
      status = `<span class="led off"></span><span>Checking…</span>`;
  }
  setHTML($("#ollama-status"), `<p class="ollama-status">${status}</p>` + (sub ? `<p class="ollama-sub">${esc(sub)}</p>` : ""));
  setHTML($("#ollama-actions"), buttons);
}

async function toggleLending() {
  if (!S) return;
  const st = lendState();
  if (st === "connecting") return;
  if (st === "disconnected") {
    if (!S.network.joined) { openSetup("first"); return; }
    try { await api("POST", "/api/connect"); } catch (e) { toast(e.message, true); }
    return;
  }
  if (st === "draining") {
    try { await api("POST", "/api/connect"); } catch (e) { toast(e.message, true); }
    return;
  }
  if (S.lending.running.length) { openDisconnectDialog(); return; }
  try { await api("POST", "/api/disconnect", { mode: "finish" }); } catch (e) { toast(e.message, true); }
}

function openDisconnectDialog() {
  const r = S.lending.running;
  $("#dd-title").textContent = r.length === 1 ? "A step is still running" : `${r.length} steps are still running`;
  $("#dd-text").textContent = r.length === 1
    ? `Your GPU is writing a reply for ${r[0].requester} with ${r[0].model}.`
    : `Your GPU is working for ${[...new Set(r.map((x) => x.requester))].join(" and ")}.`;
  $("#dd-finish").textContent = r.length === 1 ? "Finish it, then disconnect" : "Finish them, then disconnect";
  $("#dlg-disconnect").hidden = false;
  $("#dd-finish").focus();
}

// ---------- rack of devices ----------
function deviceStatus(d) {
  if (!d.online) return { led: "brick", text: d.last_seen_sec < 0 ? "Never connected" : `Offline, ${agoSec(d.last_seen_sec)}`, cls: "brick", off: true };
  if (!d.ollama_ok) return { led: "amber", text: "Ollama off", cls: "amber" };
  if (d.draining) return { led: "amber pulse", text: "Finishing up", cls: "amber" };
  if (d.lending && d.busy > 0) return { led: "ice pulse", text: d.slots > 1 ? `Busy, ${d.busy} of ${d.slots}` : "Running a step", cls: "ice" };
  if (d.lending) return { led: "ice", text: "Lending", cls: "ice" };
  return { led: "off", text: "Not lending", cls: "" };
}

function unitHTML(d) {
  const s = deviceStatus(d), me = d.id === S.device.id, hw = hwLine(d.info);
  const models = (d.models || []).filter(canChat);
  const chips = models.slice(0, 4).map((m) =>
    `<span class="chip" title="${esc(m.name)}: ${esc(m.param_size)} ${esc(m.quant)}${m.loaded ? ", loaded in memory" : ""}">${m.loaded ? '<span class="dot"></span>' : ""}${esc(m.name)}<em>${fmtGB(m.size)}</em></span>`).join("");
  const more = models.length > 4 ? `<span class="chip more">${models.length - 4} more</span>` : "";
  let slots = "";
  if (d.online) slots = chips + more || `<span class="chip more">No models shared</span>`;
  return `<div class="unit${s.off ? " offline" : ""}">
    <span class="led ${s.led}"></span>
    <div class="who"><div class="name" title="${esc(d.name)}">${esc(d.name)}</div><div class="owner">${me ? '<span class="you">This computer</span>, ' : ""}${esc(d.owner)}</div></div>
    <div class="hw">${hw ? `<b title="${esc(hw.main)}">${esc(hw.main)}</b>${esc(hw.sub)}` : ""}${bestForLine(d)}</div>
    <div class="slots">${slots}</div>
    <div class="status ${s.cls}">${esc(s.text)}${d.app_version && S.version && d.app_version !== S.version ? `<span class="ver" title="Everyone should run the same Chimera version">Chimera ${esc(d.app_version)}</span>` : ""}</div>
  </div>`;
}

function bestForLine(d) {
  const best = (d.online && d.profile && d.profile.best_for) || [];
  if (!best.length) return "";
  return `<span class="bestfor" title="${esc("Best for " + listWords(best.map((b) => b.toLowerCase())))}">Best for ${esc(listWords(best.slice(0, 3).map((b) => b.toLowerCase())))}</span>`;
}

function renderRack() {
  const n = S.network;
  $("#rack-title").textContent = n.joined ? (n.name || "Network") : "Network";
  renderInvite();
  const rack = $("#rack");
  if (!n.joined) {
    $("#rack-note").textContent = "";
    setHTML(rack, `<div class="empty"><p>You're not in a network yet. Host one on this computer, or join a friend's with their address and invite code.</p>
      <div class="btns"><button class="btn primary" data-act="host">Host a network</button><button class="btn" data-act="join">Join a network</button></div></div>`);
    return;
  }
  if (!n.ok && !n.devices.length) {
    $("#rack-note").textContent = "";
    setHTML(rack, `<div class="empty"><p>${esc(n.error || "Can't reach the hub right now.")}</p><div class="btns"><button class="btn" data-act="join">Join a different network</button></div></div>`);
    return;
  }
  const online = n.devices.filter((d) => d.online).length;
  const lending = n.devices.filter((d) => d.lending).length;
  $("#rack-note").textContent = `${online} online, ${lending} lending${n.queue ? `, ${n.queue} waiting` : ""}${n.ok ? "" : ", hub unreachable"}`;
  const ordered = [...n.devices].sort((a, b) => (b.id === S.device.id) - (a.id === S.device.id));
  let html = ordered.map(unitHTML).join("");
  if (n.devices.length <= 1) {
    html += `<p class="fine">${S.hosting.enabled ? "Only you so far. Send a friend the address and invite code above." : "Only you so far."}</p>`;
  }
  setHTML(rack, html);
}

function renderInvite() {
  const h = S.hosting, box = $("#invite");
  if (!h.enabled) { box.hidden = true; return; }
  box.hidden = false;
  const addrs = (h.addresses || []).map((a) =>
    `<button class="copy" data-copy="${esc(a.ip)}:${h.port}" title="Copy">${esc(a.ip)}:${h.port} <small>${esc(a.label)}</small></button>`).join("")
    || `<span class="fine">No network address found. Check your Wi-Fi.</span>`;
  setHTML(box, `<span class="k">Address</span><div class="v">${addrs}</div>
    <span class="k">Invite code</span><div class="v"><button class="copy code" data-copy="${esc(h.invite)}" title="Copy">${esc(h.invite)}</button><span class="fine">Friends choose Join a network in their Chimera and enter these.</span></div>`);
}

// ---------- help wanted ----------
function renderHelp() {
  const box = $("#help"), items = (S.network.joined && S.help) || [];
  if (!items.length) { box.hidden = true; setHTML(box, ""); return; }
  box.hidden = false;
  const limit = S.settings.max_model_gb;
  setHTML(box, `<div class="section-head"><h2 class="section-title">Help wanted</h2><span class="section-note">What the network waited for in the last hour</span></div>` +
    items.map((h, i) => {
      let btn = "";
      if (h.action === "connect") btn = `<button class="btn small primary" data-help="${i}">Connect</button>`;
      else if (h.action === "share") {
        const m = S.ollama.models.find((x) => normModel(x.name) === normModel(h.model));
        btn = m && limit > 0 && m.size / 1e9 > limit
          ? `<button class="btn small" data-goto="settings">Raise limit</button>`
          : `<button class="btn small" data-help="${i}">Share it</button>`;
      } else if (h.action === "download") btn = downloadButton(h.model);
      return `<div class="help-item"><span class="led amber"></span><div><b>${esc(h.title)}</b><p>${esc(h.detail)}</p></div>${btn}</div>`;
    }).join(""));
}

async function doHelp(i) {
  const h = (S.help || [])[i];
  if (!h) return;
  if (h.action === "connect") toggleLending();
  else if (h.action === "share") setShared(h.model, true);
  else if (h.action === "download") queuePull(h.model);
}

// ---------- this computer ----------
function renderMine() {
  const o = S.ollama, set = S.settings, hw = hwLine(S.device.info), p = S.profile;
  $("#mine-hw").textContent = hw ? `${S.device.name}: ${hw.main}${hw.sub ? ", " + hw.sub : ""}` : S.device.name;
  const box = $("#mine-models");
  if (o.status !== "running") {
    $("#mine-note").textContent = "";
    setHTML(box, `<p class="blank">Your models show up here once Ollama is running.</p>`);
    return;
  }
  if (!o.models.length) {
    $("#mine-note").textContent = "";
    setHTML(box, `<p class="blank">No models yet. Models has picks that fit this computer.</p>`);
    return;
  }
  const unshared = new Set((set.unshared || []).map(normModel));
  let lent = 0;
  const html = o.models.map((m) => {
    const overLimit = set.max_model_gb > 0 && m.size / 1e9 > set.max_model_gb;
    const chatty = canChat(m);
    const tooBig = chatty && m.fits === "too_big";
    const on = chatty && !overLimit && !tooBig && !unshared.has(normModel(m.name));
    if (on) lent++;
    const caps = (m.caps || []).filter((c) => c !== "completion" && c !== "tools");
    const meta = [m.param_size, fmtGB(m.size), chatty && m.ctx_max ? `up to ${ctxWord(m.ctx_max)} context` : "", caps.join(", ")].filter(Boolean).join(", ");
    const fit = chatty && m.fits === "tight" ? ` <span class="fitnote tight" title="Close to this computer's memory limit">Tight fit</span>` : "";
    let right;
    if (!chatty) right = `<span class="why muted">Not a chat model</span>`;
    else if (tooBig) right = `<span class="why" title="It would spill out of GPU memory, run slowly and time out">Too big to lend</span>`;
    else if (overLimit) right = `<span class="why">Over your ${set.max_model_gb} GB limit</span>`;
    else right = `<label><input type="checkbox" data-share="${esc(m.name)}" ${on ? "checked" : ""}><span>${on ? "Shared" : "Not shared"}</span></label>`;
    return `<div class="model${on ? "" : " off"}"><div><div class="mname"><span>${esc(m.name)}</span>${m.loaded ? '<span class="loaded">in memory</span>' : ""}${fit}</div><div class="mmeta">${esc(meta)}</div></div>${right}</div>`;
  }).join("");
  $("#mine-note").textContent = `${lent} of ${o.models.length} shared when you connect`;
  setHTML(box, html);
}

async function setShared(model, on) {
  const cur = (S.settings.unshared || []).filter((m) => normModel(m) !== normModel(model));
  if (!on) cur.push(model);
  try { await api("POST", "/api/settings", { unshared: cur }); }
  catch (e) { toast(e.message, true); }
}

// ---------- downloads ----------
// One download at a time; buttons anywhere can queue more.
const dl = { queue: [], active: null, progress: {} };

function queuePull(tag) {
  tag = String(tag || "").trim();
  if (!tag) return;
  const k = normModel(tag);
  if (dl.active && normModel(dl.active) === k) return;
  if (dl.queue.some((t) => normModel(t) === k)) return;
  if (!S || S.ollama.status !== "running") { toast("Start Ollama first, then download.", true); return; }
  dl.queue.push(tag);
  dl.progress[k] = { pct: 0, text: "Waiting…" };
  if (S) render();
  runPulls();
}

async function runPulls() {
  if (dl.active || !dl.queue.length) return;
  const tag = dl.queue.shift(), k = normModel(tag);
  dl.active = tag;
  dl.progress[k] = { pct: 0, text: "Starting…" };
  render();
  let failed = null, last = 0;
  try {
    const res = await fetch("/api/ollama/pull", { method: "POST", headers: { "X-Chimera": "1", "Content-Type": "application/json" }, body: JSON.stringify({ model: tag }) });
    if (!res.ok) { const j = await res.json().catch(() => ({})); throw new Error(j.error || "Download failed."); }
    await readSSE(res, (ev) => {
      if (ev.type === "progress") {
        const pct = ev.total ? Math.floor((ev.completed / ev.total) * 100) : 0;
        dl.progress[k] = { pct, text: ev.total ? `${pct}% of ${fmtGB(ev.total)}` : ev.status };
        if (Date.now() - last > 150) { last = Date.now(); paintDownloads(); }
      } else if (ev.type === "error") failed = ev.error;
    });
    if (failed) throw new Error(failed);
    toast(`Downloaded ${tag}`);
    if (normModel($("#pull-name").value) === k) $("#pull-name").value = "";
  } catch (e) {
    toast(`${tag}: ${e.message}`, true);
  } finally {
    delete dl.progress[k];
    dl.active = null;
    if (S) render();
    runPulls();
  }
}

// Progress is painted in place (paintDownloads) so lists don't re-render, and
// their buttons don't move under the pointer, on every progress tick.
function downloadButton(tag, label = "Download") {
  const p = dl.progress[normModel(tag)];
  if (p) return `<span class="dl" data-dl="${esc(normModel(tag))}"><span class="dl-text"></span><span class="pull-bar"><span></span></span></span>`;
  const off = !S || S.ollama.status !== "running";
  return `<button class="btn small" data-pull="${esc(tag)}" ${off ? 'disabled title="Ollama isn\'t running"' : ""}>${esc(label)}</button>`;
}

function paintDownloads() {
  $$("[data-dl]").forEach((el) => {
    const p = dl.progress[el.dataset.dl];
    if (!p) return;
    const t = $(".dl-text", el), bar = $(".pull-bar span", el);
    if (t.textContent !== p.text) t.textContent = p.text;
    bar.style.width = `${p.pct}%`;
  });
}

// ---------- models tab ----------
function renderModels() {
  renderFitPanel();
  renderPicks();
  renderCatalog();
  renderInstalled();
  renderTools();
  $("#pull-btn").disabled = S.ollama.status !== "running";
}

function renderFitPanel() {
  const p = S.profile, info = S.device.info || {}, box = $("#fit-panel");
  if (!info.os || !p.usable_gb) { setHTML(box, `<p class="blank">Checking this computer…</p>`); return; }
  const ram = Math.round(info.ram_gb || 0), gpu = (info.gpus || [])[0] || {};
  let where;
  if (info.os === "macOS") where = `${info.chip || "This Mac"} with ${ram} GB of unified memory.`;
  else if (p.accel === "CPU only") where = `No graphics card found, so models run on the processor using ${ram} GB of RAM. Small models only.`;
  else where = `${(gpu.name || "Graphics card").replace(/^NVIDIA GeForce /, "")} with ${Math.round(gpu.vram_gb || 0)} GB of video memory.`;
  const sub = `${where} Models that need up to ${gb(p.comfort_gb)} (with an 8K context) run with room to spare. Past ${gb(p.max_gb)} they spill onto the CPU, slow down and time out.`;
  const best = (p.best_for || []).map((b) => b.toLowerCase());
  const usable = p.usable_gb, pos = (v) => Math.max(0, Math.min(100, (v / usable) * 100));
  const comfortPct = pos(p.comfort_gb), maxPct = pos(p.max_gb);
  const models = S.ollama.models.filter((m) => canChat(m) && m.need_gb).sort((a, b) => a.need_gb - b.need_gb);
  const notches = models.map((m) => `<span class="notch ${esc(m.fits)}" style="left:${pos(m.need_gb)}%" title="${esc(m.name)}: needs about ${gb(m.need_gb)}, ${fitOf(m.fits).word.toLowerCase()}"></span>`).join("");
  // Labels go in up to three lanes so neighbours don't overlap.
  const lanes = [-99, -99, -99];
  const labels = models.map((m) => {
    const x = pos(m.need_gb);
    const lane = lanes.findIndex((end) => x - end > 22);
    if (lane < 0) return "";
    lanes[lane] = x;
    const edge = x < 10 ? " edge-l" : x > 90 ? " edge-r" : "";
    return `<span class="l${lane}${edge}" style="left:${x}%"><b>${esc(m.name)}</b> ${gb(m.need_gb)}</span>`;
  }).join("");
  const limit = S.settings.max_model_gb > 0 ? `<span class="limit" style="left:${pos(S.settings.max_model_gb)}%" title="Your lending limit: ${gb(S.settings.max_model_gb)}"></span>` : "";
  setHTML(box, `<div class="fit-text">
      <h2 class="fit-title">${gb(usable)}<small>for models</small></h2>
      <p class="fit-sub">${esc(sub)}</p>
      ${best.length ? `<p class="fit-best">Best for ${esc(listWords(best))}.</p>` : ""}
    </div>
    <div class="gauge">
      <div class="gauge-track">
        <span class="zone comfort" style="width:${comfortPct}%"></span>
        <span class="zone tight" style="left:${comfortPct}%;width:${maxPct - comfortPct}%"></span>
        <span class="zone over" style="width:${100 - maxPct}%"></span>
        ${limit}${notches}
      </div>
      <div class="gauge-labels">${labels || `<span class="edge-l" style="left:0">No chat models installed yet</span>`}</div>
      <div class="gauge-scale"><span>0</span><span>${gb(usable)}</span></div>
      <div class="gauge-key"><span><i class="comfort"></i>Room to spare</span><span><i class="tight"></i>Tight: works, but slows the computer</span><span><i class="over"></i>Spills onto the CPU</span>${limit ? '<span><i class="limit"></i>Your lending limit</span>' : ""}</div>
    </div>`);
}

function renderPicks() {
  const items = S.catalog.items || [], box = $("#picks");
  const isMac = (S.device.info || {}).os === "macOS";
  setHTML(box, (S.catalog.roles || []).map((r) => {
    const c = items.find((x) => x.tag === r.tag);
    if (!c) {
      const why = r.role === "images" && !isMac ? "Ollama's image models are Mac only for now. On an Nvidia PC, install the comfyui-image Head (Settings → Heads) and the whole pool can use it."
        : r.role === "planner" ? "Planning needs a big model. Long tasks plan on the biggest one in the network."
        : "Nothing in the list fits well here.";
      return `<div class="pick none"><span class="role">${esc(r.name)}</span><span class="pname">${esc(why)}</span></div>`;
    }
    const act = c.installed ? `<span class="have"><span class="led ice"></span>Installed</span>` : downloadButton(c.tag);
    return `<div class="pick"><span class="role">${esc(r.name)}</span><span class="pname" title="${esc(c.blurb)}">${esc(c.label)}<em>${esc(c.tag)}</em></span><span class="psize">${gb(c.size_gb)}</span><span class="pact">${act}</span></div>`;
  }).join(""));
}

const ROLE_WORDS = { planner: "planning", general: "general", coding: "coding", reasoning: "reasoning", vision: "images in", audio: "audio in", fast: "quick replies", embeddings: "search", images: "making images" };

function renderCatalog() {
  const items = S.catalog.items || [], box = $("#catalog");
  const bestTags = new Set((S.catalog.roles || []).map((r) => r.tag).filter(Boolean));
  setHTML(box, items.map((c) => {
    const f = fitOf(c.fit);
    const speed = c.est_tok_s ? `about ${Math.round(c.est_tok_s)} tokens/s here` : "";
    const fitSub = c.fit === "tight" ? "close to the limit" : c.fit === "too_big" ? `needs ${gb(c.need_gb)}` : speed;
    let net = "";
    if (S.network.joined) {
      const n = c.net_devices.length;
      net = n ? `<span title="${esc(c.net_devices.join(", "))}">On ${n === 1 ? esc(c.net_devices[0]) : n + " devices"}</span>` : "Not on the network yet";
      if (c.net_mixed) net += `<span class="warn" title="Devices have different versions of this model. Download it again on each to match.">Versions differ</span>`;
    }
    let act;
    if (c.installed) act = c.net_mixed ? downloadButton(c.tag, "Update") : `<span class="have"><span class="led ice"></span>Installed</span>`;
    else if (c.fit === "unsupported") act = `<span class="fine">${c.no_mac ? "Nvidia/AMD only" : "Mac only"}</span>`;
    else if (c.fit === "too_big") act = `<span class="fine">Too big here</span>`;
    else act = downloadButton(c.tag);
    const roles = listWords((c.roles || []).map((r) => ROLE_WORDS[r] || r));
    const dim = c.fit === "too_big" || c.fit === "unsupported";
    return `<div class="cat${dim ? " dim" : ""}">
      <div class="cname"><b>${esc(c.label)}</b><span class="tag">${esc(c.tag)}</span>${bestTags.has(c.tag) && !dim ? '<span class="best">Recommended</span>' : ""}<p>${esc(c.blurb)}${roles ? ` Good for ${esc(roles)}.` : ""}${c.over_limit ? " Bigger than your lending limit." : ""}</p></div>
      <div class="csize">${gb(c.size_gb)}</div>
      <div class="cfit"><span class="led ${f.led}"></span>${esc(f.word)}${fitSub ? `<small>${esc(fitSub)}</small>` : ""}</div>
      <div class="cnet">${net}</div>
      <div class="cact">${act}</div>
    </div>`;
  }).join(""));
}

const bench = { running: null };
function renderInstalled() {
  const o = S.ollama, box = $("#installed");
  if (o.status !== "running") { $("#installed-note").textContent = ""; setHTML(box, `<p class="blank">Start Ollama to see your models.</p>`); return; }
  if (!o.models.length) { $("#installed-note").textContent = ""; setHTML(box, `<p class="blank">Nothing yet. Download a recommended model.</p>`); return; }
  const total = o.models.reduce((a, m) => a + m.size, 0);
  $("#installed-note").textContent = `${plural(o.models.length, "model")}, ${fmtGB(total)} on disk`;
  setHTML(box, o.models.map((m) => {
    const chatty = canChat(m), f = fitOf(m.fits);
    const bits = [];
    if (chatty) {
      bits.push(`needs about <b>${gb(m.need_gb)}</b>`);
      if (m.ctx_max) bits.push(`up to <b>${ctxWord(m.ctx_max)}</b> context here`);
      if (m.tok_s) bits.push(`<b>${Math.round(m.tok_s)}</b> tokens/s measured`);
      else if (m.est_tok_s) bits.push(`about ${Math.round(m.est_tok_s)} tokens/s (estimate)`);
    } else bits.push(esc(fmtGB(m.size)), "not a chat model");
    const caps = (m.caps || []).filter((c) => !["completion", "tools", "thinking"].includes(c));
    if (caps.length) bits.push(esc(caps.join(", ")));
    const testing = bench.running === m.name;
    const btn = chatty && m.fits !== "too_big"
      ? `<button class="btn small quiet" data-bench="${esc(m.name)}" ${bench.running ? "disabled" : ""}>${testing ? "Testing…" : "Test speed"}</button>` : "";
    return `<div class="inst"><span class="iname">${esc(m.name)}${m.loaded ? ' <span class="loaded">in memory</span>' : ""}</span>
      <span>${chatty ? `<span class="ifit"><span class="led ${f.led}"></span>${esc(f.word)}</span> ` : ""}${btn}</span>
      <span class="imeta">${bits.join(", ")}</span></div>`;
  }).join(""));
}

async function runBench(name) {
  if (bench.running) return;
  bench.running = name;
  renderInstalled();
  try {
    const r = await api("POST", "/api/benchmark", { model: name });
    toast(`${name}: ${r.tok_s} tokens per second on this computer`);
  } catch (e) { toast(e.message, true); }
  bench.running = null;
  if (S) renderInstalled();
}

function renderTools() {
  const tools = (S.profile && S.profile.tools) || [], box = $("#tools");
  setHTML(box, tools.map((t) => {
    let sub = t.have ? (t.via ? `Using ${t.via}` : "Ready") : (t.note || "Not found on this computer");
    if (t.id === "comfyui" && t.note) sub = `Running. Can make ${t.note}.`;
    let tag = "";
    if (!t.lendable && t.id === "computer_use") tag = `<span class="tagline never" title="${esc(t.note || "")}">Never lent</span>`;
    else if (!t.lendable && t.id === "python") tag = `<span class="tagline">Library tests</span>`;
    else if (!t.have && t.get_url) tag = `<a class="btn small quiet" href="${esc(t.get_url)}" target="_blank" rel="noopener">Get it</a>`;
    if (t.id === "computer_use") sub = t.have ? `Possible with ${t.via}, but only for you: a friend's job never controls your computer.` : (t.note || "");
    return `<div class="tool"><span class="led ${t.have ? "ice" : "off"}"></span><div><b>${esc(t.name)}</b><p>${esc(sub)}</p></div>${tag}</div>`;
  }).join("") || `<p class="blank">Checking…</p>`);
}

// ---------- activity ----------
function renderActivity() {
  const n = S.network;
  if (!n.joined) {
    setHTML($("#ledger"), `<li class="blank">Join a network to see what it's been doing.</li>`);
    setHTML($("#balances"), `<p class="blank">No credits yet.</p>`);
    return;
  }
  const rows = n.recent.map((r) => {
    const asker = r.requester === "network" ? "The network" : esc(r.requester);
    const who = r.status === "failed"
      ? `<b>${asker}</b>${r.requester === "network" ? "'s library job" : "'s request"} <span class="bad">didn't finish</span>`
      : r.requester === "network"
        ? `<b>The library</b> used ${esc(r.worker)}'s <b>${esc(r.worker_device || "device")}</b>`
        : `<b>${asker}</b> used ${r.worker && !sameOwner(r.worker, r.requester) ? `${esc(r.worker)}'s ` : "their "}<b>${esc(r.worker_device || "device")}</b>`;
    const bits = [r.purpose, r.model, r.tokens ? `${fmtNum(r.tokens)} tokens` : "", r.tok_s ? `${r.tok_s} per second` : "", r.wait_s >= 5 ? `waited ${Math.round(r.wait_s)}s` : "", r.status === "cancelled" ? "stopped early" : ""].filter(Boolean);
    const detail = esc(bits.join(", ")) + (r.error ? `. <span class="bad">${esc(r.error)}</span>` : "");
    let amt = `<span class="amt free">0</span>`;
    if (r.free) amt = `<span class="amt free">free</span>`;
    else if (r.credits && sameOwner(r.worker, S.device.owner)) amt = `<span class="amt plus" title="You earned this">+${fmtCredits(r.credits)}</span>`;
    else if (r.credits && sameOwner(r.requester, S.device.owner)) amt = `<span class="amt" title="You spent this">−${fmtCredits(r.credits)}</span>`;
    else if (r.credits) amt = `<span class="amt">${fmtCredits(r.credits)}</span>`;
    return `<li><span class="what">${who}</span>${amt}<span class="detail">${detail}</span><span class="when">${ago(r.at)}</span></li>`;
  }).join("");
  setHTML($("#ledger"), rows || `<li class="blank">Nothing yet. Send a prompt from Chat to try the network.</li>`);
  const entries = Object.entries(n.balances).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, v]) => Math.abs(v)));
  setHTML($("#balances"), entries.map(([name, v]) =>
    `<div class="bal${sameOwner(name, S.device.owner) ? " me" : ""}"><span class="bname" title="${esc(name)}">${esc(name)}</span><div class="track"><div class="fill" style="width:${Math.max(2, (Math.max(0, v) / max) * 100)}%"></div></div><span class="bnum">${fmtCredits(v)}</span></div>`).join("") || `<p class="blank">No credits yet.</p>`);
}

// ---------- settings ----------
function renderSettings() {
  const set = S.settings;
  renderNetworkSettings();
  renderLibrarySettings();
  $$("[data-setting]").forEach((el) => {
    if (document.activeElement === el) return;
    const v = set[el.dataset.setting];
    if (el.type === "checkbox") el.checked = !!v;
    else if (String(el.value) !== String(v ?? "")) el.value = v ?? "";
  });
  const owner = $('[data-setting="owner"]');
  owner.disabled = S.network.joined;
  $("#owner-hint").textContent = S.network.joined
    ? "Your name is tied to your credits in this network. Leave the network to change it."
    : "Friends see this next to your credits.";
  $("#data-dir").textContent = S.data_dir;
  $("#version").textContent = `Chimera ${S.version}`;
  const idle = $("[data-netsetting]");
  if (idle && document.activeElement !== idle && String(idle.value) !== String(S.network.verify_idle_min || "")) idle.value = S.network.verify_idle_min || "";
}

function renderLibrarySettings() {
  const n = S.network, box = $("#settings-library");
  let html = `<h2 class="section-title">Library</h2>`;
  if (!n.joined) {
    html += `<p class="fine">Join a network to share what works. Replies you rate 4 or 5 stars become reusable code, Blender scripts and lessons for everyone's long tasks.</p>`;
  } else if (n.admin) {
    const st = n.library || {};
    html += `<p class="fine">This computer hosts the network, so it reviews the library. ${plural(st.total || 0, "entry", "entries")}: ${st.verified || 0} verified, ${st.unverified || 0} being checked, ${st.flagged || 0} flagged.</p>
      <label class="row toggle"><span>Test library scripts on this computer</span><input type="checkbox" data-setting="run_tests" ${(S.profile&&S.profile.can_test)?"":"disabled"}></label>
      <p class="fine">When this computer is lending and idle, it test-runs Python and Blender scripts from the library to make sure they work. Each one runs in a sandbox with no network, your home folder hidden and writes allowed only in a throwaway folder; anything that deletes files, reaches the network or starts other programs is refused before it runs.${(S.profile&&S.profile.can_test)?"":" This computer can&#39;t make that sandbox (it needs macOS, or bwrap on Linux), so test runs stay off and entries wait for a computer that can."}</p>`;
  } else {
    html += `<p class="fine">${esc(n.host || "The host")} hosts this network and reviews the library on the hosting computer. Rate replies 4 or 5 stars and say what worked to add to it.</p>`;
  }
  const plugins = (S.profile && S.profile.plugins) || [], made = S.made_heads || [];
  html += `<h2 class="section-title spaced">Heads</h2>
    <label class="row toggle"><span>Let the pool use my Heads</span><input type="checkbox" data-setting="lend_plugins"></label>
    <p class="fine">A Head is a tool installed on this computer that the whole pool can call — Perspective's studio shadows, an image generator in ComfyUI, a 3D-mesh maker. <b>Make a Head</b> turns a program or a server on this computer into one, no code needed; or drop a Head's folder (it has a <code>plugin.json</code>) into Chimera's heads folder. It shows up here when it can run. When someone asks for what a Head makes — with a picture, or just in words — it runs here in a sandbox: no internet (a Head may talk to a server on this computer if it says so), your home folder hidden except the Head's own folders. Their star ratings decide which Head the pool picks when several could do a job, and you earn bonus credits every time your Head does a job for someone else, plus more when they rate it 4 or 5 stars.</p>
    ${plugins.length ? `<ul class="plugin-list">${plugins.map((p) => `<li><span class="led ${p.have ? "ice" : "off"}"></span><span class="grow"><b>${esc(p.name)}</b> ${esc(p.version || "")}<span class="detail">${esc(p.have ? p.summary : "Can't run here: " + (p.note || ""))}</span></span><span class="head-btns">${made.includes(p.id) ? `<button class="btn small quiet" data-head-edit="${esc(p.id)}">Change</button>` : ""}<button class="btn small quiet" data-head-try="${esc(p.id)}">Try</button></span></li>`).join("")}</ul>` : `<p class="fine">No Heads installed yet.</p>`}
    ${(S.profile && S.profile.can_test === false) ? `<label class="row toggle"><span>Run Heads without a sandbox on this computer</span><input type="checkbox" data-setting="unsandboxed_heads" ${S.settings.unsandboxed_heads ? "checked" : ""}></label>
    <p class="fine warn">This computer (Windows) has no sandbox Chimera trusts, so Heads are off here unless you allow this. With it on, a Head runs with your normal permissions — only install Heads you trust, from people you trust. The Head's code is always yours, installed by hand; what arrives from the pool is just the picture or words it works on.</p>` : ""}
    <div class="btn-row"><button class="btn" data-act="make-head">Make a Head</button><button class="btn" data-act="open-plugins">Open heads folder</button></div>`;
  setHTML(box, html);
}

function renderNetworkSettings() {
  const h = S.hosting, n = S.network, box = $("#settings-network");
  let html = `<h2 class="section-title">Network</h2>`;
  if (h.enabled) {
    html += `<p class="fine">You're hosting ${esc(h.name)}. Keep Chimera open on this computer so friends can stay connected.</p>
      <label class="row toggle"><span>Let anyone join this pool (open pool)</span><input type="checkbox" data-setting="auto_join" ${S.settings.auto_join ? "checked" : ""}></label>
      <p class="fine">Anyone who can reach this hub — on your Wi-Fi, or from any network via the Pool address below — joins with no code typed. Credits, not codes, keep people contributing: out of credits, they can't use others' GPUs. Turn off to require the invite code instead${S.settings.auto_join ? "" : " (off now)"}.</p>
      <dl class="kv"><dt>Invite code</dt><dd><button class="copy code" data-copy="${esc(h.invite)}">${esc(h.invite)}</button></dd>
      <dt>Port</dt><dd>${h.port}</dd>
      <dt>Addresses</dt><dd>${(h.addresses || []).map((a) => `${esc(a.ip)}:${h.port} (${esc(a.label)})`).join("<br>") || "None found"}</dd></dl>
      <div class="btn-row"><button class="btn" data-act="new-invite">New invite code</button><button class="btn danger" data-act="stop-hosting">Stop hosting</button></div>`;
  } else if (n.joined) {
    html += `<dl class="kv"><dt>Network</dt><dd>${esc(n.name || "Unnamed")}</dd><dt>Hub</dt><dd class="mono">${esc(n.address)}</dd>
      <dt>Status</dt><dd>${n.ok ? "Connected" : `<span style="color:var(--brick)">${esc(n.error || "Can't reach the hub")}</span>`}</dd></dl>
      <div class="btn-row"><button class="btn" data-act="join">Join a different network</button><button class="btn danger" data-act="leave">Leave network</button></div>`;
  } else {
    html += `<p class="fine">Not in a network.</p><div class="btn-row"><button class="btn primary" data-act="host">Host a network</button><button class="btn" data-act="join">Join a network</button></div>`;
    if (h.error) html += `<p class="fine" style="color:var(--brick)">${esc(h.error)}</p>`;
  }
  // Pool address: a hub every device joins on its own, from any network.
  html += `<label class="row stack" style="margin-top:16px"><span>Pool address</span><input class="field mono" data-setting="pool_addr" value="${esc(S.settings.pool_addr || "")}" placeholder="e.g. 100.x.x.x:7480 (the Studio over Tailscale)" spellcheck="false"></label>
    <p class="fine">A hub every device joins automatically when Chimera opens, from any network. Point it at one always-on host (your Studio over Tailscale works from anywhere). Leave blank to just use the local Wi-Fi.</p>`;
  setHTML(box, html);
}

async function saveSetting(el) {
  const key = el.dataset.setting;
  let v = el.type === "checkbox" ? el.checked : el.value;
  if (el.dataset.type === "int") v = parseInt(v, 10) || 1;
  if (el.dataset.type === "float") v = Math.max(0, parseFloat(v) || 0);
  try {
    await api("POST", "/api/settings", { [key]: v });
    toast("Saved");
  } catch (e) {
    toast(e.message, true);
    if (S) renderSettings();
  }
}

// ---------- setup and joining ----------
let setupStep = null;   // null means not shown yet this session
function renderSetupGate() {
  const needs = !S.settings.setup_done && !S.network.joined && !S.hosting.enabled;
  if (needs && setupStep === null) openSetup("first");
  const o = S.ollama;
  let line = "";
  if (o.status === "running") line = `<span class="led ice"></span><span>Ollama is running with ${plural(o.models.length, "model")}.</span>`;
  else if (o.status === "missing") line = `<span class="led brick"></span><span>Ollama isn't installed. You'll need it to lend your GPU.</span><a class="btn small" href="https://ollama.com/download" target="_blank" rel="noopener">Get Ollama</a>`;
  else if (o.status === "starting") line = `<span class="led amber pulse"></span><span>Opening Ollama…</span>`;
  else line = `<span class="led brick"></span><span>Ollama isn't running. You'll need it to lend your GPU.</span><button class="btn small" data-act="open-ollama">Open Ollama</button>`;
  setHTML($("#su-ollama"), line);
}

function openSetup(step) {
  setupStep = step;
  $("#setup").hidden = false;
  $("#setup-step-1").hidden = step !== "first";
  $("#setup-join").hidden = step !== "join";
  $("#setup-hosted").hidden = step !== "hosted";
  $("#su-error").textContent = "";
  $("#su-join-error").textContent = "";
  if (S) {
    if (!$("#su-owner").value) $("#su-owner").value = S.settings.owner || "";
    if (!$("#su-device").value) $("#su-device").value = S.settings.device_name || "";
  }
  const focus = step === "first" ? ($("#su-owner").value ? $("#su-host") : $("#su-owner")) : step === "join" ? $("#su-address") : $("#su-done");
  setTimeout(() => focus.focus(), 30);
  if (step === "join") scanNetworks();
}

// ---------- LAN discovery ----------
async function scanNetworks() {
  const box = $("#su-found");
  if (!box) return;
  box.innerHTML = `<p class="found-head">Looking for networks on your Wi-Fi…</p>`;
  let nets = [];
  try { nets = (await api("GET", "/api/discover")).networks || []; } catch { /* ignore */ }
  if (!nets.length) { box.innerHTML = `<p class="found-head">No networks found on your Wi-Fi yet. <button class="link" data-act="rescan">Look again</button></p>`; return; }
  box.innerHTML = `<p class="found-head">On your Wi-Fi:</p>` + nets.map((n, i) =>
    `<button class="found-net" data-found="${i}"><span class="fn-name">${esc(n.name || "Chimera network")}</span><span class="fn-sub">${esc(n.address)}${n.auto_join ? " · joins automatically" : " · needs invite code"}</span></button>`).join("");
  scanNetworks._nets = nets;
}

async function joinFound(i) {
  const n = (scanNetworks._nets || [])[i];
  if (!n) return;
  const names = namesOrError($("#su-join-error"));
  if (!names) { openSetup("first"); $("#su-error").textContent = $("#su-join-error").textContent; return; }
  if (n.auto_join && n.invite) {
    const err = $("#su-join-error"); err.textContent = "";
    try {
      await api("POST", "/api/network/join", { address: n.address, invite: n.invite, owner: names.owner, device_name: names.device });
      await api("POST", "/api/settings", { setup_done: true });
      closeSetup(); toast(`Joined ${n.name}. Press Connect to start lending.`); setView("network");
    } catch (e) { err.textContent = e.message; }
  } else {
    $("#su-address").value = n.address;
    $("#su-invite").focus();
  }
}
function closeSetup() {
  setupStep = "closed";
  $("#setup").hidden = true;
}
function namesOrError(errEl) {
  const owner = $("#su-owner").value.trim(), device = $("#su-device").value.trim();
  if (!owner) { errEl.textContent = "Enter your name first. It's how friends see your credits."; $("#su-owner").focus(); return null; }
  if (!device) { errEl.textContent = "Give this computer a name."; $("#su-device").focus(); return null; }
  return { owner, device };
}

async function hostNetwork() {
  const names = namesOrError($("#su-error"));
  if (!names) return;
  $("#su-host").disabled = true;
  try {
    const h = await api("POST", "/api/network/host", { enabled: true, owner: names.owner, device_name: names.device });
    await api("POST", "/api/settings", { setup_done: true });
    const addrs = (h.addresses || []).map((a) => `<button class="copy" data-copy="${esc(a.ip)}:${h.port}">${esc(a.ip)}:${h.port} <small>${esc(a.label)}</small></button>`).join(" ");
    setHTML($("#su-hosted-details"), `<dl class="kv"><dt>Address</dt><dd>${addrs || "No address found"}</dd><dt>Invite code</dt><dd><button class="copy code" data-copy="${esc(h.invite)}">${esc(h.invite)}</button></dd></dl>
      <p class="fine">Same Wi-Fi: use the local network address. Different houses: install Tailscale on both computers and use the Tailscale address.</p>`);
    openSetup("hosted");
  } catch (e) {
    $("#su-error").textContent = e.message;
  } finally {
    $("#su-host").disabled = false;
  }
}

async function joinNetwork() {
  const err = $("#su-join-error");
  const names = namesOrError(err);
  if (!names) { openSetup("first"); $("#su-error").textContent = err.textContent; return; }
  const address = $("#su-address").value.trim(), invite = $("#su-invite").value.trim();
  if (!address) { err.textContent = "Enter the host's address."; return; }
  if (!invite) { err.textContent = "Enter the invite code."; return; }
  const btn = $("#su-join-go");
  btn.disabled = true; btn.textContent = "Joining…"; err.textContent = "";
  try {
    await api("POST", "/api/network/join", { address, invite, owner: names.owner, device_name: names.device });
    await api("POST", "/api/settings", { setup_done: true });
    closeSetup();
    toast("Joined the network. Press Connect to start lending.");
    setView("network");
  } catch (e) {
    err.textContent = e.message;
  } finally {
    btn.disabled = false; btn.textContent = "Join";
  }
}

// ---------- chat ----------
const chat = { sessions: [], current: null, busy: null, count: 0, images: [] };

// ---------- pictures (for plugins) ----------
const IMAGE_MAX = 25 * 1024 * 1024;
function fileURL(f, m) {
  return f.url || `/api/files/${encodeURIComponent((m && m._session) || chat.current || "")}/${encodeURIComponent(f.id)}`;
}
function isImage(f) { return !f.mime || /^image\//.test(f.mime); }
function filesHTML(m) {
  const fs = (m._previews || []).concat(m.files || []);
  if (!fs.length) return "";
  const mine = m.role === "user";
  return `<div class="files${mine ? " sent" : ""}">${fs.map((f) => {
    const u = fileURL(f, m), dims = f.width && f.height ? `${f.width} × ${f.height}` : "";
    if (!isImage(f)) return `<a class="file-link" href="${esc(u)}" download="${esc(f.name)}">${esc(f.name)}</a>`;
    return `<figure><a href="${esc(u)}" target="_blank" rel="noopener"><img src="${esc(u)}" alt="${esc(f.name)}" loading="lazy"></a>
      ${mine ? "" : `<figcaption><span>${esc(f.name)}${dims ? ` · ${dims}` : ""}</span><a class="btn small quiet" href="${esc(u)}" download="${esc(f.name)}">Save</a></figcaption>`}</figure>`;
  }).join("")}</div>`;
}
function addImageFile(file) {
  if (!file) return;
  if (!/^image\/(png|jpeg|webp)$/.test(file.type)) { toast("Add a PNG, JPEG or WebP picture.", true); return; }
  if (file.size > IMAGE_MAX) { toast("Pictures can be up to 25 MB.", true); return; }
  const rd = new FileReader();
  rd.onload = () => {
    const data = String(rd.result).split(",")[1] || "";
    chat.images.forEach((i) => URL.revokeObjectURL(i.url));
    chat.images = [{ name: file.name || "picture.png", data, url: URL.createObjectURL(file), size: file.size }];
    renderAttachments();
    $("#prompt").focus();
  };
  rd.onerror = () => toast("Couldn't read that picture.", true);
  rd.readAsDataURL(file);
}
function renderAttachments() {
  const box = $("#attachments");
  box.hidden = !chat.images.length;
  setHTML(box, chat.images.map((i, n) => `<span class="attachment"><img src="${esc(i.url)}" alt=""><span>${esc(i.name)}</span>
    <button class="link small" type="button" data-act="remove-attachment" data-n="${n}" aria-label="Remove ${esc(i.name)}">×</button></span>`).join(""));
  $("#prompt").placeholder = chat.images.length ? "What should a Head do with this picture? (e.g. add a soft studio shadow)" : "Ask something…";
}

function md(src) {
  const parts = String(src || "").split("```");
  return parts.map((part, i) => {
    if (i % 2 === 1) {
      const nl = part.indexOf("\n");
      const code = nl >= 0 ? part.slice(nl + 1) : part;
      return `<pre><code>${esc(code.replace(/\n$/, ""))}</code></pre>`;
    }
    return mdBlocks(part);
  }).join("");
}
function mdInline(t) {
  t = esc(t);
  t = t.replace(/`([^`]+)`/g, "<code>$1</code>");
  t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  t = t.replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<em>$2</em>");
  t = t.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return t;
}
function mdBlocks(text) {
  const lines = text.split("\n");
  let out = "", list = null, para = [];
  const flushPara = () => { if (para.length) { out += `<p>${mdInline(para.join("\n")).replace(/\n/g, "<br>")}</p>`; para = []; } };
  const flushList = () => { if (list) { out += `<${list.t}>${list.items.map((x) => `<li>${mdInline(x)}</li>`).join("")}</${list.t}>`; list = null; } };
  for (const line of lines) {
    let m;
    if (!line.trim()) { flushPara(); flushList(); continue; }
    if ((m = line.match(/^#{1,6}\s+(.*)/))) { flushPara(); flushList(); out += `<h4>${mdInline(m[1])}</h4>`; continue; }
    if ((m = line.match(/^\s*[-*+]\s+(.*)/))) { flushPara(); if (!list || list.t !== "ul") { flushList(); list = { t: "ul", items: [] }; } list.items.push(m[1]); continue; }
    if ((m = line.match(/^\s*\d+[.)]\s+(.*)/))) { flushPara(); if (!list || list.t !== "ol") { flushList(); list = { t: "ol", items: [] }; } list.items.push(m[1]); continue; }
    if (list && /^\s{2,}\S/.test(line)) { list.items[list.items.length - 1] += " " + line.trim(); continue; }
    flushList();
    para.push(line);
  }
  flushPara(); flushList();
  return out;
}

function metaText(m) {
  if (m.status === "error") return "";
  const bits = [];
  if (m.device) {
    bits.push(m.local ? `Ran here with ${m.model}` : `Ran on ${deviceLabel(m.device, m.owner)} with ${m.model}`);
  }
  if (m.tokens) bits.push(`${fmtNum(m.tokens)} tokens${m.tok_s ? ` at ${m.tok_s} per second` : ""}`);
  if (m.status === "cancelled") bits.push("Stopped early");
  if (m.local) bits.push("Not through the network");
  else if (m.free) bits.push("Free, your own device");
  else if (m.credits) bits.push(`${fmtCredits(m.credits)} credits`);
  return bits.length ? bits.join(". ") + "." : "";
}

function messageEl(m, idx) {
  const el = document.createElement("div");
  el.className = `msg ${m.role}${m.task ? " task" : ""}`;
  if (idx !== undefined) el.dataset.index = idx;
  if (m.role === "user") {
    el.textContent = m.content;
    const files = filesHTML(m);
    if (files) el.insertAdjacentHTML("beforeend", files);
    return el;
  }
  el._m = m;
  el.innerHTML = `<div class="note" hidden></div><div class="plan" hidden></div><details hidden><summary>Thinking</summary><div></div></details><div class="body"></div><div class="meta"></div><div class="rate-wrap"></div>`;
  if (m.task) fillTask(el, m); else fillAssistant(el, m);
  return el;
}

function setNote(el, text) {
  const n = $(".note", el);
  n.hidden = !text;
  n.textContent = text || "";
}

function fillAssistant(el, m) {
  const body = $(".body", el), meta = $(".meta", el), det = $("details", el);
  setNote(el, m.note);
  if (m.thinking) { det.hidden = false; $("div", det).textContent = m.thinking; } else det.hidden = true;
  if (m.status === "error") {
    body.innerHTML = m.content ? md(m.content) : "";
    meta.innerHTML = `<span class="err">${esc(m.error || "Something went wrong.")}</span>`;
    fillRate(el, m);
    return;
  }
  let html = md(m.content);
  if (m.status === "pending" && !m.plugin) {
    const caret = '<span class="caret"></span>';
    html = html.endsWith("</p>") ? html.slice(0, -4) + caret + "</p>" : html + caret;
  }
  if (m.status === "pending" && m.plugin) {
    const pct = Math.round((m._fraction || 0) * 100);
    html += `<div class="plugin-progress"><span style="width:${pct}%"></span></div>`;
  }
  body.innerHTML = html + filesHTML(m);
  meta.textContent = m.status === "pending" ? (m._runner || "Sending…") : metaText(m);
  fillRate(el, m);
}

// ---------- long tasks (Hydra) ----------
const openSteps = new Set();

function phaseText(t, pending) {
  const steps = t.steps || [];
  const done = steps.filter((s) => s.status === "done" || s.status === "library").length;
  // Round prefix only in iterate-until-done mode (rounds > 1).
  const rp = t.rounds > 1 && t.round && t.phase !== "done" ? `Round ${t.round}/${t.rounds} · ` : "";
  switch (t.phase) {
    case "planning":
      return rp + (t.planner_model ? `Planning on ${deviceLabel(t.planner_device, t.planner_owner)} with ${t.planner_model}…` : "Finding the biggest model to plan with…");
    case "working": return rp + `Working: ${done} of ${plural(steps.length, "step")} done`;
    case "combining": return rp + (t.synth_model ? `Combining on ${deviceLabel(t.synth_device, t.synth_owner)} with ${t.synth_model}…` : "Combining the steps…");
    case "reviewing": return rp + "Reviewing the result…";
    case "done": {
      const devs = new Set(steps.filter((s) => s.device).map((s) => s.device));
      const r = t.rounds > 1 && t.round ? `${plural(t.round, "round")}, ` : "";
      return `Done: ${r}${plural(steps.length, "step")}${devs.size > 1 ? ` on ${devs.size} computers` : ""}`;
    }
    case "cancelled": return "Stopped";
    case "error": return t.error || "Didn't finish";
  }
  return pending ? "Starting…" : "";
}

function stepSub(s) {
  if (s.status === "library") return `<span class="ssub lib">Reused from the library: ${esc(s.from_library)}. No model needed.</span>`;
  if (s.status === "failed" && s.error === "cancelled") return `<span class="ssub">Stopped</span>`;
  if (s.status === "failed") return `<span class="ssub bad">${esc(s.error || "Didn't finish")}</span>`;
  const where = s.device ? (s.local ? `Here with ${esc(s.model)}` : `On ${esc(deviceLabel(s.device, s.owner))} with ${esc(s.model)}`) : "";
  if (s.status === "running") return `<span class="ssub">${where ? where + ", writing…" : "Waiting for a free device…"}</span>`;
  if (s.status === "done") return `<span class="ssub">${where}${s.tokens ? `, ${fmtNum(s.tokens)} tokens` : ""}${s.free ? ", free" : s.credits ? `, ${fmtCredits(s.credits)} credits` : ""}</span>`;
  const deps = (s.depends_on || []).length ? `After step ${s.depends_on.map((d) => d.replace(/^s/, "")).join(" and ")}` : "Waiting";
  return `<span class="ssub">${esc(deps)}</span>`;
}

function fillTask(el, m) {
  const t = m.task || {}, plan = $(".plan", el), body = $(".body", el), meta = $(".meta", el);
  const pending = m.status === "pending";
  setNote(el, m.note);
  const steps = t.steps || [];
  const led = { waiting: "off", running: "ice pulse", done: "ice", library: "ice", failed: "brick" };
  const key = (s) => `${m.task_id || t.started}:${s.id}`;
  const stepsHTML = steps.map((s) => {
    const open = openSteps.has(key(s)) && s.output;
    const l = s.status === "failed" && s.error === "cancelled" ? "off" : led[s.status] || "off";
    return `<li><span class="led ${l}"></span><div><b>${esc(s.title)}</b>${stepSub(s)}</div>
      ${s.output ? `<button class="link small" data-step="${esc(key(s))}">${open ? "Hide" : "Show"}</button>` : "<span></span>"}
      ${open ? `<div class="sout">${md(s.output)}</div>` : ""}</li>`;
  }).join("");
  const phase = phaseText(t, pending);
  const bad = t.phase === "error";
  const foot = t.phase === "planning" ? [] : [t.planner_model ? `Planned on ${deviceLabel(t.planner_device, t.planner_owner)} with ${t.planner_model}` : "",
    t.synth_model ? `combined on ${deviceLabel(t.synth_device, t.synth_owner)} with ${t.synth_model}` : "",
    (t.refs || []).length ? `used ${plural(t.refs.length, "library entry", "library entries")} as references` : ""].filter(Boolean);
  plan.hidden = false;
  setHTML(plan, `<div class="plan-head">${pending ? '<span class="led ice pulse"></span>' : ""}<span class="plan-title">${esc(t.title || "Long task")}</span><span class="plan-phase${bad ? " bad" : ""}">${esc(phase)}</span></div>
    ${t.summary ? `<p class="plan-summary">${esc(t.summary)}</p>` : ""}
    ${steps.length ? `<ol class="steps">${stepsHTML}</ol>` : ""}
    ${foot.length ? `<p class="plan-foot">${esc(foot.join(", ").replace(/^./, (c) => c.toUpperCase()))}.</p>` : ""}`);
  let html = md(m.content);
  if (pending && t.phase === "combining") {
    const caret = '<span class="caret"></span>';
    html = html.endsWith("</p>") ? html.slice(0, -4) + caret + "</p>" : html + caret;
  }
  body.innerHTML = html;
  if (m.status === "error") meta.innerHTML = `<span class="err">${esc(m.error || t.error || "The task didn't finish.")}</span>`;
  else if (pending) meta.textContent = "";
  else {
    const bits = [t.tokens || m.tokens ? `${fmtNum(t.tokens || m.tokens)} tokens in all` : "", m.status === "cancelled" ? "Stopped early" : "",
      (t.credits || m.credits) ? `${fmtCredits(t.credits || m.credits)} credits` : "Free"];
    meta.textContent = bits.filter(Boolean).join(". ") + ".";
  }
  fillRate(el, m);
}

// ---------- ratings ----------
function fillRate(el, m) {
  const box = $(".rate-wrap", el);
  if (!box) return;
  const idx = el.dataset.index;
  const finished = !m.status && (m.content || "").trim();
  if (!finished || idx === undefined || !chat.current) { setHTML(box, ""); return; }
  const r = m.rating || 0;
  const stars = [1, 2, 3, 4, 5].map((n) => `<button class="star${n <= r ? " on" : ""}" data-star="${n}" aria-label="${plural(n, "star")}" title="${plural(n, "star")}">${STAR}</button>`).join("");
  let after = "";
  const askNote = r >= 4 && !m.rating_sent && !m._noteDone && S && S.network.joined;
  if (m._rateMsg) after = `<span class="rdone">${esc(m._rateMsg)}</span>`;
  else if (m.rating_sent && m.plugin) after = `<span class="rdone">Counted toward the Head's rating</span>`;
  else if (m.rating_sent && r >= 4) after = `<span class="rdone">Shared with the library</span>`;
  else if (r) after = `<span class="rdone">Rated</span>`;
  let note = "";
  if (askNote) note = `<form class="rate-note" data-rate-note><input class="field" name="note" placeholder="${m.plugin ? "What worked well? The Head's owner sees it." : "What worked well? It helps the network reuse it."}" maxlength="2000"><button class="btn small" type="submit">Send</button><button class="btn small quiet" type="button" data-rate-skip>Skip</button></form>`;
  setHTML(box, `<div class="rate"><span class="rlabel">${r ? "Your rating" : "Rate this reply"}</span>${stars}${askNote ? "" : after}</div>${note}`);
}

async function rateMessage(el, n) {
  const m = el._m, idx = Number(el.dataset.index);
  if (!m || !chat.current) return;
  m.rating = n; m._rateMsg = ""; m._noteDone = false;
  fillRate(el, m);
  const f = $(".rate-note input", el);
  if (f) f.focus();
  try {
    const r = await api("POST", "/api/feedback", { session_id: chat.current, index: idx, rating: n, send: n <= 3 });
    if (n <= 3) { m.rating_sent = !!r.sent; m._rateMsg = "Thanks for rating"; fillRate(el, m); }
    else if (!r.joined) { m._rateMsg = "Saved. Join a network to share what works."; fillRate(el, m); }
  } catch (e) { toast(e.message, true); }
}

async function sendRateNote(el, note) {
  const m = el._m, idx = Number(el.dataset.index);
  m._noteDone = true;
  m._rateMsg = "Sending…";
  fillRate(el, m);
  try {
    const r = await api("POST", "/api/feedback", { session_id: chat.current, index: idx, rating: m.rating, note, send: true });
    m.rating_note = note; m.rating_sent = !!r.sent;
    m._rateMsg = r.queued ? "Thanks. The network's biggest model will save what worked to the library."
      : r.sent && m.plugin ? "Thanks. It counts toward the Head's rating." : r.sent ? "Thanks for rating" : (r.error || "Saved");
  } catch (e) { m._rateMsg = ""; m._noteDone = false; toast(e.message, true); }
  fillRate(el, m);
}

function renderMessages(sess) {
  const box = $("#messages");
  box.innerHTML = "";
  chat.count = sess ? sess.messages.length : 0;
  if (!sess || !sess.messages.length) {
    box.innerHTML = `<div class="chat-empty"><h2 class="section-title">Test the network</h2><p>Send a prompt and Chimera runs it on a device that's lending, maybe a friend's. Each reply says which computer and model wrote it. Turn on Long task for bigger jobs: Hydra splits them into steps that run on several computers at once.</p></div>`;
    return;
  }
  sess.messages.forEach((m, i) => { m._session = sess.id; box.appendChild(messageEl(m, i)); });
  box.scrollTop = box.scrollHeight;
}

function painter(el, m, fill) {
  let raf = 0;
  const box = $("#messages");
  return () => {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
      fill(el, m);
      if (nearBottom) box.scrollTop = box.scrollHeight;
    });
  };
}

// A reply being written live.
function liveMessage(el) {
  const m = el._m || { role: "assistant", content: "", thinking: "", status: "pending" };
  el._m = m;
  m.content = m.content || ""; m.thinking = m.thinking || ""; m.status = "pending";
  const schedule = painter(el, m, fillAssistant);
  return {
    on(ev) {
      switch (ev.type) {
        case "started": chat.busy = { kind: "gen", id: ev.gen_id }; if (!chat.current) chat.current = ev.session_id; m._session = ev.session_id; m.content = ""; m.thinking = ""; break;
        case "note": m.note = ev.reason; break;
        case "queued": m._runner = m.plugin ? "Waiting for a computer with that Head…" : "Waiting for a free device…"; break;
        case "plugin": m.plugin = ev.plugin; m.model = ev.model; m._runner = `Using ${ev.model}…`; break;
        case "assigned":
          m.device = ev.device_name; m.owner = ev.owner; m.model = ev.model; m.local = ev.local;
          if (m.plugin) m._runner = ev.local ? `Running ${ev.model} here…` : `Running ${ev.model} on ${deviceLabel(ev.device_name, ev.owner)}…`;
          else m._runner = ev.local ? `Writing here with ${ev.model}…` : `Writing on ${deviceLabel(ev.device_name, ev.owner)} with ${ev.model}…`;
          break;
        case "status": {
          m._fraction = ev.fraction || 0;
          const where = m.device ? (m.local ? "Here" : `On ${deviceLabel(m.device, m.owner)}`) : "";
          m._runner = `${where ? where + ": " : ""}${ev.reason || "Working"}${ev.fraction ? ` (${Math.round(ev.fraction * 100)}%)` : ""}`;
          break;
        }
        case "file": if (ev.file) m.files = (m.files || []).concat([ev.file]); break;
        case "delta": m.content += ev.content || ""; m.thinking += ev.thinking || ""; break;
        case "replay": m.content = ev.content || ""; m.thinking = ev.thinking || ""; break;
        case "requeued": m.content = ""; m.thinking = ""; m.note = `Moved to another device: ${ev.reason}`; m._runner = "Finding another device…"; break;
        case "done": case "cancelled":
          m.status = ev.type === "cancelled" ? "cancelled" : "";
          Object.assign(m, { tokens: ev.tokens, tok_s: ev.tok_s, credits: ev.credits, free: ev.free });
          if (ev.local) m.local = true;
          break;
        case "error": m.status = "error"; m.error = ev.error; break;
      }
      schedule();
    },
    fail(msg) { m.status = "error"; m.error = msg; schedule(); },
  };
}

// A long task being worked on live.
function liveTask(el) {
  const m = el._m || { role: "assistant", content: "", status: "pending", task: { phase: "planning", steps: [] } };
  el._m = m;
  m.status = "pending"; m.content = m.content || "";
  el.classList.add("task");
  const schedule = painter(el, m, fillTask);
  return {
    on(ev) {
      switch (ev.type) {
        case "started": chat.busy = { kind: "task", id: ev.task_id }; m.task_id = ev.task_id; if (!chat.current) chat.current = ev.session_id; break;
        case "task": m.task = ev.task; break;
        case "delta": m.content += ev.content || ""; break;
        case "replay": m.content = ev.content || ""; break;
        case "done": m.task = ev.task || m.task; m.status = ""; break;
        case "cancelled": m.task = ev.task || m.task; m.status = "cancelled"; break;
        case "error": m.task = ev.task || m.task; m.status = "error"; m.error = ev.error; break;
      }
      schedule();
    },
    fail(msg) { m.status = "error"; m.error = msg; schedule(); },
  };
}

async function enterChat() {
  await loadSessions();
  if (!chat.current && chat.sessions[0]) await openSession(chat.sessions[0].id);
  else if (!chat.current) renderMessages(null);
  $("#prompt").focus();
}

async function loadSessions() {
  try { chat.sessions = await api("GET", "/api/sessions"); } catch { chat.sessions = []; }
  renderSessions();
}

function renderSessions() {
  $("#sessions").innerHTML = chat.sessions.map((s) =>
    `<li><button data-session="${esc(s.id)}" class="${s.id === chat.current ? "on" : ""}" title="${esc(s.title)}">${esc(s.title)}</button></li>`).join("");
}

async function openSession(id) {
  if (chat.busy) return; // finish the current reply first
  chat.current = id;
  renderSessions();
  let sess;
  try { sess = await api("GET", `/api/sessions/${id}`); } catch (e) { toast(e.message, true); return; }
  renderMessages(sess);
  const pending = sess.messages.find((m) => m.status === "pending" && (m.gen_id || m.task_id));
  if (pending) {
    const els = $$(".msg.assistant", $("#messages"));
    const el = els[els.length - 1];
    if (pending.task_id) attachStream(`/api/task/${pending.task_id}/stream`, liveTask(el), { kind: "task", id: pending.task_id });
    else attachStream(`/api/chat/${pending.gen_id}/stream`, liveMessage(el), { kind: "gen", id: pending.gen_id });
  }
}

function setBusy(on) {
  const b = $("#btn-send");
  const task = $("#chk-task").checked, loop = task && $("#chk-loop").checked;
  b.textContent = on ? "Stop" : loop ? "Start loop" : task ? "Start task" : "Send";
  b.classList.toggle("primary", !on);
  if (!on) chat.busy = null;
}

async function attachStream(url, live, busy) {
  chat.busy = busy;
  setBusy(true);
  try {
    const res = await fetch(url);
    if (res.ok) await readSSE(res, (ev) => live.on(ev));
  } catch { /* finished meanwhile */ }
  setBusy(false);
  loadSessions();
}

async function send() {
  const ta = $("#prompt");
  const text = ta.value.trim();
  const images = chat.images.slice();
  if ((!text && !images.length) || chat.busy) return;
  const asTask = $("#chk-task").checked;
  if (asTask && images.length) { toast("Pictures go to Heads. Untick Long task to send this one.", true); return; }
  const body = asTask
    ? { session_id: chat.current || "", goal: text, private: $("#chk-private").checked, loop: $("#chk-loop").checked }
    : { session_id: chat.current || "", message: text, model: $("#sel-model").value, target: $("#sel-device").value, private: $("#chk-private").checked };
  if (images.length) body.images = images.map((i) => ({ name: i.name, data: i.data }));
  ta.value = "";
  chat.images = [];
  renderAttachments();
  autosize();
  const box = $("#messages");
  if (box.querySelector(".chat-empty")) { box.innerHTML = ""; chat.count = 0; }
  const base = chat.count;
  box.appendChild(messageEl({ role: "user", content: text, _previews: images.map((i) => ({ url: i.url, name: i.name })) }, base));
  const el = messageEl(asTask ? { role: "assistant", status: "pending", content: "", task: { phase: "planning", steps: [] } } : { role: "assistant", status: "pending", content: "" }, base + 1);
  box.appendChild(el);
  chat.count = base + 2;
  box.scrollTop = box.scrollHeight;
  const live = asTask ? liveTask(el) : liveMessage(el);
  chat.busy = { kind: asTask ? "task" : "gen", id: "starting" };
  setBusy(true);
  try {
    const res = await fetch(asTask ? "/api/task" : "/api/chat", { method: "POST", headers: { "X-Chimera": "1", "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      chat.count = base; // nothing was saved
      live.fail(j.error || "Couldn't send that.");
    } else {
      await readSSE(res, (ev) => live.on(ev));
    }
  } catch {
    live.fail("Lost the connection to Chimera.");
  }
  setBusy(false);
  loadSessions();
}

async function stopGen() {
  const b = chat.busy;
  if (!b || b.id === "starting") return;
  const path = b.kind === "task" ? `/api/task/${b.id}/cancel` : `/api/chat/${b.id}/cancel`;
  try { await api("POST", path); } catch (e) { toast(e.message, true); }
}

function autosize() {
  const ta = $("#prompt");
  ta.style.height = "auto";
  ta.style.height = Math.min(200, ta.scrollHeight + 2) + "px";
}

function lendingDevices() {
  return S.network.joined ? S.network.devices.filter((d) => d.online && d.lending && d.ollama_ok) : [];
}

function refreshPickers() {
  const selM = $("#sel-model"), selD = $("#sel-device"), priv = $("#chk-private");
  const joined = S.network.joined;
  let models = [];
  if (!joined) {
    models = S.ollama.models.filter(canChat).map((m) => ({ value: m.name, label: `${m.name} (this computer)` }));
  } else {
    const map = new Map();
    for (const d of lendingDevices()) {
      for (const m of (d.models || []).filter(canChat)) {
        const k = normModel(m.name);
        if (!map.has(k)) map.set(k, { value: m.name, devs: [], size: m.params_b || 0 });
        map.get(k).devs.push(d.name);
      }
    }
    models = [...map.values()].sort((a, b) => b.size - a.size)
      .map((x) => ({ value: x.value, label: `${x.value} (${x.devs.length === 1 ? x.devs[0] : x.devs.length + " devices"})` }));
  }
  const htmlM = `<option value="">Best available</option>` + models.map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("");
  if (selM._html !== htmlM) {
    const prev = selM.value;
    selM.innerHTML = htmlM; selM._html = htmlM;
    selM.value = models.some((o) => o.value === prev) ? prev : "";
  }
  let devs = [];
  if (joined) {
    const want = normModel(selM.value);
    devs = lendingDevices().filter((d) => !want || (d.models || []).some((m) => normModel(m.name) === want))
      .filter((d) => !priv.checked || sameOwner(d.owner, S.device.owner))
      .map((d) => ({ value: d.id, label: d.id === S.device.id ? `${d.name} (this computer)` : deviceLabel(d.name, d.owner) }));
  }
  const htmlD = joined
    ? `<option value="">Any device</option>` + devs.map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("")
    : `<option value="">This computer</option>`;
  if (selD._html !== htmlD) {
    const prev = selD.value;
    selD.innerHTML = htmlD; selD._html = htmlD;
    selD.value = devs.some((o) => o.value === prev) ? prev : "";
  }
  selD.disabled = !joined;
  priv.closest("label").hidden = !joined;
}

// ---------- library ----------
const lib = { q: "", status: "", entries: [], admin: false, joined: false, open: new Set(), full: {}, stats: "", seq: 0, loaded: false };
const KIND_WORDS = { snippet: "Code", blender: "Blender script", lesson: "Lesson", prompt: "Prompt", plugin: "Head" };

async function loadLibrary() {
  const seq = ++lib.seq;
  const qs = new URLSearchParams({ q: lib.q, status: lib.status, limit: "200" });
  try {
    const r = await api("GET", `/api/library?${qs}`);
    if (seq !== lib.seq) return;
    Object.assign(lib, { entries: r.entries || [], admin: !!r.admin, joined: !!r.joined, loaded: true, error: "" });
  } catch (e) {
    if (seq !== lib.seq) return;
    lib.error = e.message; lib.loaded = true;
  }
  renderLibrary();
}

// Reload when the network's library counts change while it's on screen.
function libraryStatsChanged() {
  const st = JSON.stringify((S.network && S.network.library) || {}) + S.network.joined;
  if (st === lib.stats) return;
  lib.stats = st;
  if (view === "library") loadLibrary();
}

function entryStatus(e) {
  if (e.status === "verified") return { led: "ice", cls: "ice", text: "Verified" };
  if (e.status === "flagged") return { led: "brick", cls: "brick", text: "Flagged" };
  return { led: "amber pulse", cls: "amber", text: e.waiting ? `Waiting for ${e.waiting}` : "Being checked" };
}

function sourceLine(e) {
  const src = e.source || {};
  const bits = [];
  if (e.kind === "plugin") {
    bits.push(`Head${e.version ? ` ${e.version}` : ""} installed on ${src.owner ? `${src.owner}'s ` : ""}${src.device || "a computer"}`);
    bits.push(e.rated ? `${(e.stars / e.rated).toFixed(1)} stars from ${plural(e.rated, "rating")}` : "not rated yet");
    if (e.uses) bits.push(`ran ${plural(e.uses, "time")} for people`);
    const text = bits.join(", ");
    return text + ".";
  }
  if (src.from === "rating") bits.push(`From ${src.owner}'s ${src.rating}-star reply${src.model ? ` written by ${src.model}` : ""}`);
  else if (src.owner) bits.push(`Added by ${src.owner}`);
  if (e.votes > 1) bits.push(`rated 4 or 5 stars ${plural(e.votes, "time")}`);
  if (e.uses) bits.push(`reused ${plural(e.uses, "time")} by long tasks`);
  const text = bits.join(", ");
  return text ? text[0].toUpperCase() + text.slice(1) + "." : "";
}

const CHECK_WORDS = { review: "Reviewed", run: "Test run", curate: "Written", vote: "Rated again" };
function entryHTML(e) {
  const st = entryStatus(e), open = lib.open.has(e.id), full = lib.full[e.id] || e;
  let body = "";
  if (open) {
    const checks = (full.checks || []).slice().reverse().map((c) =>
      `<li><span class="led ${c.verdict === "pass" ? "ice" : "brick"}"></span><span><b>${esc(CHECK_WORDS[c.kind] || c.kind)}</b> by ${esc(c.device)}${c.kind === "vote" || c.kind === "curate" ? "" : `: ${esc(c.verdict === "pass" ? "passed" : c.verdict)}`}${c.detail ? `<span class="detail">${esc(c.detail)}</span>` : ""}</span><span class="when">${ago(c.at)}</span></li>`).join("");
    const acts = lib.admin ? `<div class="entry-actions">
        ${e.status !== "verified" ? `<button class="btn small" data-lib-act="approve" data-id="${esc(e.id)}">Approve</button>` : ""}
        ${e.status !== "flagged" ? `<button class="btn small" data-lib-act="flag" data-id="${esc(e.id)}">Flag</button>` : ""}
        <button class="btn small" data-lib-act="recheck" data-id="${esc(e.id)}">Check again</button>
        <button class="btn small danger" data-lib-act="delete" data-id="${esc(e.id)}">Delete</button></div>` : "";
    body = `<div class="entry-body">
      ${e.flag ? `<p class="flag">${esc(e.flag)}</p>` : ""}
      <pre>${esc(full.content || "")}</pre>
      <p class="entry-foot"><span>${esc(sourceLine(full))}</span>${(full.tags || []).map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</p>
      ${checks ? `<ul class="checks">${checks}</ul>` : ""}
      ${acts}</div>`;
  }
  return `<div class="entry"><button class="entry-head" data-lib-open="${esc(e.id)}" aria-expanded="${open}">
      <span class="led ${st.led}"></span>
      <span><b>${esc(e.title)}</b><span class="kind">${esc(KIND_WORDS[e.kind] || e.kind)}</span>${e.kind === "plugin" && e.rated ? `<span class="kind stars">★ ${(e.stars / e.rated).toFixed(1)} (${e.rated})</span>` : ""}<p>${esc(e.summary || "")}</p></span>
      <span class="estatus ${st.cls}">${esc(st.text)}</span></button>${body}</div>`;
}

function renderLibrary() {
  const list = $("#lib-list"), review = $("#lib-review");
  $("#lib-filter-flagged").hidden = !lib.admin;
  $$("#lib-filter button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.status === lib.status)));
  $("#btn-lib-add").hidden = !lib.joined;
  $("#btn-lib-export").hidden = !lib.admin;
  const st = (S && S.network.library) || {};
  if (lib.joined) {
    const total = lib.admin ? st.total || 0 : (st.verified || 0) + (st.unverified || 0);
    $("#lib-sub").innerHTML = `${plural(total, "entry", "entries")}: <b>${st.verified || 0} verified</b>, ${st.unverified || 0} being checked${lib.admin ? `, ${st.flagged || 0} flagged` : ""}. Saved from 4 and 5 star replies; long tasks reuse them instead of asking a model again.`;
  }
  if (!lib.loaded) { setHTML(list, `<p class="blank">Loading…</p>`); setHTML(review, ""); return; }
  if (lib.error) { setHTML(list, `<div class="empty"><p>${esc(lib.error)}</p></div>`); setHTML(review, ""); return; }
  if (!lib.joined) {
    setHTML(review, "");
    setHTML(list, `<div class="empty"><p>The library lives on your network's host. Join or host a network to share code, Blender scripts and lessons that worked.</p><div class="btns"><button class="btn primary" data-act="host">Host a network</button><button class="btn" data-act="join">Join a network</button></div></div>`);
    return;
  }
  let flagged = [], rest = lib.entries;
  if (lib.admin && !lib.status) {
    flagged = lib.entries.filter((e) => e.status === "flagged");
    rest = lib.entries.filter((e) => e.status !== "flagged");
  }
  setHTML(review, flagged.length ? `<div class="review"><div class="section-head"><h2 class="section-title">Needs your review</h2><span class="section-note">These failed a check or look like spam. Approve the ones that are fine, delete the rest.</span></div><div class="lib-list">${flagged.map(entryHTML).join("")}</div></div>` : "");
  let empty = "";
  if (!rest.length) {
    empty = lib.q ? `<p class="blank">Nothing matches “${esc(lib.q)}”.</p>`
      : lib.status ? `<p class="blank">No entries here.</p>`
      : `<div class="empty"><p>Nothing saved yet. Rate a reply 4 or 5 stars in Chat and say what worked: the network's biggest model turns it into a reusable entry, checks it, and long tasks start reusing it.</p></div>`;
  }
  setHTML(list, rest.map(entryHTML).join("") + empty);
}

async function toggleEntry(id) {
  if (lib.open.has(id)) { lib.open.delete(id); renderLibrary(); return; }
  lib.open.add(id);
  renderLibrary();
  try { lib.full[id] = await api("GET", `/api/library/${encodeURIComponent(id)}`); } catch (e) { toast(e.message, true); }
  renderLibrary();
}

async function libraryAction(id, action) {
  if (action === "delete" && !confirm("Delete this entry from the library for everyone?")) return;
  try {
    await api("POST", `/api/library/${encodeURIComponent(id)}/review`, { action });
    toast({ approve: "Approved", flag: "Flagged", recheck: "It'll be checked again", delete: "Deleted" }[action] || "Done");
    delete lib.full[id];
    if (action === "delete") lib.open.delete(id);
  } catch (e) { toast(e.message, true); }
  loadLibrary();
}

async function addLibraryEntry() {
  const body = {
    kind: $("#la-kind").value, language: $("#la-lang").value.trim(), title: $("#la-title").value.trim(),
    summary: $("#la-summary").value.trim(), content: $("#la-content").value,
    tags: $("#la-tags").value.split(",").map((t) => t.trim()).filter(Boolean),
  };
  if (!body.title || !body.content.trim()) { toast("Give it a title and some content.", true); return; }
  try {
    await api("POST", "/api/library", body);
    toast("Added. It's checked before long tasks use it.");
    $("#lib-add").reset();
    $("#lib-add").hidden = true;
    loadLibrary();
  } catch (e) { toast(e.message, true); }
}

// ---------- Head maker ----------
// Settings → Heads → Make a Head: a form that turns a program or a server on
// this computer into a Head, with no code. "Try it" then runs any Head installed
// here once, in its sandbox, the way the pool would.
const hm = { editing: null, kind: "", options: [], lastField: null, tryId: null, tryInfo: null, tryImage: null, tryAbort: null };

const HM_PLACEHOLDERS = {
  program: [["prompt", "the words"], ["input", "the picture's file"], ["out", "folder for results"], ["name", "the picture's name"], ["cache", "folder kept between runs"], ["blender", "Blender"], ["seed", "a random number"]],
  server: [["prompt", "the words"], ["input_base64", "the picture, base64"], ["input_data_url", "the picture, data: URL"], ["name", "the picture's name"], ["seed", "a random number"]],
};

const HM_BLANK = { name: "", summary: "", when_to_use: "", when_not_to_use: "", tags: [], timeout_s: 1800, maker: { kind: "", input: "picture", output: [], options: [], typical_s: 60 } };

// Starting points: each fills the whole form, to change from there.
const HM_EXAMPLES = [
  { label: "Remove a picture's background (rembg)", name: "Background remover", summary: "Cuts the subject out of a picture and makes the background transparent, with rembg.",
    when_to_use: "Someone attaches a picture and asks to remove or delete the background, cut out the subject, isolate it, or make it transparent.",
    when_not_to_use: "Changing what's in the picture, or requests without a picture.", tags: ["background", "remove background", "cutout", "transparent"], timeout_s: 600,
    maker: { kind: "program", input: "picture", output: ["picture"], command: "rembg i {{input}} {{out}}/{{name}}_cutout.png", reads: ["~/.u2net"], typical_s: 15, options: [] } },
  { label: "Run my Blender script on a picture", name: "Blender picture script", summary: "Runs my Blender script on a picture and returns what it renders.",
    when_to_use: "Someone attaches a picture and asks for the effect my script makes.", when_not_to_use: "", tags: ["blender", "render"], timeout_s: 1800,
    maker: { kind: "program", input: "picture", output: ["picture"], command: "{{blender}} -b --python /path/to/your_script.py -- {{input}} {{out}}/{{name}}_render.png {{prompt}}", typical_s: 90, options: [] } },
  { label: "Turn a picture into a short video (ffmpeg)", name: "Picture to video clip", summary: "Makes a short MP4 clip from a picture, with ffmpeg.",
    when_to_use: "Someone attaches a picture and asks to turn it into a video or a clip of a few seconds.", when_not_to_use: "Animating what's in the picture.", tags: ["video", "mp4", "clip", "ffmpeg"], timeout_s: 600,
    maker: { kind: "program", input: "picture", output: ["video"], command: "ffmpeg -y -loop 1 -i {{input}} -t {{seconds}} -vf scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p {{out}}/{{name}}.mp4", typical_s: 10,
      options: [{ name: "seconds", type: "integer", description: "how long the clip is, in seconds", default: 5, min: 1, max: 60 }] } },
  { label: "Read words out loud (Mac's say)", name: "Read it out loud", summary: "Reads the words out loud with the Mac's built-in voice and returns a sound file.",
    when_to_use: "Someone asks to read text out loud, say something, or turn words into speech or a voice recording.", when_not_to_use: "Questions about speech.", tags: ["speech", "voice", "read aloud", "tts"], timeout_s: 300,
    maker: { kind: "program", input: "words", output: ["sound"], command: "/usr/bin/say -o {{out}}/speech.aiff {{prompt}}", typical_s: 5, options: [] } },
  { label: "Pictures from words (AUTOMATIC1111 or Forge)", name: "Stable Diffusion pictures", summary: "Makes pictures from a description with the Stable Diffusion web UI running on this computer.",
    when_to_use: "Someone asks to generate, draw, paint or make a picture, image or illustration of something.", when_not_to_use: "Questions about images; editing an attached picture.", tags: ["image", "picture", "generate", "draw", "stable diffusion"], timeout_s: 900,
    maker: { kind: "server", input: "words", output: ["picture"], method: "POST", url: "http://127.0.0.1:7860/sdapi/v1/txt2img", result_field: "images", typical_s: 30,
      body: { prompt: "{{prompt}}", negative_prompt: "{{negative}}", steps: "{{steps}}", width: "{{width}}", height: "{{height}}", seed: "{{seed}}", cfg_scale: 7 },
      options: [
        { name: "steps", type: "integer", description: "sampling steps; more is slower and finer", default: 25, min: 10, max: 60 },
        { name: "width", type: "integer", description: "width in pixels", default: 768, min: 256, max: 2048 },
        { name: "height", type: "integer", description: "height in pixels", default: 768, min: 256, max: 2048 },
        { name: "negative", type: "text", description: "what the picture should not have", default: "blurry, low quality" }] } },
  { label: "3D mesh from a picture (Hunyuan3D server)", name: "3D mesh from a picture", summary: "Turns a picture of one object into a 3D mesh (GLB) with the Hunyuan3D server running on this computer.",
    when_to_use: "Someone attaches a picture of a single object and asks for a 3D model, mesh, GLB or asset of it.", when_not_to_use: "Pictures of whole scenes; 2D edits.", tags: ["3d", "mesh", "model", "glb", "hunyuan3d"], timeout_s: 3600,
    maker: { kind: "server", input: "picture", output: ["model"], method: "POST", url: "http://127.0.0.1:8080/generate", health_url: "http://127.0.0.1:8080/health", typical_s: 120,
      body: { image: "{{input_base64}}", seed: "{{seed}}", octree_resolution: "{{detail}}", num_inference_steps: "{{steps}}", guidance_scale: 5, texture: "{{texture}}", type: "glb" },
      options: [
        { name: "detail", type: "integer", description: "mesh detail: 256 is quick, 384 to 512 is finer and slower", default: 256, min: 128, max: 512 },
        { name: "steps", type: "integer", description: "diffusion steps", default: 30, min: 5, max: 50 },
        { name: "texture", type: "boolean", description: "also paint a texture (slower)", default: false }] } },
];

const fmtSize = (n) => n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n >= 1e3 ? `${Math.round(n / 1e3)} KB` : `${n} bytes`;

function hmFill(f) {
  const m = f.maker || {};
  $("#hm-name").value = f.name || "";
  $("#hm-summary").value = f.summary || "";
  $("#hm-when").value = f.when_to_use || "";
  $("#hm-not").value = f.when_not_to_use || "";
  $("#hm-tags").value = (f.tags || []).join(", ");
  $("#hm-input").value = m.input || "picture";
  $$("#hm-output .pill").forEach((c) => c.setAttribute("aria-pressed", String((m.output || []).includes(c.dataset.out))));
  $("#hm-command").value = m.command || "";
  $("#hm-command-noinput").value = m.command_no_input || "";
  $("#hm-url").value = m.url || "";
  $("#hm-method").value = m.method || "POST";
  $("#hm-body").value = m.body == null ? "" : typeof m.body === "string" ? m.body : JSON.stringify(m.body, null, 2);
  $("#hm-upload").value = m.upload_field || "";
  $("#hm-result").value = m.result_field || "";
  $("#hm-health").value = m.health_url || "";
  $("#hm-reads").value = (m.reads || []).join("\n");
  $("#hm-typical").value = m.typical_s || 60;
  $("#hm-timeout").value = Math.max(1, Math.round((f.timeout_s || 1800) / 60));
  hm.options = (m.options || []).map((o) => ({ ...o, choices: o.choices || [] }));
  setHMKind(m.kind || "");
}

function setHMKind(kind) {
  hm.kind = kind;
  $$(".maker-kinds .choice").forEach((c) => c.classList.toggle("on", c.dataset.kind === kind));
  $("#hm-program").hidden = kind !== "program";
  $("#hm-server").hidden = kind !== "server";
  $("#hm-common").hidden = !kind;
  $("#hm-reads").placeholder = kind === "server" ? "/Users/you/server/outputs" : "~/.u2net";
  $("#hm-reads-hint").textContent = kind === "server"
    ? "Only needed when the server answers with where it saved the file instead of the file itself: list that folder. Heads can't see your home folder otherwise."
    : "Heads can't see your home folder. The program's own folder and the paths written in the command are allowed already; list anything else it needs, like a folder of models.";
  syncHMInput();
  renderHMOptions();
}

function syncHMInput() {
  $("#hm-noinput-row").hidden = !(hm.kind === "program" && $("#hm-input").value === "either");
}

function renderHMChips() {
  const words = $("#hm-input").value === "words";
  const list = (HM_PLACEHOLDERS[hm.kind] || []).filter(([n]) => !(words && n.startsWith("input")));
  const opts = hm.options.map((o) => (o.name || "").trim()).filter((n) => /^[a-z][a-z0-9_]*$/.test(n)).map((n) => [n, "setting"]);
  const all = list.concat(opts);
  $("#hm-chips").innerHTML = all.length ? `<span class="lead">Click to insert:</span>` +
    all.map(([n, d]) => `<button type="button" class="pill" data-ph="${esc(n)}">{{${esc(n)}}}<span>${esc(d)}</span></button>`).join("") : "";
}

function renderHMOptions() {
  const types = [["number", "Number"], ["integer", "Whole number"], ["boolean", "Yes or no"], ["choice", "Choice"], ["text", "Text"]];
  $("#hm-options").innerHTML = hm.options.map((o, i) => {
    const t = o.type || "number";
    let extra = "";
    if (t === "number" || t === "integer") {
      extra = `<div class="pair"><label><span>Lowest <em>(optional)</em></span><input class="field" data-o="min" type="number" step="any" value="${esc(o.min ?? "")}"></label>
        <label><span>Highest <em>(optional)</em></span><input class="field" data-o="max" type="number" step="any" value="${esc(o.max ?? "")}"></label></div>`;
    } else if (t === "choice") {
      extra = `<label class="full"><span>Choices, separated by commas</span><input class="field" data-o="choices" value="${esc((o.choices || []).join(", "))}" placeholder="soft, hard, none"></label>`;
    } else if (t === "boolean" && hm.kind === "program") {
      extra = `<div class="pair"><label><span>When yes, the command gets</span><input class="field mono" data-o="yes" value="${esc(o.yes ?? "true")}" placeholder="(nothing)" spellcheck="false"></label>
        <label><span>When no, it gets</span><input class="field mono" data-o="no" value="${esc(o.no ?? "false")}" placeholder="(nothing)" spellcheck="false"></label></div>`;
    }
    const def = t === "boolean"
      ? `<select class="field" data-o="default"><option value="false"${o.default === true ? "" : " selected"}>Default: no</option><option value="true"${o.default === true ? " selected" : ""}>Default: yes</option></select>`
      : `<input class="field" data-o="default" value="${esc(o.default ?? "")}" placeholder="Default">`;
    return `<div class="opt" data-i="${i}">
      <input class="field mono" data-o="name" value="${esc(o.name || "")}" placeholder="name, like strength" spellcheck="false">
      <select class="field" data-o="type">${types.map(([v, l]) => `<option value="${v}"${v === t ? " selected" : ""}>${l}</option>`).join("")}</select>
      ${def}
      <button type="button" class="btn small quiet" data-o-rm="${i}">Remove</button>
      <input class="field full" data-o="description" value="${esc(o.description || "")}" placeholder="What it means, so the model knows when a request asks for it">
      ${extra}</div>`;
  }).join("");
  renderHMChips();
}

function hmOptionInput(e) {
  const el = e.target, box = el.closest(".opt");
  if (!box || !el.dataset.o) return;
  const o = hm.options[Number(box.dataset.i)];
  const k = el.dataset.o;
  if (k === "choices") o.choices = el.value.split(",").map((s) => s.trim()).filter(Boolean);
  else if (k === "default" && o.type === "boolean") o.default = el.value === "true";
  else o[k] = el.value;
  if (k === "type") {
    o.default = o.type === "boolean" ? false : "";
    renderHMOptions();
  } else if (k === "name") renderHMChips();
}

function hmInsert(name) {
  let el = hm.lastField;
  if (!el || el.closest("[hidden]")) el = hm.kind === "server" ? $("#hm-body") : $("#hm-command");
  const s = el.selectionStart ?? el.value.length, end = el.selectionEnd ?? el.value.length;
  // In the JSON, a placeholder goes in quotes unless the cursor is already inside some.
  const quote = el.id === "hm-body" && el.value[s - 1] !== '"';
  const text = quote ? `"{{${name}}}"` : `{{${name}}}`;
  el.value = el.value.slice(0, s) + text + el.value.slice(end);
  el.focus();
  el.selectionStart = el.selectionEnd = s + text.length;
}

function hmForm() {
  const v = (id) => $(id).value.trim();
  const num = (x) => (x === "" || x == null ? undefined : Number(x));
  const options = hm.options.map((o) => {
    const x = { name: (o.name || "").trim(), type: o.type || "number", description: (o.description || "").trim() };
    if (x.type === "number" || x.type === "integer") {
      const d = String(o.default ?? "").trim();
      x.default = d === "" ? null : Number.isNaN(Number(d)) ? d : Number(d);
      x.min = num(o.min);
      x.max = num(o.max);
    } else if (x.type === "boolean") {
      x.default = o.default === true;
      if (hm.kind === "program") { x.yes = o.yes ?? "true"; x.no = o.no ?? "false"; }
    } else if (x.type === "choice") {
      x.choices = o.choices || [];
      x.default = String(o.default ?? "");
    } else x.default = String(o.default ?? "");
    return x;
  });
  return {
    id: hm.editing || "", replace: !!hm.editing,
    name: v("#hm-name"), summary: v("#hm-summary"), when_to_use: v("#hm-when"), when_not_to_use: v("#hm-not"),
    tags: v("#hm-tags").split(",").map((s) => s.trim()).filter(Boolean),
    timeout_s: Math.round((Number($("#hm-timeout").value) || 30) * 60),
    body_text: $("#hm-body").value,
    maker: {
      kind: hm.kind, input: $("#hm-input").value,
      output: $$("#hm-output .pill").filter((c) => c.getAttribute("aria-pressed") === "true").map((c) => c.dataset.out),
      command: $("#hm-command").value, command_no_input: $("#hm-command-noinput").value,
      url: v("#hm-url"), method: $("#hm-method").value, upload_field: v("#hm-upload"), result_field: v("#hm-result"), health_url: v("#hm-health"),
      reads: $("#hm-reads").value.split("\n").map((s) => s.trim()).filter(Boolean),
      options, typical_s: Math.round(Number($("#hm-typical").value) || 60),
    },
  };
}

async function openMaker(id) {
  stopTry();
  hm.editing = null;
  $("#hm-error").textContent = "";
  if (id) {
    let h;
    try { h = await api("GET", `/api/heads/${encodeURIComponent(id)}`); } catch (e) { toast(e.message, true); return; }
    if (!h.editable) { toast(`${h.name} wasn't made here, so change its plugin.json by hand.`, true); return; }
    hm.editing = h.id;
    hmFill(h);
    $("#hm-title").textContent = `Change ${h.name}`;
  } else {
    hmFill(HM_BLANK);
    $("#hm-title").textContent = "Make a Head";
  }
  $("#hm-example-row").hidden = !!id;
  $("#hm-example").innerHTML = `<option value="">Nothing, I'll fill it in</option>` + HM_EXAMPLES.map((x, i) => `<option value="${i}">${esc(x.label)}</option>`).join("");
  showMakerForm();
  $("#hm-name").focus();
}

function showMakerForm() {
  $("#hm-form").hidden = false;
  $("#hm-try").hidden = true;
  $("#head-maker").hidden = false;
  $(".maker-card").scrollTop = 0;
}

async function saveHMHead() {
  const body = hmForm(), btn = $("#hm-save");
  $("#hm-error").textContent = "";
  btn.disabled = true;
  try {
    const r = await api("POST", "/api/heads", body);
    hm.editing = r.id; // saving again changes this Head
    $("#hm-title").textContent = `Change ${body.name}`;
    $("#hm-example-row").hidden = true;
    toast(`Saved ${body.name}${r.version ? " " + r.version : ""}. It's listed under Heads.`);
    openTry(r.id);
  } catch (e) {
    $("#hm-error").textContent = e.message;
  }
  btn.disabled = false;
}

async function openTry(id) {
  stopTry();
  hm.tryId = id;
  hm.tryImage = null;
  hm.tryInfo = null;
  $("#hm-form").hidden = true;
  $("#hm-try").hidden = false;
  $("#head-maker").hidden = false;
  $("#ht-out").innerHTML = "";
  $("#ht-pic-name").textContent = "";
  $("#ht-run").textContent = "Run it here";
  $("#ht-state").textContent = "Checking it…";
  let h;
  try { h = await api("GET", `/api/heads/${encodeURIComponent(id)}`); } catch (e) { $("#ht-state").textContent = e.message; return; }
  hm.tryInfo = h;
  $("#ht-title").textContent = `Try ${h.name}`;
  $("#ht-edit").hidden = !h.editable;
  const pic = (h.accepts || []).length > 0;
  $("#ht-pic-row").hidden = !pic;
  $("#ht-pic-row > span").textContent = h.optional_input ? "Picture (optional)" : "Picture";
  $("#ht-state").innerHTML = h.have
    ? "It runs here, in its sandbox, exactly as it would for someone in the pool. Only you see this try."
    : `<span class="bad">Can't run here yet: ${esc(h.note || "")}</span> Fix that and run it again; Chimera checks each time.`;
  $("#ht-request").focus();
}

function stopTry() {
  if (hm.tryAbort) hm.tryAbort.abort();
  hm.tryAbort = null;
}

async function runTry() {
  if (hm.tryAbort) { stopTry(); return; } // the button is Stop while it runs
  const h = hm.tryInfo;
  if (!h) return;
  if ((h.accepts || []).length && !h.optional_input && !hm.tryImage) { toast("Choose a picture for it to work on.", true); return; }
  const body = { request: $("#ht-request").value.trim() };
  if (hm.tryImage) body.image = hm.tryImage;
  const out = $("#ht-out");
  out.innerHTML = `<p class="said" id="ht-msg">Starting…</p><div class="plugin-progress"><span id="ht-bar" style="width:0%"></span></div>`;
  const ctl = new AbortController();
  hm.tryAbort = ctl;
  $("#ht-run").textContent = "Stop";
  let done = null, note = "";
  try {
    const res = await fetch(`/api/heads/${encodeURIComponent(hm.tryId)}/try`, {
      method: "POST", headers: { "X-Chimera": "1", "Content-Type": "application/json" }, body: JSON.stringify(body), signal: ctl.signal,
    });
    if (!res.ok) {
      let msg = `Something went wrong (${res.status}).`;
      try { msg = (await res.json()).error || msg; } catch { /* no body */ }
      throw new Error(msg);
    }
    await readSSE(res, (ev) => {
      if (ev.type === "status") {
        const m = $("#ht-msg"), bar = $("#ht-bar");
        if (m) m.textContent = ev.message;
        if (bar && ev.fraction >= 0) bar.style.width = `${Math.round(ev.fraction * 100)}%`;
      } else if (ev.type === "note") note = ev.message;
      else if (ev.type === "done") done = ev;
    });
    if (!done) throw new Error("It stopped without an answer.");
    out.innerHTML = tryResultHTML(done, note);
  } catch (e) {
    out.innerHTML = e.name === "AbortError" ? `<p class="said">Stopped.</p>` : `<p class="result bad">${esc(e.message)}</p>`;
  }
  if (hm.tryAbort === ctl) hm.tryAbort = null;
  $("#ht-run").textContent = "Run it again";
}

function tryResultHTML(d, note) {
  let html = note ? `<p class="said">${esc(note)}</p>` : "";
  if (!d.ok) return html + `<p class="result bad">${esc(d.error || "It didn't work.")}</p>`;
  html += `<p class="result">${esc(d.summary || "Done.")}</p>`;
  for (const f of d.files || []) {
    if (f.data_base64 && f.kept) html += `<img alt="${esc(f.name)}" src="data:${esc(f.mime)};base64,${f.data_base64}">`;
    const why = f.kept ? fmtSize(f.bytes) : `Left out: the Head says it makes ${(d.produces || []).join(", ")}, not ${f.mime}`;
    html += `<div class="tfile${f.kept ? "" : " dropped"}"><span>${esc(f.name)}</span><span>${esc(why)}</span></div>`;
  }
  if ((d.files || []).length) html += `<div><button type="button" class="btn small" data-act="head-try-files">Show the files</button></div>`;
  return html;
}

function closeMaker() {
  stopTry();
  $("#head-maker").hidden = true;
}

$("#hm-form").addEventListener("submit", (e) => { e.preventDefault(); saveHMHead(); });
$("#hm-form").addEventListener("keydown", (e) => { // Enter in a one-line box shouldn't save a half-filled Head
  if (e.key === "Enter" && e.target.tagName === "INPUT") e.preventDefault();
});
$("#hm-cancel").addEventListener("click", closeMaker);
$("#hm-add-option").addEventListener("click", () => {
  hm.options.push({ name: "", type: "number", description: "", default: "" });
  renderHMOptions();
  const last = $$("#hm-options .opt").pop();
  if (last) $('[data-o="name"]', last).focus();
});
$("#hm-options").addEventListener("input", hmOptionInput);
$("#hm-options").addEventListener("change", (e) => { if (e.target.tagName === "SELECT") hmOptionInput(e); });
$("#hm-input").addEventListener("change", () => { syncHMInput(); renderHMChips(); });
$("#hm-example").addEventListener("change", (e) => {
  const x = HM_EXAMPLES[Number(e.target.value)];
  if (e.target.value === "" || !x) return;
  if (($("#hm-name").value.trim() || $("#hm-command").value.trim() || $("#hm-url").value.trim()) && !confirm("Replace what you've filled in with this example?")) return;
  hmFill(x);
});
$("#head-maker").addEventListener("focusin", (e) => { if (e.target.matches("[data-template]")) hm.lastField = e.target; });
$("#ht-run").addEventListener("click", runTry);
$("#ht-request").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); if (!hm.tryAbort) runTry(); } });
$("#ht-pick").addEventListener("click", () => $("#ht-file").click());
$("#ht-file").addEventListener("change", (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  if (f.size > 40e6) { toast("That picture is too large (40 MB at most).", true); return; }
  const r = new FileReader();
  r.onload = () => {
    hm.tryImage = { name: f.name, data_base64: String(r.result).split(",")[1] || "" };
    $("#ht-pic-name").textContent = f.name;
  };
  r.readAsDataURL(f);
});
$("#ht-edit").addEventListener("click", () => {
  stopTry();
  if (hm.editing && hm.editing === hm.tryId && $("#hm-name").value) showMakerForm(); // the form still has it
  else openMaker(hm.tryId);
});
$("#ht-done").addEventListener("click", closeMaker);
$("#ht-folder").addEventListener("click", () => api("POST", "/api/open-folder", { which: "plugin", id: hm.tryId }).catch((e) => toast(e.message, true)));

// ---------- wiring ----------
document.addEventListener("click", async (e) => {
  const t = e.target.closest("button, a");
  if (!t) return;
  if (t.classList.contains("mode")) { setView(t.dataset.view); return; }
  if (t.dataset.copy) {
    try { await navigator.clipboard.writeText(t.dataset.copy); toast(`Copied ${t.dataset.copy}`); }
    catch { toast("Couldn't copy. Select it and copy by hand.", true); }
    return;
  }
  if (t.dataset.session) { openSession(t.dataset.session); return; }
  if (t.dataset.goto) { setView(t.dataset.goto); return; }
  if (t.dataset.pull) { queuePull(t.dataset.pull); return; }
  if (t.dataset.bench) { runBench(t.dataset.bench); return; }
  if (t.dataset.help !== undefined) { doHelp(Number(t.dataset.help)); return; }
  if (t.dataset.libOpen) { toggleEntry(t.dataset.libOpen); return; }
  if (t.dataset.libAct) { libraryAction(t.dataset.id, t.dataset.libAct); return; }
  if (t.dataset.found !== undefined) { joinFound(Number(t.dataset.found)); return; }
  if (t.dataset.act === "rescan") { scanNetworks(); return; }
  if (t.dataset.act === "install-dock") { installToDock(); return; }
  if (t.dataset.status !== undefined && t.closest("#lib-filter")) { lib.status = t.dataset.status; loadLibrary(); return; }
  if (t.dataset.step) {
    if (openSteps.has(t.dataset.step)) openSteps.delete(t.dataset.step); else openSteps.add(t.dataset.step);
    const el = t.closest(".msg"); if (el && el._m) fillTask(el, el._m);
    return;
  }
  if (t.dataset.star) { const el = t.closest(".msg"); if (el) rateMessage(el, Number(t.dataset.star)); return; }
  if (t.dataset.rateSkip !== undefined) { const el = t.closest(".msg"); if (el) sendRateNote(el, ""); return; }
  if (t.dataset.headTry) { openTry(t.dataset.headTry); return; }
  if (t.dataset.headEdit) { openMaker(t.dataset.headEdit); return; }
  if (t.dataset.ph) { hmInsert(t.dataset.ph); return; }
  if (t.dataset.out) { t.setAttribute("aria-pressed", String(t.getAttribute("aria-pressed") !== "true")); return; }
  if (t.dataset.kind && t.closest(".maker-kinds")) { setHMKind(t.dataset.kind); return; }
  if (t.dataset.oRm !== undefined) { hm.options.splice(Number(t.dataset.oRm), 1); renderHMOptions(); return; }
  switch (t.dataset.act) {
    case "open-ollama":
      t.disabled = true;
      try { await api("POST", "/api/ollama/start"); toast("Ollama is running"); } catch (err) { toast(err.message, true); }
      t.disabled = false;
      return;
    case "host": openSetup("first"); return;
    case "join": openSetup("join"); return;
    case "leave":
      if (S.lending.state !== "disconnected" && !confirm("Leave the network? Lending stops right away.")) return;
      try { await api("POST", "/api/network/leave"); toast("Left the network"); } catch (err) { toast(err.message, true); }
      return;
    case "stop-hosting":
      if (!confirm("Stop hosting? Everyone in this network gets disconnected until you host again.")) return;
      try { await api("POST", "/api/network/host", { enabled: false }); toast("Stopped hosting"); } catch (err) { toast(err.message, true); }
      return;
    case "new-invite":
      try { await api("POST", "/api/network/new-invite"); toast("New invite code made. Devices already in stay in."); } catch (err) { toast(err.message, true); }
      return;
    case "open-plugins":
      try { await api("POST", "/api/open-folder", { which: "plugins" }); } catch (err) { toast(err.message, true); }
      return;
    case "make-head": openMaker(); return;
    case "head-try-files":
      try { await api("POST", "/api/open-folder", { which: "head-try", id: hm.tryId }); } catch (err) { toast(err.message, true); }
      return;
    case "remove-attachment":
      chat.images.splice(Number(t.dataset.n), 1).forEach((i) => URL.revokeObjectURL(i.url));
      renderAttachments();
      return;
  }
});

document.addEventListener("change", async (e) => {
  const el = e.target;
  if (el.dataset.setting !== undefined) { saveSetting(el); return; }
  if (el.dataset.netsetting !== undefined) {
    try { await api("POST", "/api/network/settings", { [el.dataset.netsetting]: parseInt(el.value, 10) || 10 }); toast("Saved"); }
    catch (err) { toast(err.message, true); }
    return;
  }
  if (el.dataset.share !== undefined) { setShared(el.dataset.share, el.checked); return; }
  if (el.id === "sel-model" || el.id === "chk-private") refreshPickers();
  if (el.id === "chk-task") setTaskMode(el.checked);
  if (el.id === "chk-loop" && !chat.busy) $("#btn-send").textContent = el.checked ? "Start loop" : "Start task";
});

document.addEventListener("submit", (e) => {
  const f = e.target;
  if (f.dataset.rateNote !== undefined) {
    e.preventDefault();
    const el = f.closest(".msg");
    if (el) sendRateNote(el, f.elements.note.value.trim());
  }
});

// Light up stars up to the one under the pointer.
document.addEventListener("mouseover", (e) => {
  const star = e.target.closest(".star");
  const rate = e.target.closest(".rate");
  $$(".rate.hovering").forEach((r) => { if (r !== rate) { r.classList.remove("hovering"); $$(".star", r).forEach((x) => x.classList.remove("hov")); } });
  if (!star || !rate) return;
  rate.classList.add("hovering");
  const n = Number(star.dataset.star);
  $$(".star", rate).forEach((x) => x.classList.toggle("hov", Number(x.dataset.star) <= n));
});

function setTaskMode(on) {
  $("#composer").classList.toggle("task-mode", on);
  $("#loop-wrap").hidden = !on;
  if (!on) $("#chk-loop").checked = false;
  const loop = on && $("#chk-loop").checked;
  $("#prompt").placeholder = on ? "Describe a bigger task. Hydra splits it into steps and runs them on several computers…" : "Ask something…";
  if (!chat.busy) $("#btn-send").textContent = loop ? "Start loop" : on ? "Start task" : "Send";
  try { localStorage.setItem("chimera.task", on ? "1" : ""); } catch { /* private mode */ }
}

$("#switch").addEventListener("click", toggleLending);
$("#btn-connect").addEventListener("click", toggleLending);
$("#btn-stop-now").addEventListener("click", async () => {
  try { await api("POST", "/api/disconnect", { mode: "now" }); } catch (e) { toast(e.message, true); }
});
$("#dd-finish").addEventListener("click", async () => {
  $("#dlg-disconnect").hidden = true;
  try { await api("POST", "/api/disconnect", { mode: "finish" }); } catch (e) { toast(e.message, true); }
});
$("#dd-now").addEventListener("click", async () => {
  $("#dlg-disconnect").hidden = true;
  try { await api("POST", "/api/disconnect", { mode: "now" }); } catch (e) { toast(e.message, true); }
});
$("#dd-cancel").addEventListener("click", () => { $("#dlg-disconnect").hidden = true; });

$("#pull-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const name = $("#pull-name").value.trim();
  if (!name) { toast("Type a model name, like qwen3:8b.", true); $("#pull-name").focus(); return; }
  queuePull(name);
});
$("#btn-rescan").addEventListener("click", async () => {
  try { await api("POST", "/api/tools/rescan"); toast("Checking this computer's tools…"); } catch (e) { toast(e.message, true); }
});
let libTimer;
$("#lib-q").addEventListener("input", (e) => {
  clearTimeout(libTimer);
  libTimer = setTimeout(() => { lib.q = e.target.value.trim(); loadLibrary(); }, 250);
});
$("#btn-lib-add").addEventListener("click", () => { const f = $("#lib-add"); f.hidden = !f.hidden; if (!f.hidden) $("#la-title").focus(); });
$("#la-cancel").addEventListener("click", () => { $("#lib-add").hidden = true; });
$("#lib-add").addEventListener("submit", (e) => { e.preventDefault(); addLibraryEntry(); });

$("#su-host").addEventListener("click", hostNetwork);
$("#su-join").addEventListener("click", () => {
  if (namesOrError($("#su-error"))) openSetup("join");
});
$("#su-join-go").addEventListener("click", joinNetwork);
$("#su-back").addEventListener("click", () => openSetup("first"));
$("#su-skip").addEventListener("click", async () => {
  const owner = $("#su-owner").value.trim(), device = $("#su-device").value.trim();
  const body = { setup_done: true };
  if (owner) body.owner = owner;
  if (device) body.device_name = device;
  try { await api("POST", "/api/settings", body); } catch { /* fine */ }
  closeSetup();
});
$("#su-done").addEventListener("click", closeSetup);
$("#su-invite").addEventListener("keydown", (e) => { if (e.key === "Enter") joinNetwork(); });

$("#btn-new-chat").addEventListener("click", () => {
  if (chat.busy) return;
  chat.current = null;
  renderSessions();
  renderMessages(null);
  $("#prompt").focus();
});
$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  if (chat.busy) stopGen(); else send();
});
$("#prompt").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    if (!chat.busy) send();
  }
});
$("#prompt").addEventListener("input", autosize);
$("#btn-attach").addEventListener("click", () => $("#file-attach").click());
$("#file-attach").addEventListener("change", (e) => { addImageFile(e.target.files[0]); e.target.value = ""; });
$("#prompt").addEventListener("paste", (e) => {
  const f = [...((e.clipboardData && e.clipboardData.files) || [])].find((x) => /^image\//.test(x.type));
  if (f) { e.preventDefault(); addImageFile(f); }
});
$("#composer").addEventListener("dragover", (e) => { if ([...e.dataTransfer.types].includes("Files")) { e.preventDefault(); $("#composer").classList.add("drop"); } });
$("#composer").addEventListener("dragleave", () => $("#composer").classList.remove("drop"));
$("#composer").addEventListener("drop", (e) => {
  $("#composer").classList.remove("drop");
  const f = [...e.dataTransfer.files].find((x) => /^image\//.test(x.type));
  if (f) { e.preventDefault(); addImageFile(f); }
});

$("#btn-open-folder").addEventListener("click", () => api("POST", "/api/open-folder").catch((e) => toast(e.message, true)));
$("#btn-quit").addEventListener("click", async () => {
  if (S && S.lending.running.length && !confirm("A step is still running. Quit anyway? It moves to another device.")) return;
  try { await api("POST", "/api/quit"); } catch { /* already gone */ }
});

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!$("#dlg-disconnect").hidden) $("#dlg-disconnect").hidden = true;
  else if (!$("#head-maker").hidden && !$("#hm-try").hidden) closeMaker(); // not from the form: it would lose what's typed
  else if (!$("#setup").hidden && setupStep !== "hosted") closeSetup();
});

// ---------- install to Dock (PWA) ----------
let deferredInstall = null;
const installed = () => { try { return matchMedia("(display-mode: standalone)").matches || navigator.standalone; } catch { return false; } };
function refreshDock() {
  const row = $("#dock-row"), hint = $("#dock-hint");
  if (!row) return;
  if (installed()) { row.hidden = true; if (hint) hint.hidden = true; return; }
  row.hidden = false; if (hint) hint.hidden = false;
}
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => { /* fine; install just won't be offered */ });
}
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferredInstall = e; refreshDock(); });
window.addEventListener("appinstalled", () => { deferredInstall = null; toast("Added to your Dock. Open Chimera from there next time."); refreshDock(); });
async function installToDock() {
  if (deferredInstall) {
    deferredInstall.prompt();
    try { await deferredInstall.userChoice; } catch { /* dismissed */ }
    deferredInstall = null;
    refreshDock();
    return;
  }
  if (installed()) { toast("Chimera is already in your Dock."); return; }
  toast("In Chrome or Edge, open the ⋮ menu and choose “Install Chimera” (under Cast, save, and share).", false);
}

// ---------- start ----------
try {
  const v = localStorage.getItem("chimera.view");
  if (v && $(`#view-${v}`)) setView(v);
  if (localStorage.getItem("chimera.task")) { $("#chk-task").checked = true; setTaskMode(true); }
} catch { /* private mode */ }
refreshDock();
connectStream();

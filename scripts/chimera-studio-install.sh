#!/usr/bin/env bash
# =============================================================================
# chimera-studio-install.sh
# Installs the Chimera hub lineup on the M3 Ultra Mac Studio (96 GB).
# Written 2026-10-24. Never uses sudo.
#
#   bash chimera-studio-install.sh              install whatever is still missing
#   bash chimera-studio-install.sh --dry-run    show the plan, change nothing
#   bash chimera-studio-install.sh --help
#
# Order (the planner is always last):
#   1   Hunyuan3D 2.1, Mac/MPS port     -> ~/chimera-tools/hunyuan3d-2.1-mac
#   2   Image    Ollama  x/z-image-turbo
#   3a  Music    ACE-Step 1.5 XL turbo + 4B LM -> ~/chimera-tools/ACE-Step-1.5
#   3b  Speech   Ollama  phonon (text-to-speech)
#   4   Vision   Ollama  qwen3.8:27b
#   5   Planner  Ollama  gpt-oss:120b
#
# Re-runnable: finished steps are skipped, failed or skipped ones are retried,
# and interrupted downloads resume. Every step is independent, so one failure
# never blocks the rest.
#
# WHAT IT TOUCHES
#   ~/chimera-tools            tools, Python envs, model weights, launchers, log
#   Ollama's model folder      the four `ollama pull`s (default ~/.ollama/models)
#   ~/.cache/huggingface       facebook/dinov2-giant, used by Hunyuan texturing
#   ~/.u2net                   rembg's background-removal model, for the hunyuan3d-mac Head
#   ~/.local/share/uv/python   only if no Python 3.10-3.12 here can run pip and uv is installed
#   ~/.cache/uv and pip        Python package caches
#   ~/.gitconfig               Hunyuan's installer runs `git lfs install`
#   Homebrew                   only if Python 3.10-3.12 or git-lfs is missing AND
#                              you say yes (or set ALLOW_BREW=1)
#   Sleep                      held off with `caffeinate` while it runs, nothing else
# It does not use sudo, change system settings, modify your shell profile, or
# touch the Chimera app. Code comes from three repos pinned to the commits that
# were read before this script was written (see PINS below); weights come from
# Hugging Face; Python packages come from PyPI; models come from Ollama.
#
# Known behaviours of the tools it runs (not of this script):
#   - Hunyuan's installer prints in Russian. Cosmetic.
#   - ACE-Step's downloader checks whether google.com:443 is reachable to pick
#     Hugging Face or ModelScope, and falls back to ModelScope if Hugging Face fails.
#   - ACE-Step writes MP3/Opus/AAC only if `ffmpeg` is on PATH (WAV/FLAC need nothing).
# =============================================================================

set -uo pipefail
export GIT_TERMINAL_PROMPT=0

# ---- what to install (override any of these from the environment) ------------
TOOLS_DIR="${TOOLS_DIR:-$HOME/chimera-tools}"

IMAGE_MODEL="${IMAGE_MODEL:-x/z-image-turbo}"
TTS_MODEL="${TTS_MODEL:-phonon}"
VISION_MODEL="${VISION_MODEL:-qwen3.8:27b}"
PLANNER_MODEL="${PLANNER_MODEL:-gpt-oss:120b}"
ACE_DIT="${ACE_DIT:-acestep-v15-xl-turbo}"
ACE_LM="${ACE_LM:-acestep-5Hz-lm-4B}"

# rough download sizes in GB; only used for the free-space check
HUNYUAN_GB="${HUNYUAN_GB:-40}"
MUSIC_GB="${MUSIC_GB:-40}"
IMAGE_GB="${IMAGE_GB:-13}"
TTS_GB="${TTS_GB:-1}"
VISION_GB="${VISION_GB:-18}"
PLANNER_GB="${PLANNER_GB:-65}"
HEADROOM_GB="${HEADROOM_GB:-15}"

# ---- PINS: the exact commits that were reviewed -------------------------------
HY_PORT_URL="https://github.com/VladimirTalyzin/hunyuan3d-2.1-mac.git"
HY_PORT_SHA="6f4b63bd6419406f40291bca23a7c849bcaae2a3"      # 2026-08-09 "Add MPS texture support"
HY_UPSTREAM_URL="https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1.git"
HY_UPSTREAM_SHA="82920d643c0dc2f7bfd7255f45f62d386edfe60c"  # 2025-10-17, upstream HEAD when reviewed
ACE_URL="https://github.com/ACE-Step/ACE-Step-1.5.git"
ACE_SHA="ca1e85fe9430179831e6bc6be790c332190a3866"          # 2026-08-29

# ---- derived paths and state ---------------------------------------------------
HY_DIR="$TOOLS_DIR/hunyuan3d-2.1-mac"
ACE_DIR="$TOOLS_DIR/ACE-Step-1.5"
DONE_DIR="$TOOLS_DIR/.install-state"
UV_ENV="$TOOLS_DIR/uv-env"

DRY_RUN="${DRY_RUN:-0}"
SKIP="${SKIP:-}"
LOG_FILE=""
RESULTS=""
STEP_NOTE=""
CURRENT_STEP=""
OLLAMA_BIN=""
OLLAMA_READY=0
OLLAMA_NOTE=""
OLLAMA_VER=""
UV_BIN=""
NEED_MODELS_GB=0
NEED_TOOLS_GB=0

# ---- small helpers -------------------------------------------------------------
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

say() {
  printf '%s\n' "$*"
  if [ -n "$LOG_FILE" ]; then printf '%s\n' "$*" >> "$LOG_FILE"; fi
}

warn() { say "  [!] $*"; }

hdr() {
  say ""
  say "----------------------------------------------------------------"
  say "$*"
  say "----------------------------------------------------------------"
}

note() { STEP_NOTE="$*"; }

dry() { [ "$DRY_RUN" = "1" ]; }

want() {
  case ",$SKIP," in
    *",${1:-},"*) return 1 ;;
  esac
  return 0
}

fmt_secs() {
  local s="${1:-0}"
  printf '%dm%02ds' $((s / 60)) $((s % 60))
}

usage() {
  cat <<'EOF'
chimera-studio-install.sh - Chimera hub lineup for the 96 GB M3 Ultra Mac Studio

  bash chimera-studio-install.sh [--dry-run] [--help]

Environment overrides (all optional):
  SKIP=hunyuan,image,music,tts,vision,planner   skip steps (comma-separated)
  IMAGE_MODEL TTS_MODEL VISION_MODEL PLANNER_MODEL   Ollama tags to pull
  ACE_DIT ACE_LM                                ACE-Step DiT and language-model names
  TOOLS_DIR=~/chimera-tools                     where tools and weights go
  ALLOW_BREW=1                                  let Hunyuan's installer run
                                                `brew install python@3.11 git-lfs` if needed
  FORCE=1                                       carry on past the memory / free-disk checks
  HUNYUAN_GB MUSIC_GB IMAGE_GB TTS_GB VISION_GB PLANNER_GB   size estimates for the disk check

Example: smaller planner
  PLANNER_MODEL=gpt-oss:20b PLANNER_GB=14 bash chimera-studio-install.sh
EOF
}

# bash 3.2 (macOS's /bin/bash) has no mapfile, no ${x^^}, no associative arrays.
# Everything below sticks to what 3.2 supports.

# true if dotted version $1 >= $2 (up to three numeric parts)
ver_ge() {
  local v1="${1%%[!0-9.]*}" v2="${2%%[!0-9.]*}" a1 a2 a3 b1 b2 b3
  IFS=. read -r a1 a2 a3 <<EOF
$v1
EOF
  IFS=. read -r b1 b2 b3 <<EOF
$v2
EOF
  a1="${a1:-0}"; a2="${a2:-0}"; a3="${a3:-0}"
  b1="${b1:-0}"; b2="${b2:-0}"; b3="${b3:-0}"
  [ $((10#$a1)) -gt $((10#$b1)) ] && return 0
  [ $((10#$a1)) -lt $((10#$b1)) ] && return 1
  [ $((10#$a2)) -gt $((10#$b2)) ] && return 0
  [ $((10#$a2)) -lt $((10#$b2)) ] && return 1
  [ $((10#$a3)) -ge $((10#$b3)) ]
}

# retry <tries> <seconds> command...   (downloads resume, so a retry is cheap)
retry() {
  local n="$1" s="$2" i=1
  shift 2
  while :; do
    if "$@"; then return 0; fi
    if [ "$i" -ge "$n" ]; then return 1; fi
    say "  attempt $i of $n failed; trying again in ${s}s (downloads resume where they stopped)"
    sleep "$s"
    i=$((i + 1))
  done
}

# ---- Ollama ----------------------------------------------------------------------
ol() { "$OLLAMA_BIN" "$@"; }

ollama_has() {
  local name="${1:-}" last list
  [ -n "$OLLAMA_BIN" ] || return 1
  last="${name##*/}"
  case "$last" in
    *:*) ;;
    *) name="$name:latest" ;;
  esac
  list="$(ol list 2>/dev/null | awk 'NR > 1 { print $1 }')"
  grep -Fxq -- "$name" <<EOF
$list
EOF
}

ollama_models_dir() {
  local d="${OLLAMA_MODELS:-}"
  if [ -z "$d" ] && command -v launchctl >/dev/null 2>&1; then
    d="$(launchctl getenv OLLAMA_MODELS 2>/dev/null || true)"
  fi
  if [ -z "$d" ]; then d="$HOME/.ollama/models"; fi
  printf '%s' "$d"
}

setup_ollama() {
  local p i
  OLLAMA_BIN=""
  if command -v ollama >/dev/null 2>&1; then
    OLLAMA_BIN="$(command -v ollama)"
  else
    for p in /Applications/Ollama.app/Contents/Resources/ollama \
             "$HOME/Applications/Ollama.app/Contents/Resources/ollama" \
             /opt/homebrew/bin/ollama /usr/local/bin/ollama; do
      if [ -x "$p" ]; then OLLAMA_BIN="$p"; break; fi
    done
  fi
  if [ -z "$OLLAMA_BIN" ]; then
    OLLAMA_NOTE="Ollama isn't installed (https://ollama.com/download): install it, open it once, then re-run"
    return 1
  fi
  if ol list >/dev/null 2>&1; then
    :
  elif dry; then
    say "  Ollama isn't answering right now (a real run would try to open the Ollama app)"
  else
    say "  Ollama isn't answering; trying to open the Ollama app..."
    open -a Ollama >/dev/null 2>&1 || true
    i=0
    while [ "$i" -lt 30 ]; do
      if ol list >/dev/null 2>&1; then break; fi
      sleep 2
      i=$((i + 1))
    done
    if ! ol list >/dev/null 2>&1; then
      OLLAMA_NOTE="Ollama isn't running: open the Ollama app (llama in the menu bar), then re-run"
      return 1
    fi
  fi
  OLLAMA_VER="$(ol --version 2>/dev/null | sed -n 's/.*version is \([0-9][0-9.]*\).*/\1/p' | head -n 1)"
  OLLAMA_READY=1
  return 0
}

pull_model() {
  local m="${1:-}"
  if [ "$OLLAMA_READY" != "1" ]; then note "$OLLAMA_NOTE"; return 10; fi
  if ollama_has "$m"; then
    say "  $m is already installed, skipping (to update it yourself: ollama pull $m)"
    return 0
  fi
  if dry; then say "  [dry-run] would run: ollama pull $m"; return 0; fi
  say "  ollama pull $m"
  if ! retry 3 20 ol pull "$m"; then
    note "ollama pull $m failed; re-run to resume"
    return 1
  fi
  if ! ollama_has "$m"; then
    note "pull finished but $m is not in 'ollama list'"
    return 1
  fi
  return 0
}

# ---- disk ------------------------------------------------------------------------
nearest_dir() {
  local p="${1:-/}"
  while [ ! -d "$p" ] && [ "$p" != "/" ] && [ -n "$p" ]; do p="$(dirname "$p")"; done
  printf '%s' "$p"
}

free_gb() { df -Pk "$(nearest_dir "$1")" 2>/dev/null | awk 'NR == 2 { printf "%d", $4 / 1048576 }'; }
fs_of() { df -Pk "$(nearest_dir "$1")" 2>/dev/null | awk 'NR == 2 { print $1 }'; }

add_need_model() {  # <step id> <model> <gb>
  want "$1" || return 0
  if ollama_has "$2"; then return 0; fi
  NEED_MODELS_GB=$((NEED_MODELS_GB + $3))
}

check_disk() {
  local mdir fm ft sm st total
  mdir="$(ollama_models_dir)"
  NEED_MODELS_GB=0
  NEED_TOOLS_GB=0
  if want hunyuan && [ ! -f "$DONE_DIR/hunyuan3d" ]; then NEED_TOOLS_GB=$((NEED_TOOLS_GB + HUNYUAN_GB)); fi
  if want music && [ ! -f "$DONE_DIR/acestep" ]; then NEED_TOOLS_GB=$((NEED_TOOLS_GB + MUSIC_GB)); fi
  if [ "$OLLAMA_READY" = "1" ]; then
    add_need_model image "$IMAGE_MODEL" "$IMAGE_GB"
    add_need_model tts "$TTS_MODEL" "$TTS_GB"
    add_need_model vision "$VISION_MODEL" "$VISION_GB"
    add_need_model planner "$PLANNER_MODEL" "$PLANNER_GB"
  fi
  ft="$(free_gb "$TOOLS_DIR")"; fm="$(free_gb "$mdir")"
  st="$(fs_of "$TOOLS_DIR")"; sm="$(fs_of "$mdir")"
  ft="${ft:-0}"; fm="${fm:-0}"
  total=$((NEED_MODELS_GB + NEED_TOOLS_GB))
  say "Disk"
  if [ "$total" -eq 0 ]; then
    say "  nothing left to download"
    return 0
  fi
  if [ "$st" = "$sm" ]; then
    say "  free      : ${ft} GB on one volume (tools and Ollama models share it)"
    say "  still need: ~${total} GB (${NEED_TOOLS_GB} tools + ${NEED_MODELS_GB} Ollama models) plus ${HEADROOM_GB} GB headroom"
    if [ "$ft" -ge $((total + HEADROOM_GB)) ]; then return 0; fi
  else
    say "  tools  : ${ft} GB free, need ~${NEED_TOOLS_GB} GB   ($TOOLS_DIR)"
    say "  models : ${fm} GB free, need ~${NEED_MODELS_GB} GB   ($mdir)"
    if [ "$ft" -ge $((NEED_TOOLS_GB + HEADROOM_GB)) ] && [ "$fm" -ge $((NEED_MODELS_GB + HEADROOM_GB)) ]; then return 0; fi
  fi
  say "  NOT ENOUGH FREE SPACE. Free some up, pick smaller models (for example"
  say "  PLANNER_MODEL=gpt-oss:20b PLANNER_GB=14 saves ~51 GB), skip a step with SKIP=..., or run"
  say "  with FORCE=1 to try anyway (the planner is last, so everything else lands first)."
  if [ "${FORCE:-0}" = "1" ]; then say "  FORCE=1 set: carrying on."; return 0; fi
  return 1
}

# ---- git: fetch an exact commit ----------------------------------------------------
git_pinned() {  # <url> <sha> <dir>
  local url="${1:-}" sha="${2:-}" dir="${3:-}" cur=""
  if [ -d "$dir/.git" ]; then
    cur="$(git -C "$dir" rev-parse HEAD 2>/dev/null || true)"
    if [ "$cur" = "$sha" ]; then
      say "  $(basename "$dir") is already at ${sha:0:10}"
      return 0
    fi
    if [ -n "$cur" ]; then
      note "$dir is at ${cur:0:10}, not the reviewed ${sha:0:10}: move it aside and re-run"
      return 1
    fi
    rm -rf "$dir/.git"   # leftover from an attempt that died before the first checkout
  fi
  if [ -e "$dir" ] && [ -n "$(ls -A "$dir" 2>/dev/null)" ]; then
    note "$dir exists but isn't a git checkout: move it aside and re-run"
    return 1
  fi
  say "  fetching $(basename "$dir") @ ${sha:0:10} from $url"
  if mkdir -p "$dir" \
     && git -C "$dir" init -q \
     && git -C "$dir" remote add origin "$url" \
     && git -C "$dir" fetch -q --depth 1 origin "$sha" \
     && git -C "$dir" checkout -q --detach FETCH_HEAD; then
    return 0
  fi
  rm -rf "$dir/.git"
  rmdir "$dir" 2>/dev/null || true
  note "could not fetch ${sha:0:10} from $url"
  return 1
}

need_git() {
  if ! xcode-select -p >/dev/null 2>&1; then
    note "Xcode Command Line Tools missing: run 'xcode-select --install', then re-run this script"
    return 1
  fi
  if ! command -v git >/dev/null 2>&1; then
    note "git not found"
    return 1
  fi
  return 0
}

# ---- step 1: Hunyuan3D 2.1 ------------------------------------------------------------
confirm_brew() {  # <formulae>
  local what="${1:-}" ans=""
  say "  Hunyuan's installer will run:  brew install $what   (Homebrew, user-level, no sudo)"
  if dry; then say "  [dry-run] would ask for a yes first"; return 0; fi
  if [ "${ALLOW_BREW:-0}" = "1" ]; then say "  ALLOW_BREW=1 is set, fine."; return 0; fi
  if [ -t 0 ] && [ -t 1 ]; then
    printf '  Go ahead? [y/N] (no answer within 60 s counts as no): '
    read -r -t 60 ans || true
    printf '\n'
    case "$ans" in y|Y|yes|YES|Yes) return 0 ;; esac
  fi
  return 1
}

# A Python 3.10-3.12 whose pip can start. Homebrew's python@3.11 bottle may be built for a newer
# macOS than this one: then pyexpat can't load (/usr/lib/libexpat lacks a symbol), pip can't read
# the macOS version, and ensurepip fails. Falls back to uv's self-contained Python 3.11.
working_python() {
  local c
  for c in python3.12 python3.11 python3.10 "$HOME/.local/bin/python3.12" "$HOME/.local/bin/python3.11"; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import pyexpat, ensurepip' >/dev/null 2>&1; then
      echo "$c"
      return 0
    fi
  done
  command -v uv >/dev/null 2>&1 || return 1
  say "  no working Python 3.10-3.12 found; installing uv's Python 3.11 (~/.local/share/uv/python)" >&2
  uv python install 3.11 >&2 || return 1
  "$HOME/.local/bin/python3.11" -c 'import pyexpat, ensurepip' >/dev/null 2>&1 || return 1
  echo "$HOME/.local/bin/python3.11"
}

step_hunyuan() {
  local marker="$DONE_DIR/hunyuan3d" py="" v need="" w
  if [ -f "$marker" ]; then
    say "  already installed (delete $marker to reinstall); skipping"
    return 0
  fi
  if ! need_git; then return 10; fi
  if ! command -v brew >/dev/null 2>&1; then
    note "Homebrew missing; this port's installer requires it (https://brew.sh). Install it, then re-run"
    return 10
  fi
  for v in 3.12 3.11 3.10; do
    if command -v "python$v" >/dev/null 2>&1; then py="python$v"; break; fi
  done
  if [ -z "$py" ]; then need="python@3.11"; fi
  if ! command -v git-lfs >/dev/null 2>&1; then need="${need:+$need }git-lfs"; fi
  if [ -n "$need" ]; then
    if ! confirm_brew "$need"; then
      note "needs 'brew install $need'; say yes at the prompt, set ALLOW_BREW=1, or install them yourself, then re-run"
      return 10
    fi
  else
    say "  prerequisites found: Xcode CLT, Homebrew, $py, git-lfs"
  fi
  if dry; then
    say "  [dry-run] would fetch the port @ ${HY_PORT_SHA:0:10} and Tencent's repo @ ${HY_UPSTREAM_SHA:0:10},"
    say "  [dry-run] then run the port's install.sh (venv, PyTorch/MPS, ~${HUNYUAN_GB} GB of weights)"
    return 0
  fi
  git_pinned "$HY_PORT_URL" "$HY_PORT_SHA" "$HY_DIR" || return 1
  git_pinned "$HY_UPSTREAM_URL" "$HY_UPSTREAM_SHA" "$HY_DIR/Hunyuan3D-2.1" || return 1
  # The port's installer reuses an existing venv, so make it here with a Python whose pip starts.
  # A venv left by a failed run (no working pip) is remade; one that works is left alone.
  if [ -d "$HY_DIR/venv" ] && ! "$HY_DIR/venv/bin/python" -m pip --version >/dev/null 2>&1; then
    say "  removing the half-made venv from an earlier failed run"
    rm -rf "$HY_DIR/venv"
  fi
  if [ ! -d "$HY_DIR/venv" ]; then
    py="$(working_python)" || { note "no Python 3.10-3.12 here can run pip (Homebrew's may be built for a newer macOS); run 'brew install uv', then re-run"; return 1; }
    say "  making the venv with $py"
    "$py" -m venv "$HY_DIR/venv" || { note "couldn't make the venv with $py"; return 1; }
  fi
  say "  running the port's own installer (the reviewed copy). Long: ~${HUNYUAN_GB} GB, tens of minutes."
  say "  Its messages are in Russian; that's cosmetic."
  if ! ( cd "$HY_DIR" && bash ./install.sh ); then
    note "the port's installer failed (scroll up for why); re-run to resume"
    return 1
  fi
  w="$HY_DIR/weights/Hunyuan3D-2.1"
  if [ ! -x "$HY_DIR/venv/bin/python" ]; then note "venv missing after install"; return 1; fi
  if [ ! -d "$w/hunyuan3d-dit-v2-1" ]; then note "shape weights missing after install"; return 1; fi
  if [ ! -d "$w/hunyuan3d-paintpbr-v2-1" ]; then note "texture (paint) weights missing after install"; return 1; fi
  # rembg fetches its background model on first use; Heads run with no network, so fetch it now.
  if [ ! -f "${U2NET_HOME:-$HOME/.u2net}/u2net.onnx" ]; then
    say "  fetching rembg's u2net background model (~176 MB) for the hunyuan3d-mac Head"
    if ! "$HY_DIR/venv/bin/python" -c "from rembg import new_session; new_session('u2net')"; then
      note "couldn't download rembg's u2net model; re-run to retry"
      return 1
    fi
  fi
  printf 'port=%s upstream=%s date=%s\n' "$HY_PORT_SHA" "$HY_UPSTREAM_SHA" "$(date +%Y-%m-%d)" > "$marker"
  return 0
}

# ---- step 3a: ACE-Step -----------------------------------------------------------------
find_uv() {
  local p
  p="$(command -v uv 2>/dev/null || true)"
  if [ -n "$p" ]; then UV_BIN="$p"; return 0; fi
  for p in "$UV_ENV/bin/uv" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
    if [ -x "$p" ]; then UV_BIN="$p"; return 0; fi
  done
  return 1
}

install_uv() {
  local py="" c
  for c in python3.12 python3.11 python3.13 python3; do
    if command -v "$c" >/dev/null 2>&1; then py="$c"; break; fi
  done
  [ -n "$py" ] || return 1
  say "  uv not found; installing it from PyPI into $UV_ENV (isolated, no shell-profile changes)"
  "$py" -m venv "$UV_ENV" || return 1
  "$UV_ENV/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip || true
  "$UV_ENV/bin/python" -m pip install --quiet --disable-pip-version-check uv || return 1
  [ -x "$UV_ENV/bin/uv" ] || return 1
  UV_BIN="$UV_ENV/bin/uv"
  return 0
}

write_ace_env() {
  local f="$ACE_DIR/.env"
  if [ -f "$f" ]; then
    say "  $f already exists; left alone (it should set ACESTEP_CONFIG_PATH=$ACE_DIT and ACESTEP_LM_MODEL_PATH=$ACE_LM)"
    return 0
  fi
  cat > "$f" <<EOF
# Written by chimera-studio-install.sh. Edit freely; ACE-Step's launchers and API read it.
ACESTEP_CONFIG_PATH=$ACE_DIT
ACESTEP_LM_MODEL_PATH=$ACE_LM
ACESTEP_LM_BACKEND=mlx
EOF
}

write_launchers() {
  local api="$TOOLS_DIR/start-acestep-api.sh" ui="$TOOLS_DIR/start-acestep-ui.sh"
  cat > "$api" <<EOF
#!/usr/bin/env bash
# ACE-Step 1.5 REST API (MLX): http://127.0.0.1:8001  (interactive docs at /docs)
# Written by chimera-studio-install.sh.  PORT=8002 $api  uses another port.
cd "$ACE_DIR" || exit 1
export ACESTEP_LM_BACKEND=mlx TOKENIZERS_PARALLELISM=false
exec "$UV_BIN" run acestep-api --host 127.0.0.1 --port "\${PORT:-8001}"
EOF
  cat > "$ui" <<EOF
#!/usr/bin/env bash
# ACE-Step 1.5 Gradio UI (MLX): http://127.0.0.1:7861
# Port 7861, not 7860, so it can run next to the Hunyuan3D UI.
# Written by chimera-studio-install.sh.
cd "$ACE_DIR" || exit 1
export ACESTEP_LM_BACKEND=mlx TOKENIZERS_PARALLELISM=false
exec "$UV_BIN" run acestep --port "\${PORT:-7861}" --server-name 127.0.0.1 --language en --config_path "$ACE_DIT" --lm_model_path "$ACE_LM" --init_service true --backend mlx
EOF
  chmod +x "$api" "$ui"
}

step_music() {
  local marker="$DONE_DIR/acestep" d
  if [ -f "$marker" ]; then
    say "  already installed (delete $marker to reinstall); skipping"
    return 0
  fi
  if ! need_git; then return 10; fi
  if dry; then
    say "  [dry-run] would fetch ACE-Step @ ${ACE_SHA:0:10}, run 'uv sync' (uv comes from PyPI if you don't have it),"
    say "  [dry-run] then 'acestep-download --model $ACE_DIT' (also fetches the main model: vae, text encoder, 1.7B LM)"
    say "  [dry-run] and 'acestep-download --model $ACE_LM'; ~${MUSIC_GB} GB, then write .env and two launchers"
    return 0
  fi
  if ! find_uv && ! install_uv; then
    note "couldn't find or install uv; run 'brew install uv' (or see https://docs.astral.sh/uv/), then re-run"
    return 1
  fi
  say "  using uv: $UV_BIN"
  git_pinned "$ACE_URL" "$ACE_SHA" "$ACE_DIR" || return 1
  say "  uv sync (Python packages from the repo's lockfile; may fetch a Python 3.11/3.12 if you have none)"
  if ! ( cd "$ACE_DIR" && "$UV_BIN" sync ); then note "uv sync failed; re-run to retry"; return 1; fi
  say "  downloading $ACE_DIT (plus the main model on the first call)"
  if ! retry 3 20 bash -c 'cd "$1" && "$2" run acestep-download --model "$3"' _ "$ACE_DIR" "$UV_BIN" "$ACE_DIT"; then
    note "download of $ACE_DIT failed; re-run to resume"
    return 1
  fi
  say "  downloading $ACE_LM"
  if ! retry 3 20 bash -c 'cd "$1" && "$2" run acestep-download --model "$3"' _ "$ACE_DIR" "$UV_BIN" "$ACE_LM"; then
    note "download of $ACE_LM failed; re-run to resume"
    return 1
  fi
  for d in vae Qwen3-Embedding-0.6B "$ACE_DIT" "$ACE_LM"; do
    if [ ! -d "$ACE_DIR/checkpoints/$d" ]; then note "checkpoints/$d is missing after the download"; return 1; fi
  done
  write_ace_env || { note "could not write $ACE_DIR/.env"; return 1; }
  write_launchers || { note "could not write the launcher scripts"; return 1; }
  if ! command -v ffmpeg >/dev/null 2>&1; then
    say "  note: no ffmpeg on PATH. WAV/FLAC export works; MP3/Opus/AAC needs 'brew install ffmpeg' (not done here)."
  fi
  printf 'ace=%s dit=%s lm=%s date=%s\n' "$ACE_SHA" "$ACE_DIT" "$ACE_LM" "$(date +%Y-%m-%d)" > "$marker"
  return 0
}

# ---- the Ollama steps ---------------------------------------------------------------------
step_image() { pull_model "$IMAGE_MODEL"; }

step_tts() {
  if [ "$TTS_MODEL" = "phonon" ] && [ "$OLLAMA_READY" = "1" ] && [ -n "$OLLAMA_VER" ] && ! ver_ge "$OLLAMA_VER" "0.40.9"; then
    note "phonon needs Ollama 0.40.9 or newer (you have $OLLAMA_VER): update Ollama, then re-run"
    return 10
  fi
  pull_model "$TTS_MODEL"
}

step_vision() { pull_model "$VISION_MODEL"; }
step_planner() { pull_model "$PLANNER_MODEL"; }

# ---- running steps and reporting ------------------------------------------------------------
run_step() {  # <id> <label> <function>
  local id="$1" label="$2" fn="$3" t0 rc status
  hdr "$label"
  if ! want "$id"; then
    say "  skipped (SKIP=$SKIP)"
    RESULTS="${RESULTS}${label}|skipped|SKIP setting|0"$'\n'
    return 0
  fi
  STEP_NOTE=""
  CURRENT_STEP="$label"
  t0=$SECONDS
  "$fn"
  rc=$?
  CURRENT_STEP=""
  case "$rc" in
    0)  if dry; then status="planned"; else status="ok"; fi ;;
    10) status="SKIPPED" ;;
    *)  status="FAILED"; if [ -z "$STEP_NOTE" ]; then STEP_NOTE="exit code $rc"; fi ;;
  esac
  if [ -n "$STEP_NOTE" ]; then say "  -> $status: $STEP_NOTE"; else say "  -> $status"; fi
  RESULTS="${RESULTS}${label}|${status}|${STEP_NOTE}|$((SECONDS - t0))"$'\n'
  return 0
}

summary() {
  local name status detail secs failed=0
  say ""
  say "================================================================"
  say "SUMMARY"
  say "================================================================"
  while IFS='|' read -r name status detail secs; do
    [ -n "$name" ] || continue
    say "$(printf '  %-42s %-8s %7s  %s' "$name" "$status" "$(fmt_secs "${secs:-0}")" "$detail")"
    if [ "$status" = "FAILED" ] || [ "$status" = "interrupted" ]; then failed=1; fi
  done <<EOF
$RESULTS
EOF
  return "$failed"
}

closing_notes() {
  say ""
  say "Where things are"
  say "  Hunyuan3D UI   $HY_DIR/launch.sh   -> http://localhost:7860   (meshes land in outputs/ beside it)"
  say "  ACE-Step API   $TOOLS_DIR/start-acestep-api.sh   -> http://127.0.0.1:8001/docs"
  say "  ACE-Step UI    $TOOLS_DIR/start-acestep-ui.sh    -> http://127.0.0.1:7861"
  say "  Ollama models  ollama list"
  if [ -n "$LOG_FILE" ]; then say "  This run's log $LOG_FILE"; fi
  if [ "$PLANNER_GB" -ge 50 ] 2>/dev/null; then
    say ""
    say "Memory: the ${PLANNER_GB} GB planner leaves only a few GB of the Studio's ~72 GB usable, so image, vision and"
    say "3D jobs run only while it is unloaded."
  fi
  say ""
  say "Licences: Hunyuan3D is under the Tencent Hunyuan 3D 2.1 Community License, which does not apply in the"
  say "EU, UK or South Korea; read it before lending it out. ACE-Step's code and its XL turbo model are MIT."
  say ""
  say "Run this script again any time: finished steps are skipped, failed or skipped ones are retried."
}

on_interrupt() {
  echo
  if [ -n "$CURRENT_STEP" ]; then RESULTS="${RESULTS}${CURRENT_STEP}|interrupted|stopped by you; re-run to resume|0"$'\n'; fi
  say "Interrupted. Nothing finished is lost; run the script again to resume."
  summary
  exit 130
}

# ---- main --------------------------------------------------------------------------------------
main() {
  local mem_gb rc=0
  while [ $# -gt 0 ]; do
    case "$1" in
      -n|--dry-run) DRY_RUN=1 ;;
      -h|--help) usage; exit 0 ;;
      *) printf 'unknown option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
  done

  [ "$(uname -s)" = "Darwin" ] || die "this installer is for macOS (run it on the Mac Studio)."
  [ "$(uname -m)" = "arm64" ] || die "this needs Apple Silicon (arm64). If this IS an Apple Silicon Mac, your Terminal is running under Rosetta: quit it, Get Info on Terminal.app, untick 'Open using Rosetta', and try again."
  # A Terminal with an activated venv would leak these into every installer below (this script's process tree only).
  unset VIRTUAL_ENV PYTHONHOME PYTHONPATH
  if [ "$(id -u)" = "0" ] && [ "${ALLOW_ROOT:-0}" != "1" ]; then
    die "don't run this with sudo or as root (Homebrew and the Python tools refuse or misbehave). Run it as your normal user."
  fi
  mem_gb=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1073741824 ))
  if [ "$mem_gb" -lt 90 ] && [ "${FORCE:-0}" != "1" ]; then
    die "this Mac reports ${mem_gb} GB of memory. This lineup is sized for the 96 GB M3 Ultra Studio (gpt-oss:120b alone is ~65 GB). Run it on the Studio, or set FORCE=1 / pick smaller models (see --help)."
  fi
  if [ -x /opt/homebrew/bin/brew ]; then PATH="/opt/homebrew/bin:$PATH"; fi

  if ! dry; then
    mkdir -p "$TOOLS_DIR" "$DONE_DIR" || die "can't create $TOOLS_DIR"
    LOG_FILE="$TOOLS_DIR/install-$(date +%Y%m%d-%H%M%S).log"
    : > "$LOG_FILE" || LOG_FILE=""
  fi
  trap on_interrupt INT TERM

  say "Chimera hub installer ($(date '+%Y-%m-%d %H:%M'))"
  if dry; then say "DRY RUN: showing the plan, changing nothing."; fi
  say "  tools folder : $TOOLS_DIR"
  say "  order        : Hunyuan3D 2.1 -> $IMAGE_MODEL -> ACE-Step ($ACE_DIT + $ACE_LM) -> $TTS_MODEL -> $VISION_MODEL -> $PLANNER_MODEL (last)"
  if [ -n "$SKIP" ]; then say "  skipping     : $SKIP"; fi
  say ""
  if ! setup_ollama; then say "Ollama: $OLLAMA_NOTE"; fi
  if ! check_disk; then
    say ""
    say "Stopping before downloading anything."
    exit 1
  fi
  if ! dry && command -v caffeinate >/dev/null 2>&1; then
    caffeinate -i -s -w $$ >/dev/null 2>&1 &
    say "  (keeping the Mac awake while this runs)"
  fi

  run_step hunyuan "1  Hunyuan3D 2.1 (3D meshes)"         step_hunyuan
  run_step image   "2  Image: $IMAGE_MODEL"                step_image
  run_step music   "3a Music: ACE-Step 1.5 XL"             step_music
  run_step tts     "3b Speech: $TTS_MODEL"                 step_tts
  run_step vision  "4  Vision: $VISION_MODEL"              step_vision
  run_step planner "5  Planner: $PLANNER_MODEL (last)"     step_planner

  summary || rc=1
  if dry; then
    say ""
    say "Dry run only: nothing was changed."
  else
    if [ "$OLLAMA_READY" = "1" ]; then
      say ""
      say "ollama list"
      ol list 2>&1 | while IFS= read -r line; do say "  $line"; done
    fi
    closing_notes
  fi
  return "$rc"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
  exit $?
fi

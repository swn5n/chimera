#!/bin/bash
# Score stock models on the helper eval set with Chimera's own prompts and request options.
#
#   bash run_baselines.sh                          # qwen3:1.7b, qwen3:4b, qwen3:8b + the embedding check
#   MODELS="qwen3.5:4b qwen3.5:9b" bash run_baselines.sh
#   THINK=false bash run_baselines.sh              # also score the non-thinking mode (Chimera sends no think field)
#
# Pulls whatever isn't installed yet: qwen3:1.7b 1.4 GB, qwen3:4b 2.5 GB, qwen3:8b 5.2 GB,
# qwen3-embedding:0.6b about 0.6 GB. Roughly 20-40 minutes on the Studio; best run while the
# Studio isn't lending, since other work on the GPU slows every timing down.
set -euo pipefail
cd "$(dirname "$0")"

MODELS=${MODELS:-"qwen3:1.7b qwen3:4b qwen3:8b"}
EMBED=${EMBED:-qwen3-embedding:0.6b}
THINK=${THINK:-}
HOST=${OLLAMA_HOST:-127.0.0.1:11434}
case "$HOST" in http://*|https://*) ;; *) HOST="http://$HOST" ;; esac
HOST=${HOST/0.0.0.0/127.0.0.1}
case "${HOST#*://}" in *:*) ;; *) HOST="$HOST:11434" ;; esac

PY=""
for p in python3 /usr/bin/python3 "$HOME/.local/bin/python3.11"; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys, json, urllib.request, http.server; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    PY=$p; break
  fi
done
[ -n "$PY" ] || { echo "Need Python 3.9 or newer as python3."; exit 1; }

if ! curl -sf "$HOST/api/version" >/dev/null; then
  echo "Ollama isn't answering at $HOST. Open Ollama, then run this again."; exit 1
fi
command -v caffeinate >/dev/null 2>&1 && { caffeinate -i -w $$ & } # keep the Mac awake until this finishes

echo "== Checking the helper-model code ($("$PY" --version))"
"$PY" -m unittest discover -s tests -t . >/dev/null 2>&1 || { "$PY" -m unittest discover -s tests -t .; exit 1; }
"$PY" tools/check_prompts_sync.py

for m in $MODELS $EMBED; do
  if ! curl -sf "$HOST/api/show" -d "{\"model\": \"$m\"}" >/dev/null; then
    echo "== Pulling $m"
    ollama pull "$m"
  fi
done

for m in $MODELS; do
  echo "== Scoring $m (as Chimera asks)"
  "$PY" runner/run_eval.py --model "$m" --host "$HOST"
  if [ -n "$THINK" ]; then
    echo "== Scoring $m with think=$THINK"
    "$PY" runner/run_eval.py --model "$m" --host "$HOST" --think "$THINK" --tag "think-$THINK"
  fi
done
echo "== Embedding check with $EMBED"
"$PY" runner/run_eval.py --model "$EMBED" --host "$HOST" --jobs embed
GO=$(command -v go || true); [ -z "$GO" ] && [ -x /opt/homebrew/bin/go ] && GO=/opt/homebrew/bin/go
if [ -n "$GO" ]; then
  echo "== Checking the Python port against Chimera's Go code on every reply"
  "$PY" tools/check_go_parity.py --go "$GO" || echo "(parity differences: see results/GO_PARITY.txt)"
fi
"$PY" runner/report.py
echo
echo "Done. Summary: helper-model/results/BASELINES.md"

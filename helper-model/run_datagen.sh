#!/bin/bash
# Generate the helper model's synthetic training data on the Studio.
#
#   bash run_datagen.sh                  # a 15-minute smoke run of every stage, then the overnight run (7 to 8 hours)
#   SIZE=smoke bash run_datagen.sh       # only the smoke run
#   EFFORT=high bash run_datagen.sh      # the teacher reasons harder (better, slower)
#
# Before starting, switch lending off in Chimera, so pool work doesn't land on the GPU while the 65 GB
# teacher is loaded. It's resumable: if it stops, or you stop it with Ctrl-C, run the same command again
# and it continues where it left off. Results: data/sft/ (training files) and data/STATS.md.
set -euo pipefail
cd "$(dirname "$0")"

SIZE=${SIZE:-night}
EFFORT=${EFFORT:-}
TEACHER=gpt-oss:120b
WORKERS="qwen3:4b-instruct-2507-q4_K_M qwen3:1.7b qwen3:8b"
HOST=${OLLAMA_HOST:-127.0.0.1:11434}
case "$HOST" in http://*|https://*) ;; *) HOST="http://$HOST" ;; esac
HOST=${HOST/0.0.0.0/127.0.0.1}
case "${HOST#*://}" in *:*) ;; *) HOST="$HOST:11434" ;; esac

PY=""
for p in python3 /usr/bin/python3 "$HOME/.local/bin/python3.11"; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    PY=$p; break
  fi
done
[ -n "$PY" ] || { echo "Need Python 3.9 or newer as python3."; exit 1; }
if ! curl -sf "$HOST/api/version" >/dev/null; then
  echo "Ollama isn't answering at $HOST. Open Ollama, then run this again."; exit 1
fi
command -v caffeinate >/dev/null 2>&1 && { caffeinate -i -w $$ & } # keep the Mac awake until this finishes

echo "== Checking the helper-model code"
"$PY" -m unittest discover -s tests -t . >/dev/null 2>&1 || { "$PY" -m unittest discover -s tests -t .; exit 1; }
"$PY" tools/check_prompts_sync.py

for m in $TEACHER $WORKERS; do
  if ! curl -sf "$HOST/api/show" -d "{\"model\": \"$m\"}" >/dev/null; then
    echo "== Pulling $m"
    ollama pull "$m"
  fi
done

mkdir -p data
echo "== Smoke run: every stage on a few items (about 15 minutes), into data/smoke/"
if ! "$PY" -m datagen.run --size smoke --data-dir data/smoke --host "$HOST" ${EFFORT:+--effort "$EFFORT"} 2>&1 | tee -a data/smoke.log; then
  echo
  echo "The smoke run stopped; nothing else was started. See data/smoke/STOPPED.md and data/smoke.log."
  exit 1
fi
[ "$SIZE" = smoke ] && { echo; echo "Smoke run done: data/smoke/STATS.md"; exit 0; }

echo
echo "== Overnight run (about 7 to 8 hours), into data/. Ctrl-C is safe: run this again to continue."
if ! "$PY" -m datagen.run --size "$SIZE" --data-dir data --host "$HOST" ${EFFORT:+--effort "$EFFORT"} 2>&1 | tee -a data/night.log; then
  echo
  echo "The run stopped early. See data/STOPPED.md (if it exists) and data/night.log; run this again to continue."
  exit 1
fi
echo
echo "Done. Training files: data/sft/train.jsonl and valid.jsonl. Summary: data/STATS.md"

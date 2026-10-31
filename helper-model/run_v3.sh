#!/bin/bash
# Helper model v3: what v2 still missed. Reviews whose checks list the task's requirements first and redo the
# counts and calculations; more flaws of the kinds v2 let through; long batches planned in 3 to 5 groups. Then
# training (1 epoch) and the eval, in one go.
#
#   bash run_v3.sh                 # a 3-minute test, about 5 hours of data, then about 2 hours of training and the eval
#   STEP=data bash run_v3.sh       # stop after the data (data/sft-v3/ and data/STATS-v3.md)
#   EFFORT=high bash run_v3.sh     # the teacher reasons harder (better, slower)
#
# Builds on v1's and v2's data in data/ (nothing there is changed; v3's files are new). Switch lending off in
# Chimera first. Resumable: if it stops, or you stop it with Ctrl-C, run the same command again and it carries on.
set -euo pipefail
cd "$(dirname "$0")"

STEP=${STEP:-all}
EFFORT=${EFFORT:-}
TEACHER=gpt-oss:120b
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
curl -sf "$HOST/api/version" >/dev/null || { echo "Ollama isn't answering at $HOST. Open Ollama, then run this again."; exit 1; }
[ -s data/seeds.jsonl ] || { echo "No v1 data in data/ (run_datagen.sh makes it); v3 builds on it."; exit 1; }
[ -s data/review_items2.jsonl ] || { echo "No v2 data in data/ (run_v2.sh makes it); v3 builds on it."; exit 1; }
command -v caffeinate >/dev/null 2>&1 && { caffeinate -i -w $$ & } # keep the Mac awake until this finishes

echo "== Checking the helper-model code"
"$PY" -m unittest discover -s tests -t . >/dev/null 2>&1 || { "$PY" -m unittest discover -s tests -t .; exit 1; }
"$PY" tools/check_prompts_sync.py
GO=$(command -v go || true)
[ -z "$GO" ] && [ -x /opt/homebrew/bin/go ] && GO=/opt/homebrew/bin/go
if [ -n "$GO" ]; then  # Chimera's own Go decoding on every saved reply, including the check-first ones
  set +e; "$PY" tools/check_go_parity.py --go "$GO"; rc=$?; set -e
  [ "$rc" -eq 1 ] && { echo "Chimera's Go code reads some replies differently from the port; see results/GO_PARITY.txt"; exit 1; }
  [ "$rc" -ne 0 ] && echo "(The Go parity check couldn't run; carrying on without it.)"
fi
if ! curl -sf "$HOST/api/show" -d "{\"model\": \"$TEACHER\"}" >/dev/null; then
  echo "== Pulling $TEACHER"
  ollama pull "$TEACHER"
fi

mkdir -p data
# The worked-check instruction as a prompt, on v2 and the untrained base: does asking for it help by itself?
for m in chimera-helper:v2 qwen3:4b-instruct-2507-q4_K_M; do
  if curl -sf "$HOST/api/show" -d "{\"model\": \"$m\"}" >/dev/null; then
    echo "== Reviewer test with worked checks: $m (a minute or two)"
    "$PY" runner/run_eval.py --model "$m" --host "$HOST" --jobs reviewer --variant check-working 2>&1 | tail -1 || true
  fi
done

if [ ! -s data/smoke/review_items2.jsonl ]; then
  echo "== v2's smoke run first (v3's smoke run builds on it), into data/smoke/"
  "$PY" -m datagen.run --size smoke --data-dir data/smoke --stages v2 --host "$HOST" ${EFFORT:+--effort "$EFFORT"} 2>&1 | tee -a data/smoke-v2.log \
    || { echo; echo "The smoke run stopped. See data/smoke/STOPPED.md and data/smoke-v2.log."; exit 1; }
fi
echo "== Smoke run of v3's stages (about 15 minutes), into data/smoke/"
if ! "$PY" -m datagen.run --size smoke --data-dir data/smoke --stages v3 --host "$HOST" ${EFFORT:+--effort "$EFFORT"} 2>&1 | tee -a data/smoke-v3.log; then
  echo
  echo "The v3 smoke run stopped; nothing else was started. See data/smoke/STOPPED.md and data/smoke-v3.log."
  exit 1
fi

echo
echo "== v3 data (about 5 hours), into data/. Ctrl-C is safe: run this again to continue."
if ! "$PY" -m datagen.run --size night --data-dir data --stages v3 --host "$HOST" ${EFFORT:+--effort "$EFFORT"} 2>&1 | tee -a data/v3.log; then
  echo
  echo "The v3 run stopped early. See data/STOPPED.md (if it exists) and data/v3.log; run this again to continue."
  exit 1
fi
for f in data/sft-v3/train.jsonl data/sft-v3/valid.jsonl; do
  "$PY" tools/check_overlap.py "$f" || { echo "Some of $f overlaps the eval set; not training on it."; exit 1; }
done
echo
sed -n '/^## Examples/,/^## Stages/p' data/STATS-v3.md | sed '$d'
[ "$STEP" = data ] && { echo "Data done: data/sft-v3/ and data/STATS-v3.md"; exit 0; }

echo "== Training v3 (1 epoch) and scoring it"
NAME=v3 EPOCHS=1 DATA=data/sft-v3 bash run_train.sh

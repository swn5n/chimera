#!/bin/bash
# Helper model v2: better review data (a check of each requirement before every verdict, more correct answers and
# more subtle flaws), the planner's misses from v1, then training (1 epoch) and the eval, in one go.
#
#   bash run_v2.sh                 # about 5 hours of data, then about 1.5 hours of training and the eval
#   STEP=data bash run_v2.sh       # stop after the data (data/sft-v2/ and data/STATS-v2.md)
#   EFFORT=high bash run_v2.sh     # the teacher reasons harder (better, slower)
#
# Builds on v1's data in data/ (nothing there is changed; v2's files are new). Switch lending off in Chimera
# first. Resumable: if it stops, or you stop it with Ctrl-C, run the same command again and it carries on.
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
[ -s data/seeds.jsonl ] || { echo "No v1 data in data/ (run_datagen.sh makes it); v2 builds on it."; exit 1; }
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
if [ ! -s data/smoke/seeds.jsonl ]; then
  echo "== v1 smoke run first (v2's smoke run builds on it), into data/smoke/"
  "$PY" -m datagen.run --size smoke --data-dir data/smoke --host "$HOST" ${EFFORT:+--effort "$EFFORT"} 2>&1 | tee -a data/smoke.log \
    || { echo; echo "The smoke run stopped. See data/smoke/STOPPED.md and data/smoke.log."; exit 1; }
fi
echo "== Smoke run of v2's stages (about 15 minutes), into data/smoke/"
if ! "$PY" -m datagen.run --size smoke --data-dir data/smoke --stages v2 --host "$HOST" ${EFFORT:+--effort "$EFFORT"} 2>&1 | tee -a data/smoke-v2.log; then
  echo
  echo "The v2 smoke run stopped; nothing else was started. See data/smoke/STOPPED.md and data/smoke-v2.log."
  exit 1
fi

echo
echo "== v2 data (about 5 hours), into data/. Ctrl-C is safe: run this again to continue."
if ! "$PY" -m datagen.run --size night --data-dir data --stages v2 --host "$HOST" ${EFFORT:+--effort "$EFFORT"} 2>&1 | tee -a data/v2.log; then
  echo
  echo "The v2 run stopped early. See data/STOPPED.md (if it exists) and data/v2.log; run this again to continue."
  exit 1
fi
for f in data/sft-v2/train.jsonl data/sft-v2/valid.jsonl; do
  "$PY" tools/check_overlap.py "$f" || { echo "Some of $f overlaps the eval set; not training on it."; exit 1; }
done
echo
sed -n '/^## Examples/,/^## Stages/p' data/STATS-v2.md | sed '$d'
[ "$STEP" = data ] && { echo "Data done: data/sft-v2/ and data/STATS-v2.md"; exit 0; }

echo "== Training v2 (1 epoch) and scoring it"
NAME=v2 EPOCHS=1 DATA=data/sft-v2 bash run_train.sh

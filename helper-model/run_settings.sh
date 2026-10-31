#!/bin/bash
# The same trained weights under other settings, to see whether a problem is the training or the settings:
#   <name>-t02    temperature 0.2      (the base's default, which the helper inherits, is 0.7)
#   <name>-t0     temperature 0
#   <name>-bf16   not quantized, default temperature (planner only: the slow one)
# Each with replies capped at 4,096 tokens (Chimera sets no cap, so a reply that never ends hangs a task).
#
#   bash run_settings.sh             # chimera-helper:v3, about 15 minutes
#   NAME=v2 bash run_settings.sh
#
# Nothing is retrained; the variants reuse the run's GGUF files (the bf16 one adds about 8 GB to Ollama's store).
set -euo pipefail
cd "$(dirname "$0")"
NAME=${NAME:-v3}
RUN=$HOME/chimera-tools/helper-train/$NAME
HOST=${OLLAMA_HOST:-127.0.0.1:11434}
case "$HOST" in http://*|https://*) ;; *) HOST="http://$HOST" ;; esac
HOST=${HOST/0.0.0.0/127.0.0.1}
case "${HOST#*://}" in *:*) ;; *) HOST="$HOST:11434" ;; esac
PY=""
for p in python3 /usr/bin/python3 "$HOME/.local/bin/python3.11"; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then PY=$p; break; fi
done
[ -n "$PY" ] || { echo "Need Python 3.9 or newer as python3."; exit 1; }
curl -sf "$HOST/api/version" >/dev/null || { echo "Ollama isn't answering at $HOST. Open Ollama, then run this again."; exit 1; }
for f in base.Modelfile helper-q4_k_m.gguf helper-bf16.gguf; do
  [ -s "$RUN/$f" ] || { echo "No $RUN/$f: train $NAME first (run_train.sh)."; exit 1; }
done
command -v caffeinate >/dev/null 2>&1 && { caffeinate -i -w $$ & }

variant() {  # variant <suffix> <gguf> [temperature]
  local f="$RUN/Modelfile.$1"
  "$PY" train/make_modelfile.py --base "$RUN/base.Modelfile" --from "$RUN/$2" --out "$f" --num-predict 4096 ${3:+--temperature "$3"}
  echo "== chimera-helper:$NAME-$1"
  ollama create "chimera-helper:$NAME-$1" -f "$f" >/dev/null
}
variant t02 helper-q4_k_m.gguf 0.2
variant t0 helper-q4_k_m.gguf 0
variant bf16 helper-bf16.gguf

"$PY" runner/run_eval.py --model "chimera-helper:$NAME-t02" --host "$HOST" 2>&1 | tail -1
"$PY" runner/run_eval.py --model "chimera-helper:$NAME-t0" --host "$HOST" 2>&1 | tail -1
"$PY" runner/run_eval.py --model "chimera-helper:$NAME-bf16" --host "$HOST" --jobs planner 2>&1 | tail -1
"$PY" runner/report.py >/dev/null

latest() { ls -td results/runs/*-"$1" 2>/dev/null | head -1; }
RUNS=("$(latest "chimera-helper-$NAME")" "$(latest "chimera-helper-$NAME-t02")" "$(latest "chimera-helper-$NAME-t0")" "$(latest "chimera-helper-$NAME-bf16")")
echo
"$PY" runner/compare.py --jobs planner,reviewer,gate "${RUNS[@]}" | grep -E "^## |right|^\| case"
echo
echo "Done. Per case: python3 runner/compare.py ${RUNS[*]}"

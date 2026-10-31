#!/bin/bash
# The trained helper at higher-precision quantizations than Q4_K_M, each scored in full at its normal settings
# (temperature 0.7) with replies capped at 4,096 tokens. v3 unquantized (bf16) never wrote the stray "depends"
# key that v3 at Q4_K_M wrote at every temperature, so the question is the smallest quantization that keeps that.
#
#   bash run_quants.sh               # chimera-helper:v3 at Q5_K_M, Q6_K and Q8_0, about 20 minutes
#   NAME=v2 QUANTS="Q6_K" bash run_quants.sh
#
# Nothing is retrained. Each GGUF is made from the run's bf16 one with the llama-quantize run_train.sh built, and
# takes 3 to 4.5 GB in the run folder plus the same again in Ollama's store.
set -euo pipefail
cd "$(dirname "$0")"
NAME=${NAME:-v3}
QUANTS=${QUANTS:-Q5_K_M Q6_K Q8_0}
WORK=$HOME/chimera-tools/helper-train
RUN=$WORK/$NAME
QBIN=$WORK/llama.cpp/build/bin/llama-quantize
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
for f in "$RUN/base.Modelfile" "$RUN/helper-bf16.gguf" "$QBIN"; do
  [ -s "$f" ] || { echo "Missing $f: train $NAME first (run_train.sh builds the quantizer)."; exit 1; }
done
FREE_GB=$(df -g "$HOME" | awk 'NR==2 {print $4}')
[ "${FREE_GB:-0}" -ge 25 ] || { echo "Needs about 25 GB of free disk; there are ${FREE_GB} GB."; exit 1; }
command -v caffeinate >/dev/null 2>&1 && { caffeinate -i -w $$ & }

TAGS=()
for q in $QUANTS; do
  lq=$(echo "$q" | tr 'A-Z' 'a-z')
  gg="$RUN/helper-$lq.gguf"
  if [ ! -s "$gg" ]; then
    echo "== Quantizing to $q"
    "$QBIN" "$RUN/helper-bf16.gguf" "$gg.part" "$q" >> "$RUN/quants.log" 2>&1 || { echo "Quantizing to $q failed; see $RUN/quants.log"; exit 1; }
    mv "$gg.part" "$gg"
  fi
  tag="chimera-helper:$NAME-$lq"
  "$PY" train/make_modelfile.py --base "$RUN/base.Modelfile" --from "$gg" --out "$RUN/Modelfile.$lq" --num-predict 4096
  echo "== $tag ($(du -h "$gg" | cut -f1))"
  ollama create "$tag" -f "$RUN/Modelfile.$lq" >/dev/null
  "$PY" runner/run_eval.py --model "$tag" --host "$HOST" 2>&1 | tail -1
  TAGS+=("$tag")
done
"$PY" runner/report.py >/dev/null

latest() { ls -td results/runs/*-"$1" 2>/dev/null | head -1; }
RUNS=("$(latest "chimera-helper-$NAME")")
for t in "${TAGS[@]}"; do RUNS+=("$(latest "${t/:/-}")"); done
B=$(latest "chimera-helper-$NAME-bf16"); [ -n "$B" ] && RUNS+=("$B")
echo
"$PY" runner/compare.py --jobs planner,reviewer,gate "${RUNS[@]}" | grep -E "^## |right|^\| case"
echo
echo "Done. Per case: python3 runner/compare.py ${RUNS[*]}"

#!/bin/bash
# Train the Chimera helper model and score it.
#
#   bash run_train.sh                  # LoRA on Qwen3-4B-Instruct-2507 -> Ollama as chimera-helper:v1 -> eval
#   NAME=v2 EPOCHS=3 bash run_train.sh # another run, with its own folder and Ollama name
#   LR=1e-5 bash run_train.sh          # a different peak learning rate (default 2e-5)
#   DATA=data/sft-v2 bash run_train.sh # other training files (default data/sft)
#   QUANT=Q4_K_M bash run_train.sh     # another quantization (default Q5_K_M; see results/QUANT-v3.md)
#
# About an hour on the Studio, most of it training. Switch lending off in Chimera first. Finished steps are
# skipped when you run it again (markers TRAINED, MERGED, IMPORTED; macOS names are case-insensitive, so no marker
# may share a name with a folder like fused/). Model files go in ~/chimera-tools/helper-train/<name>/ (about 20 GB:
# adapters, the merged model, and its GGUFs at bf16 and Q5_K_M); llama.cpp and the Python environments sit beside them;
# the scores go in results/ like the baselines, with a summary in results/TRAINING-<name>.md.
set -euo pipefail
cd "$(dirname "$0")"

NAME=${NAME:-v1}
EPOCHS=${EPOCHS:-2}
LR=${LR:-2e-5}
DATA=${DATA:-data/sft}
QUANT=${QUANT:-Q5_K_M}  # v3 at Q4_K_M wrote a stray "depends" key in 1 of 13 plan steps, and twice got stuck in it; Q5_K_M never did
NUM_PREDICT=${NUM_PREDICT:-4096}  # the helper's own cap on a reply (Chimera sets none, so a runaway reply would hang a task)
BASE_HF=Qwen/Qwen3-4B-Instruct-2507
BASE_OLLAMA=qwen3:4b-instruct-2507-q4_K_M
TAG=chimera-helper:$NAME
WORK=$HOME/chimera-tools/helper-train
RUN=$WORK/$NAME
VENV=$WORK/.venv
VPY=$VENV/bin/python
HOST=${OLLAMA_HOST:-127.0.0.1:11434}
case "$HOST" in http://*|https://*) ;; *) HOST="http://$HOST" ;; esac
HOST=${HOST/0.0.0.0/127.0.0.1}
case "${HOST#*://}" in *:*) ;; *) HOST="$HOST:11434" ;; esac

mkdir -p "$RUN"
LOG=$RUN/run.log
say() { echo "== $*" | tee -a "$LOG"; }
die() { echo; echo "STOPPED: $*" | tee -a "$LOG"; exit 1; }

[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] || die "MLX needs an Apple Silicon Mac."
PY=""
for p in python3 /usr/bin/python3 "$HOME/.local/bin/python3.11"; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then PY=$p; break; fi
done
[ -n "$PY" ] || die "Need Python 3.9 or newer as python3."
curl -sf "$HOST/api/version" >/dev/null || die "Ollama isn't answering at $HOST. Open Ollama, then run this again."
command -v ollama >/dev/null 2>&1 || die "The ollama command isn't on PATH."
[ -s "$DATA/train.jsonl" ] && [ -s "$DATA/valid.jsonl" ] || die "No training data in $DATA/. Run run_datagen.sh first."
FREE_GB=$(df -g "$HOME" | awk 'NR==2 {print $4}')
if [ ! -f "$RUN/MERGED" ] && [ "${FREE_GB:-0}" -lt 40 ]; then die "Needs about 40 GB of free disk; there are ${FREE_GB} GB."; fi
command -v caffeinate >/dev/null 2>&1 && { caffeinate -i -w $$ & }
say "Run $NAME started $(date) — $TAG"

# 1. MLX-LM in its own environment (not needed once training and merging are done)
UV=$(command -v uv || true)
[ -z "$UV" ] && [ -x /opt/homebrew/bin/uv ] && UV=/opt/homebrew/bin/uv
if [ ! -f "$RUN/TRAINED" ] || [ ! -f "$RUN/MERGED" ]; then
  [ -n "$UV" ] || die "uv isn't installed (brew install uv); it sets up MLX-LM."
  [ -x "$VPY" ] || { "$UV" venv --python 3.12 "$VENV" 2>&1 | tee -a "$LOG" || die "Couldn't create $VENV"; }
  # The exact packages v1 was trained with; sync also takes out anything else that got installed here.
  "$UV" pip sync --python "$VPY" train/mlx-requirements.txt 2>&1 | tee -a "$LOG" || die "Couldn't install MLX-LM; see $LOG"
  if "$VPY" -m mlx_lm.lora --help >/dev/null 2>&1; then
    LORA=("$VPY" -m mlx_lm.lora); FUSE=("$VPY" -m mlx_lm.fuse)
  elif "$VPY" -m mlx_lm lora --help >/dev/null 2>&1; then
    LORA=("$VPY" -m mlx_lm lora); FUSE=("$VPY" -m mlx_lm fuse)
  else
    die "MLX-LM is installed but its LoRA trainer won't start; see $LOG"
  fi
  say "MLX-LM $("$VPY" -c 'import mlx_lm; print(mlx_lm.__version__)'), Python $("$VPY" -c 'import platform; print(platform.python_version())')"
fi

# 2. Train the LoRA
if [ ! -f "$RUN/TRAINED" ]; then
  [ -d "$RUN/adapters" ] && mv "$RUN/adapters" "$RUN/adapters.partial-$(date +%Y%m%d-%H%M%S)"
  INFO=$("$PY" train/make_config.py --data "$DATA" --adapters "$RUN/adapters" --out "$RUN/lora.yaml" \
         --base "$BASE_HF" --epochs "$EPOCHS" --lr "$LR") || die "Couldn't write the training config."
  say "Training on $INFO. The first run downloads $BASE_HF (about 8 GB). Loss lines follow."
  "$PY" train/ollama_unload.py "$HOST" | tee -a "$LOG" || true
  if ! "${LORA[@]}" -c "$RUN/lora.yaml" --mask-prompt --grad-checkpoint 2>&1 | tee "$RUN/train.log"; then
    die "Training stopped; see $RUN/train.log. Run this again to start the training over."
  fi
  [ -f "$RUN/adapters/adapters.safetensors" ] || die "Training ended without saving adapters; see $RUN/train.log"
  date > "$RUN/TRAINED"
fi

# 3. Merge the LoRA into the model
if [ ! -f "$RUN/MERGED" ]; then
  say "Merging the LoRA into the model"
  rm -rf "$RUN/fused"
  if ! "${FUSE[@]}" --model "$BASE_HF" --adapter-path "$RUN/adapters" --save-path "$RUN/fused" 2>&1 | tee -a "$LOG"; then
    die "Merging failed; see $LOG"
  fi
  [ -f "$RUN/fused/config.json" ] || die "Merging wrote no model; see $LOG"
  date > "$RUN/MERGED"
fi

# 4. Into Ollama as a GGUF quantized to $QUANT (Q5_K_M; the baselines are Q4_K_M), prompted exactly
#    like the base model (its template copied from Ollama). llama.cpp's converter makes the GGUF and its
#    quantizer the $QUANT; both live in $WORK, the converter in its own Python environment (it pins an older
#    transformers than MLX-LM uses). Ollama can import safetensors itself, but only into its own int4/int8/mxfp
#    formats, not llama.cpp's K-quants.
convert() {   # convert <outtype> <file>: the merged model, with the base model's tokenizer files, to GGUF
  "$CPY" train/gguf_source.py --base "$BASE_HF" --fused "$RUN/fused" --out "$RUN/gguf-src" 2>&1 | tee -a "$LOG" || return 1
  say "Converting to GGUF ($1)"
  "$CPY" "$LC/convert_hf_to_gguf.py" "$RUN/gguf-src" --outfile "$2.part" --outtype "$1" --model-name "Chimera Helper $NAME" \
    2>&1 | tee -a "$LOG" || return 1
  mv "$2.part" "$2"
}
build_quantizer() {   # just llama-quantize, CPU only, into $LC/build; needs Apple's command line tools (Homebrew does too)
  local cm
  xcode-select -p >/dev/null 2>&1 || { echo "No Apple command line tools (xcode-select --install)." >> "$LOG"; return 1; }
  cm=$(command -v cmake || true)
  [ -z "$cm" ] && [ -x /opt/homebrew/bin/cmake ] && cm=/opt/homebrew/bin/cmake
  if [ -z "$cm" ]; then
    "$UV" pip install --python "$CPY" cmake >> "$LOG" 2>&1 || return 1
    cm=$CVENV/bin/cmake
  fi
  "$cm" -S "$LC" -B "$LC/build" -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DGGML_METAL=OFF -DLLAMA_OPENSSL=OFF \
    -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=OFF -DLLAMA_BUILD_APP=OFF >> "$LOG" 2>&1 || return 1
  "$cm" --build "$LC/build" --config Release --target llama-quantize -j "$(sysctl -n hw.ncpu 2>/dev/null || echo 8)" >> "$LOG" 2>&1 || return 1
  [ -x "$LC/build/bin/llama-quantize" ]
}
if [ ! -f "$RUN/IMPORTED" ] || ! ollama show "$TAG" >/dev/null 2>&1; then
  if ! ollama show "$BASE_OLLAMA" --modelfile > "$RUN/base.Modelfile" 2>/dev/null; then
    ollama pull "$BASE_OLLAMA" && ollama show "$BASE_OLLAMA" --modelfile > "$RUN/base.Modelfile" || die "Couldn't read $BASE_OLLAMA's template."
  fi
  [ -n "$UV" ] || die "uv is needed for llama.cpp's converter (brew install uv)."
  LC=$WORK/llama.cpp
  CVENV=$WORK/.venv-convert
  CPY=$CVENV/bin/python
  if [ ! -f "$LC/convert_hf_to_gguf.py" ]; then
    say "Downloading llama.cpp"
    git clone --depth 1 https://github.com/ggml-org/llama.cpp "$LC" 2>&1 | tee -a "$LOG" || die "Couldn't download llama.cpp."
  fi
  if ! "$CPY" -c "import gguf, transformers, torch" >/dev/null 2>&1; then
    say "Setting up llama.cpp's converter in $CVENV"
    { [ -x "$CPY" ] || "$UV" venv --python 3.12 "$CVENV"; } 2>&1 | tee -a "$LOG" || die "Couldn't create $CVENV"
    # unsafe-best-match: pip's rule for the extra PyTorch index (best version from either index), not uv's
    # first-index rule, which takes years-old requests/urllib3/certifi from the PyTorch index.
    "$UV" pip install --python "$CPY" --index-strategy unsafe-best-match \
      -r "$LC/requirements/requirements-convert_hf_to_gguf.txt" 2>&1 | tee -a "$LOG" || die "Couldn't install llama.cpp's converter; see $LOG"
  fi
  GG=$RUN/helper-$(echo "$QUANT" | tr 'A-Z' 'a-z').gguf
  if [ ! -s "$GG" ]; then
    FREE_GB=$(df -g "$HOME" | awk 'NR==2 {print $4}')
    [ "${FREE_GB:-0}" -ge 15 ] || die "Needs about 15 GB of free disk for the GGUF files; there are ${FREE_GB} GB."
    QBIN=$LC/build/bin/llama-quantize   # built from the same llama.cpp as the converter
    if [ ! -x "$QBIN" ]; then
      say "Building llama.cpp's quantizer in $LC/build (a minute or two)"
      if ! build_quantizer; then
        QBIN=$(command -v llama-quantize || true)
        if [ -n "$QBIN" ]; then say "Couldn't build it (details in $LOG); using $QBIN instead"
        else say "Couldn't build it (details in $LOG), so this run makes a Q8_0 GGUF instead of $QUANT"; fi
      fi
    fi
    if [ -n "$QBIN" ]; then
      GGB=$RUN/helper-bf16.gguf
      [ -s "$GGB" ] || convert bf16 "$GGB" || die "Conversion failed; see $LOG"
      say "Quantizing to $QUANT with $QBIN"
      "$QBIN" "$GGB" "$GG.part" "$QUANT" >> "$LOG" 2>&1 || die "Quantizing failed; see $LOG"
      mv "$GG.part" "$GG"
    else
      GG=$RUN/helper-q8_0.gguf
      [ -s "$GG" ] || convert q8_0 "$GG" || die "Conversion failed; see $LOG"
    fi
  fi
  case "$GG" in
    *q8_0.gguf) [ "$QUANT" = Q8_0 ] && NOTE="GGUF Q8_0 made with llama.cpp" \
                  || NOTE="GGUF Q8_0 made with llama.cpp, not $QUANT (no quantizer; to redo it, delete $RUN/IMPORTED and run this again)" ;;
    *) NOTE="GGUF $QUANT made with llama.cpp (the baselines are Q4_K_M)" ;;
  esac
  "$PY" train/make_modelfile.py --base "$RUN/base.Modelfile" --from "$GG" --out "$RUN/Modelfile" --num-predict "$NUM_PREDICT" \
    || die "Couldn't write the Modelfile."
  NOTE="$NOTE, the base model's template, replies capped at $NUM_PREDICT tokens"
  say "Adding it to Ollama as $TAG"
  ollama create "$TAG" -f "$RUN/Modelfile" 2>&1 | tee -a "$LOG" || die "Ollama couldn't create $TAG; see $LOG"
  ollama show "$TAG" >/dev/null 2>&1 || die "$TAG isn't in Ollama after the import; see $LOG"
  echo "$NOTE" > "$RUN/import.txt"
  date > "$RUN/IMPORTED"
fi
say "In Ollama as $TAG: $(cat "$RUN/import.txt")"

# 5. Score it exactly as Chimera would call it
say "Scoring $TAG on the eval (a few minutes)"
"$PY" runner/run_eval.py --model "$TAG" --host "$HOST" 2>&1 | tee -a "$LOG" || die "The eval run failed; see $LOG"
"$PY" runner/report.py 2>&1 | tee -a "$LOG"
"$PY" train/summarize.py --name "$NAME" --run "$RUN" --model "$TAG" 2>&1 | tee -a "$LOG"
echo
sed -n '/^## Eval/,$p' "results/TRAINING-$NAME.md"
echo
echo "Done. Summary: helper-model/results/TRAINING-$NAME.md"

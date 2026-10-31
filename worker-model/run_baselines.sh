#!/bin/bash
# Hydra Worker 1.0: tonight's baseline A/B (docs/hydra-worker-plan.md, BASELINES 1 and 2, the base-model rule's
# untrained scores), in order of importance, so that whatever finishes by morning is useful. EVAL ONLY: everything it
# writes is model output for eval cases (results/runs*/, eval/frozen/), never training data.
#
#   bash run_baselines.sh                  # every stage below, in order. Resumable: run it again and it carries on
#   DRY_RUN=1 bash run_baselines.sh        # the plan, the estimates and the runners' first requests; calls no model
#   STAGES=a bash run_baselines.sh         # only some stages (a,b,g,c,d,e,f, run in that order)
#   touch data/baselines/STOP              # stop after the run in progress (the file is removed when it stops)
#   STOP_AT=07:30 bash run_baselines.sh    # don't start a run after 07:30 (the run in progress still finishes)
#
# Needs: Ollama running with the models below (nothing is downloaded), Blender 5.2.2 and 5.0.1 (tools/blenders.py),
# and CHIMERA_BIN (built here into data/baselines/bin/ if unset). Switch lending off in Chimera for clean timings (not a
# blocker). Each run is one runner call writing its own folder (results/runs/<time>-<model>-<prompt>-baseline/, and
# results/runs-tasks/ for T1); a finished one goes into data/baselines/done.txt and is skipped next time. The log is
# data/baselines/baselines.log (every stage and run timed, with its estimate); results/BASELINES.md is rewritten after
# every stage (runner/report.py). Before each run every other loaded model is unloaded, so gpt-oss:120b (65 GB) is
# never left beside a 27B; the runners themselves get --no-unload. At the end everything it loaded is unloaded.
#
# Samples (the plan: Blender and code 3, prose 1; fewer where 3 would make one model's stage a longer than about
# 90 minutes, recorded in each run's meta.json "samples" and in BASELINES.md):
#
#   model                           tok/s  thinks   tokens/reply  s/sample  samples  stage a   stage c
#   qwen3:14b                       ~52    yes      ~5,000        ~100      1        ~2 h      ~1.5 h   (over 90 min even at 1)
#   gemma4:12b-it-q4_K_M            ~65    yes      ~4,000        ~65       1        ~80 min   ~60 min
#   qwen3.8:27b                     ~60    medium   ~3,500        ~62       1        ~75 min   ~55 min
#   gpt-oss:120b                    ~82    yes      ~2,800        ~38       2        ~90 min   ~60 min
#   qwen3:8b                        ~91    yes      ~5,500        ~65       1        ~80 min   ~60 min
#   qwen3:4b-instruct-2507-q4_K_M   ~140   no       ~900          ~9        3        ~30 min   ~20 min
#
# tok/s: measured on the Studio for qwen3:4b-instruct (Oct 29 smoke, 139-143), qwen3:8b (Oct 30 verifier smoke, 88-96),
# qwen3.8:27b (Oct 29 contract smoke, 2,300-4,900 tokens in 40-80 s) and gpt-oss:120b (the plan's 82); the plan's
# estimates for qwen3:14b (47 at Q5_K_M) and Gemma (58 at Q5_K_M), a little more at Q4_K_M. Every model but the 4B
# thinks with think unset (Ollama's defaults: gemma4 on, qwen3.8 medium), and thinking now runs to the 16,384-token
# guard (only content is held to 6,144), so thinking models' times are the least certain: one reply that thinks to
# the guard takes 3-5 min on its own. A sample's time adds about 2 s of Blender (4 runs) and the prompt.
#
# Stages (about 23 h in all, so one night gets through stage a and part of b; the rest carries on the next night):
#   a. step_eval, the quick subset's W2, W3 and W4 cases (36: 33 Blender or code, 3 prose; no freezing needed), today's
#      prompt and the contract, per model in the order above: the two base candidates first (the base-model rule
#      needs their untrained contract scores), today's biggest pool worker, the teacher (the ceiling), the small ones.
#      About 7 h 50 min.
#   b. freeze.py: W1's plans (all 54: hydra:1.0, and gpt-oss:120b for the 10 its rule picks; about 10 min), then the
#      verified gpt-oss:120b dependency outputs of the quick subset's 12 W1 tasks (about 40 min). About 50 min.
#   c. step_eval, the quick subset's W1 steps (the first and last step of 12 frozen plans, up to 24), same models and
#      prompts. About 5 h 40 min.
#   d. task_eval T1 arms A, B, C, A2 (qwen3.8:27b the fixed combine model) on tonight's T1: the frozen Blender plans
#      (up to 12) and python-script plans (up to 10), quick-subset tasks first, the kinds alternated, in chunks of 4
#      tasks; each chunk runs all four arms (A and B first: the phase-1 gate), so every finished chunk compares.
#      About 19 min a task for the four arms: about 7 h for 22.
#   e. runner/report.py: results/BASELINES.md (also after every other stage). Seconds.
#   f. freeze.py: the rest of W1's dependency outputs (the other 42 tasks) and 10 in today's format from qwen3.8:27b,
#      for the full W1 later; nothing tonight reads them. About 2 h 30 min.
#   g. (added Oct 30; runs right after b) step_eval with thinking off ("think": false) for the two base candidates
#      (BASES), the contract prompt only, NOTHINK_SAMPLES samples (default 3; prose 1): first the quick subset's W2-W4
#      cases for each, then its W1 steps (when frozen). The base-model rule's score in the setting the trained worker
#      runs in: its template forces thinking off, and with think unset both models think into the 8K context (Gemma
#      stops there with no answer, Qwen3 shifts the context). Without thinking a reply takes 6-30 s. About 1 h 30 min.
#
# A tiny stage (the script's own test: one W2 case, qwen3:4b-instruct, both prompts, into a scratch folder):
#   MODELS=qwen3:4b-instruct-2507-q4_K_M CASES=w2-01 STAGES=a TAG=tiny BASE=$WM_SCRATCH/bl RUNS=$WM_SCRATCH/bl/runs \
#     REPORT=$WM_SCRATCH/bl/BASELINES.md bash run_baselines.sh
# Other settings: SAMPLES="qwen3:14b=2,gpt-oss:120b=3" (per model), T1_CHUNK=4, T1_BLENDER=12, T1_CODE=10,
# ARMS="A B C A2", COMBINE=qwen3.8:27b, REVIEW=0 (reviews per T1 result on gpt-oss:120b), FROZEN=eval/frozen,
# TASK_RUNS=results/runs-tasks, SKIP_TESTS=1, OLLAMA_HOST, WM_SCRATCH (Blender run folders; default data/scratch),
# NO_BLENDER=1 (stages a, c, d and g score without Blender: for testing this script only),
# BASES="qwen3:14b gemma4:12b-it-q4_K_M" and NOTHINK_SAMPLES=3 (stage g).
set -euo pipefail
cd "$(dirname "$0")"
HERE=$(pwd)

DRY_RUN=${DRY_RUN:-}
STAGES=${STAGES:-a,b,c,d,e,f,g}
MODELS=${MODELS:-"qwen3:14b gemma4:12b-it-q4_K_M qwen3.8:27b gpt-oss:120b qwen3:8b qwen3:4b-instruct-2507-q4_K_M"}
SAMPLES=${SAMPLES:-}
CASES=${CASES:-}
TAG=${TAG:-baseline}
BASE=${BASE:-data/baselines}
RUNS=${RUNS:-results/runs}
TASK_RUNS=${TASK_RUNS:-results/runs-tasks}
FROZEN=${FROZEN:-eval/frozen}
REPORT=${REPORT:-results/BASELINES.md}
T1_CHUNK=${T1_CHUNK:-4}
T1_BLENDER=${T1_BLENDER:-12}
T1_CODE=${T1_CODE:-10}
ARMS=${ARMS:-"A B C A2"}
COMBINE=${COMBINE:-qwen3.8:27b}
REVIEW=${REVIEW:-0}
BASES=${BASES:-"qwen3:14b gemma4:12b-it-q4_K_M"}
NOTHINK_SAMPLES=${NOTHINK_SAMPLES:-3}
STOP_AT=${STOP_AT:-}
NO_BLENDER=${NO_BLENDER:+--no-blender}
TEACHER=gpt-oss:120b
PLANNER=hydra:1.0
HOST=${OLLAMA_HOST:-127.0.0.1:11434}
case "$HOST" in http://*|https://*) ;; *) HOST="http://$HOST" ;; esac
HOST=${HOST/0.0.0.0/127.0.0.1}
case "${HOST#*://}" in *:*) ;; *) HOST="$HOST:11434" ;; esac

STOP_EPOCH=""
if [ -n "$STOP_AT" ]; then  # the next STOP_AT from now (today's, or tomorrow's when today's has passed)
  STOP_EPOCH=$(date -j -f "%H:%M:%S" "$STOP_AT:00" +%s) || { echo "STOP_AT takes HH:MM, e.g. 07:30"; exit 1; }
  [ "$STOP_EPOCH" -le "$(date +%s)" ] && STOP_EPOCH=$((STOP_EPOCH + 86400))
fi
[ -n "$DRY_RUN" ] && [ "$REPORT" = results/BASELINES.md ] && REPORT="$BASE/BASELINES-dry-run.md"

mkdir -p "$BASE"
LOG="$BASE/baselines.log"
DONE="$BASE/done.txt"
STOP="$BASE/STOP"
OUT="$BASE/last-run.out"
touch "$DONE"
FAILS=0

PY=""
for p in python3 /usr/bin/python3 "$HOME/.local/bin/python3.11"; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    PY=$p; break
  fi
done
[ -n "$PY" ] || { echo "Need Python 3.9 or newer as python3."; exit 1; }

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
hm() {  # seconds as "1 h 05 min" / "12 min" / "40 s"
  local s=${1:-0}
  if [ "$s" -ge 3600 ]; then printf '%d h %02d min' $((s / 3600)) $(((s % 3600) / 60))
  elif [ "$s" -ge 60 ]; then printf '%d min' $(((s + 30) / 60))
  else printf '%d s' "$s"; fi
}
want() { case ",$STAGES," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }

# The table above: samples and seconds per sample for each model (SAMPLES overrides the samples)
samples_for() {
  local m=$1 n
  case "$m" in
    qwen3:14b|gemma4:12b-it-q4_K_M|qwen3.8:27b|qwen3:8b) n=1 ;;
    gpt-oss:120b) n=2 ;;
    *) n=3 ;;
  esac
  local IFS=','
  for kv in $SAMPLES; do [ "${kv%=*}" = "$m" ] && n=${kv##*=}; done
  echo "$n"
}
sec_for() {
  case "$1" in
    qwen3:14b) echo 100 ;; gemma4:12b-it-q4_K_M) echo 65 ;; qwen3.8:27b) echo 62 ;; gpt-oss:120b) echo 38 ;;
    qwen3:8b) echo 65 ;; qwen3:4b-instruct-2507-q4_K_M) echo 9 ;; *) echo 60 ;;
  esac
}
# One prompt's samples: stage a has 33 Blender or code cases and 3 prose; stage c's N W1 steps (24 when all are
# frozen) about three quarters Blender or code, with prompts about 10% longer
est_a() {
  local s; s=$(samples_for "$1")
  if [ -n "$CASES" ]; then echo $(( $(echo "$CASES" | tr ',' '\n' | wc -l) * s * $(sec_for "$1") )); return 0; fi
  echo $(( (33 * s + 3) * $(sec_for "$1") ))
}
est_c() { local s n=${2:-24}; s=$(samples_for "$1"); echo $(( (3 * n * s + n) / 4 * $(sec_for "$1") * 11 / 10 )); }
# Stage g, thinking off (the Oct 30 smoke run: 6-18 s a reply for qwen3:14b, 7-30 s for Gemma, plus Blender)
sec_nothink() { case "$1" in qwen3:14b) echo 16 ;; gemma4:12b-it-q4_K_M) echo 22 ;; *) echo 20 ;; esac; }
est_g_a() {
  if [ -n "$CASES" ]; then echo $(( $(echo "$CASES" | tr ',' '\n' | wc -l) * NOTHINK_SAMPLES * $(sec_nothink "$1") )); return 0; fi
  echo $(( (33 * NOTHINK_SAMPLES + 3) * $(sec_nothink "$1") ))
}
est_g_c() { local n=${2:-24}; echo $(( (3 * n * NOTHINK_SAMPLES + n) / 4 * $(sec_nothink "$1") * 11 / 10 )); }

is_done() { awk -F'\t' -v k="$1" '$1 == k { f = 1 } END { exit !f }' "$DONE"; }
check_stop() {
  if [ -e "$STOP" ]; then
    rm -f "$STOP"
    log "STOP file found: stopping before \"$1\". Run the same command again to carry on."
    finish 0
  fi
  if [ -n "$STOP_EPOCH" ] && [ "$(date +%s)" -ge "$STOP_EPOCH" ]; then
    log "It's past STOP_AT $STOP_AT: stopping before \"$1\". Run the same command again to carry on."
    finish 0
  fi
}
installed() { curl -sf "$HOST/api/show" -d "{\"model\": \"$1\"}" >/dev/null; }
unload_except() {  # unload every loaded model but these (space-separated)
  if [ -n "$DRY_RUN" ]; then log "  (dry run) would unload every loaded model except: ${1:-none}"; return 0; fi
  "$PY" -m runner.baselines unload --keep "$(echo "$1" | tr ' ' ',')" --host "$HOST" 2>&1 | tee -a "$LOG" || true
}
report() {
  "$PY" runner/report.py --runs "$RUNS" --task-runs "$TASK_RUNS" --frozen "$FROZEN" --tag "$TAG" --out "$REPORT" \
    2>&1 | tee -a "$LOG" || log "the report failed (the runs are still there)"
}
finish() {
  report
  if [ -z "$DRY_RUN" ] && [ -n "${LOADED_AT_START+x}" ]; then unload_except "$LOADED_AT_START"; fi
  log "== finished: $FAILS run(s) failed; $(wc -l < "$DONE" | tr -d ' ') run(s) done in all ($DONE); report $REPORT"
  exit "$1"
}

# run KEY ESTIMATE_S KEEP_MODELS -- command ...: one runner call, skipped when KEY is in the done list
run() {
  local key=$1 est=$2 keep=$3
  shift 4
  if is_done "$key"; then log "  skip (done before): $key"; return 0; fi
  check_stop "$key"
  if [ -n "$DRY_RUN" ]; then
    log "  (dry run) $key, estimate $(hm "$est"): $*"
    unload_except "$keep"
    set +e; "$@" --dry-run >"$OUT" 2>&1; local rc=$?; set -e
    cat "$OUT" >> "$LOG"
    log "  (dry run) the runner's dry run exited $rc; its output ($(wc -l < "$OUT" | tr -d ' ') lines) is in the log"
    return 0
  fi
  unload_except "$keep"
  log "  start: $key (estimate $(hm "$est"))"
  local t0=$SECONDS rc
  set +e
  "$@" 2>&1 | tee "$OUT" | tee -a "$LOG" >&2
  rc=${PIPESTATUS[0]}
  set -e
  local took=$((SECONDS - t0)) dir
  dir=$(grep '^wrote ' "$OUT" | tail -1 | sed 's/^wrote //; s#/summary.md$##' || true)
  if [ "$rc" -eq 0 ] && [ -n "$dir" ] && [ -f "$dir/summary.json" ] && ! "$PY" -c '
import json, sys
s = json.load(open(sys.argv[1]))["summary"]
a = s.get("all", s)
sys.exit(1 if a.get("n") and 2 * (a.get("errors") or 0) > a["n"] else 0)' "$dir/summary.json"; then
    rc=3
    log "  most of the run's calls failed (see its summary.md): not counting it as done"
  fi
  if [ "$rc" -eq 0 ]; then
    printf '%s\t%s\t%s\t%s\t%s\n' "$key" "$took" "$est" "$(date '+%Y-%m-%dT%H:%M:%S')" "${dir:--}" >> "$DONE"
    log "  done: $key in $(hm "$took") (estimate $(hm "$est"))${dir:+ -> $dir}"
  else
    FAILS=$((FAILS + 1))
    log "  FAILED (exit $rc) after $(hm "$took"): $key. Not marked done: a rerun tries it again."
  fi
}

stage_start() { STAGE_T0=$SECONDS; log "== stage $1 (estimate $(hm "$2"))"; }
stage_end() { log "== stage $1 finished in $(hm $((SECONDS - STAGE_T0)))"; report; }

# ---------------------------------------------------------------- checks
log "== run_baselines.sh ($("$PY" --version 2>&1)), stages $STAGES, tag $TAG${DRY_RUN:+, DRY RUN (no model calls)}"
if [ -z "${CHIMERA_BIN:-}" ]; then
  CHIMERA_BIN="$HERE/$BASE/bin/chimera"
  GO=$(command -v go || true); [ -z "$GO" ] && [ -x /opt/homebrew/bin/go ] && GO=/opt/homebrew/bin/go
  [ -n "$GO" ] || { echo "No CHIMERA_BIN and no Go to build one (see README, Common commands)."; exit 1; }
  log "building Chimera into $CHIMERA_BIN"
  mkdir -p "$(dirname "$CHIMERA_BIN")"
  rm -f "$CHIMERA_BIN"  # macOS kills a signed binary overwritten in place
  (cd ../app && PATH="$(dirname "$GO"):$PATH" "$GO" build -o "$CHIMERA_BIN" .)
fi
export CHIMERA_BIN
[ -x "$CHIMERA_BIN" ] || { echo "CHIMERA_BIN=$CHIMERA_BIN isn't an executable."; exit 1; }
if [ -z "${SKIP_TESTS:-}" ]; then
  log "checking worker-model's code (the unit tests, about 40 s)"
  "$PY" -m unittest discover -s tests -t . >"$OUT" 2>&1 || { cat "$OUT"; log "the tests failed; nothing was run"; exit 1; }
fi
if [ -e "$STOP" ]; then rm -f "$STOP"; log "removed an old STOP file"; fi

if [ -z "$DRY_RUN" ]; then
  curl -sf "$HOST/api/version" >/dev/null || { echo "Ollama isn't answering at $HOST. Open Ollama, then run this again."; exit 1; }
  LOADED_AT_START=$("$PY" -m runner.baselines loaded --host "$HOST" 2>/dev/null | tr '\n' ' ' || true)
  command -v caffeinate >/dev/null 2>&1 && { caffeinate -i -w $$ & }  # keep the Mac awake until this finishes
  echo "Switch lending off in Chimera for clean timings, if it's on (not a blocker)."
fi
MISSING=""
LINEUP=""
for m in $MODELS; do
  if [ -z "$DRY_RUN" ] && ! installed "$m"; then MISSING="$MISSING $m"; else LINEUP="$LINEUP $m"; fi
done
[ -n "$MISSING" ] && log "not installed, so skipped (nothing is downloaded):$MISSING"
TOTAL_A=0
for m in $LINEUP; do TOTAL_A=$((TOTAL_A + 2 * $(est_a "$m"))); done
log "models:$LINEUP; samples:$(for m in $LINEUP; do printf ' %s=%s' "$m" "$(samples_for "$m")"; done)"

SEL="--quick"
if [ -n "$CASES" ]; then
  SEL=""
  for c in $(echo "$CASES" | tr ',' ' '); do SEL="$SEL --case $c"; done
fi
CASES_KEY=${CASES:-quick}

# ---------------------------------------------------------------- a. step level, W2-W4
if want a; then
  stage_start "a: step_eval on the quick subset's W2, W3 and W4 cases" "$TOTAL_A"
  for m in $LINEUP; do
    s=$(samples_for "$m"); e=$(est_a "$m")
    for p in today contract; do
      # shellcheck disable=SC2086
      run "a|step|w2-w4|$CASES_KEY|$m|$p|samples=$s|$TAG" "$e" "$m" -- \
        "$PY" runner/step_eval.py --model "$m" --prompt "$p" --parts w2,w3,w4f,w4l $SEL --samples "$s" --tag "$TAG" \
        --prose-samples 1 --out "$RUNS" --host "$HOST" --no-unload $NO_BLENDER
    done
  done
  stage_end a
fi

# ---------------------------------------------------------------- b. freeze W1's plans and the quick tasks' inputs
QUICK_W1=$("$PY" -m runner.baselines quick-w1)
if want b; then
  stage_start "b: freezing W1's plans and the quick subset's dependency outputs" 3000
  run "b|freeze|plans|$TAG" 600 "$PLANNER" -- \
    "$PY" runner/freeze.py --what plans --frozen "$FROZEN" --host "$HOST" --no-unload
  run "b|freeze|deps|$QUICK_W1|$TAG" 2400 "$TEACHER" -- \
    "$PY" runner/freeze.py --what deps --tasks "$QUICK_W1" --today-deps 0 --frozen "$FROZEN" --host "$HOST" --no-unload
  stage_end b
fi

# ---------------------------------------------------------------- g. thinking off, the two base candidates
if want g; then
  G_BASES=""
  for m in $BASES; do
    if [ -z "$DRY_RUN" ] && ! installed "$m"; then log "stage g: $m isn't installed, so skipped"; else G_BASES="$G_BASES $m"; fi
  done
  N_W1G=0
  if [ -z "$CASES" ]; then N_W1G=$("$PY" -m runner.baselines w1-cases --frozen "$FROZEN"); fi
  TOTAL_G=0
  for m in $G_BASES; do
    TOTAL_G=$((TOTAL_G + $(est_g_a "$m")))
    if [ "$N_W1G" -gt 0 ]; then TOTAL_G=$((TOTAL_G + $(est_g_c "$m" "$N_W1G"))); fi
  done
  stage_start "g: step_eval with thinking off for$G_BASES, contract prompt, samples=$NOTHINK_SAMPLES" "$TOTAL_G"
  for m in $G_BASES; do
    # shellcheck disable=SC2086
    run "g|step|w2-w4|$CASES_KEY|$m|contract|think=false|samples=$NOTHINK_SAMPLES|$TAG" "$(est_g_a "$m")" "$m" -- \
      "$PY" runner/step_eval.py --model "$m" --prompt contract --think false --parts w2,w3,w4f,w4l $SEL \
      --samples "$NOTHINK_SAMPLES" --tag "$TAG-nothink" --prose-samples 1 --out "$RUNS" --host "$HOST" --no-unload $NO_BLENDER
  done
  if [ "$N_W1G" -gt 0 ]; then
    for m in $G_BASES; do
      # shellcheck disable=SC2086
      run "g|step|w1|quick|$m|contract|think=false|samples=$NOTHINK_SAMPLES|$TAG" "$(est_g_c "$m" "$N_W1G")" "$m" -- \
        "$PY" runner/step_eval.py --model "$m" --prompt contract --think false --parts w1 --quick --frozen "$FROZEN" \
        --samples "$NOTHINK_SAMPLES" --tag "$TAG-nothink-w1" --prose-samples 1 --out "$RUNS" --host "$HOST" --no-unload \
        $NO_BLENDER
    done
  else
    log "  stage g: no W1 steps (none frozen yet, or CASES is set), so only W2-W4"
  fi
  stage_end g
fi

# ---------------------------------------------------------------- c. step level, W1's frozen steps
if want c; then
  N_W1=$("$PY" -m runner.baselines w1-cases --frozen "$FROZEN")
  if [ "$N_W1" -eq 0 ]; then
    log "== stage c skipped: none of the quick subset's W1 steps has its inputs frozen yet (stage b)"
  else
    TOTAL_C=0
    for m in $LINEUP; do TOTAL_C=$((TOTAL_C + 2 * $(est_c "$m" "$N_W1"))); done
    stage_start "c: step_eval on the quick subset's $N_W1 W1 steps" "$TOTAL_C"
    for m in $LINEUP; do
      s=$(samples_for "$m")
      for p in today contract; do
        # shellcheck disable=SC2086
        run "c|step|w1|quick|$m|$p|samples=$s|$TAG" "$(est_c "$m" "$N_W1")" "$m" -- \
          "$PY" runner/step_eval.py --model "$m" --prompt "$p" --parts w1 --quick --frozen "$FROZEN" --samples "$s" \
          --tag "$TAG-w1" --prose-samples 1 --out "$RUNS" --host "$HOST" --no-unload $NO_BLENDER
      done
    done
    stage_end c
  fi
fi

# ---------------------------------------------------------------- d. T1, whole plans, arms side by side
if want d; then
  T1=$("$PY" -m runner.baselines t1 --frozen "$FROZEN" --max-blender "$T1_BLENDER" --max-code "$T1_CODE" | tr '\n' ' ')
  # shellcheck disable=SC2206
  T1_LIST=($T1)
  N_T1=${#T1_LIST[@]}
  if [ "$N_T1" -eq 0 ]; then
    log "== stage d skipped: no frozen Blender or python-script plan yet (stage b)"
  else
    stage_start "d: task_eval T1, arms $ARMS, on $N_T1 tasks in chunks of $T1_CHUNK" $((N_T1 * 1140))
    k=0
    i=0
    while [ "$i" -lt "$N_T1" ]; do
      k=$((k + 1))
      chunk=$(echo "${T1_LIST[@]:$i:$T1_CHUNK}" | tr ' ' ',')
      n=$(echo "$chunk" | tr ',' '\n' | wc -l | tr -d ' ')
      log "  T1 chunk $k: $chunk"
      for arm in $ARMS; do
        case "$arm" in
          A|B) keep="$COMBINE"; per=300 ;;   # qwen3.8:27b workers and combine
          A2|C) keep="$TEACHER"; per=240 ;;  # gpt-oss:120b workers; the combine loads qwen3.8:27b when it needs it
          *) log "  unknown arm $arm, skipped"; continue ;;
        esac
        run "d|t1|$arm|$chunk|review=$REVIEW|$TAG" $((n * per)) "$keep" -- \
          "$PY" runner/task_eval.py --arm "$arm" --tasks "$chunk" --frozen "$FROZEN" --combine-model "$COMBINE" \
          --review "$REVIEW" --tag "$TAG-t1-c$k" --out "$TASK_RUNS" --host "$HOST" --no-unload $NO_BLENDER
      done
      i=$((i + T1_CHUNK))
    done
    stage_end d
  fi
fi

# ---------------------------------------------------------------- e. the report (also after every stage)
if want e; then
  log "== stage e: the report"
  report
fi

# ---------------------------------------------------------------- f. the rest of W1's inputs, for later
if want f; then
  stage_start "f: the rest of W1's dependency outputs and 10 in today's format" 9000
  run "f|freeze|deps|all|today=10|$TAG" 9000 "$TEACHER" -- \
    "$PY" runner/freeze.py --what deps --today-deps 10 --frozen "$FROZEN" --host "$HOST" --no-unload
  stage_end f
fi

finish 0

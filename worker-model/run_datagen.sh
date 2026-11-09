#!/bin/bash
# Make Hydra Worker 1.0's training data on the Studio (datagen/DESIGN.md; the README's "Data generation").
#
#   bash run_datagen.sh                  # the 20-seed smoke run (about 4-6 hours), into data/gen/smoke/ (see below)
#   bash run_datagen.sh --data-dir data/gen/smoke6 --limit 8   # a smaller smoke run, in a folder of its own
#   SIZE=night bash run_datagen.sh       # the overnight run, into data/gen/night/ (resumable over 3-4 nights)
#   PARALLEL=2 bash run_datagen.sh       # two model calls at once (only if Ollama runs with OLLAMA_NUM_PARALLEL=2)
#   SKIP_TESTS=1 bash run_datagen.sh     # don't run the datagen tests first (about 3 minutes)
#   bash run_datagen.sh --no-early-stop  # anything after the script's name goes to datagen.run as it is
#
# Before starting, switch lending off in Chimera (Disconnected), so pool work doesn't land on the Studio while the
# 65 GB teacher is loaded, and don't start or restart the real Chimera while it runs. The script checks: while
# Chimera is lending it stops, unless FORCE=1. It's resumable: stop it with Ctrl-C, or touch <data folder>/STOP to
# stop after the calls in flight, then run the same command again. It pulls nothing: a missing model stops it with the
# command to pull it. The data folder is --data-dir's, else data/gen/<size>/; results: its REPORT.md and sft/ (the
# training files), and this script's log, its run.log. A smoke run that has finished in data/gen/smoke/ (REPORT.md
# written, every seed of its seeds.jsonl finished) isn't run again there without a --data-dir: that would skip its
# seeds or make them again and replace its report and training files, the first smoke run's among them. Nor is a
# finished run of another data generator format, in any folder, --data-dir's too (data/gen/smoke2 to smoke5 hold the
# second to the fifth smoke runs, formats 2 to 5; the format is 6 since Nov 6, so the sixth goes into
# data/gen/smoke6), unless --new-binary-ok; a direct python3 -m datagen.run refuses those folders as well.
# The Blender and Python run folders go under $WM_SCRATCH, by default a folder in $TMPDIR (else /tmp), outside the
# home folder: the sandbox they run in can't read /Users, so a tool that resolves its own path there (node, which
# checks a .js file) can't start in one under data/scratch. Each is removed after its run.
set -euo pipefail
cd "$(dirname "$0")"

SIZE=${SIZE:-smoke}
PARALLEL=${PARALLEL:-1}
DATA_DIR=""  # --data-dir, when the arguments give one (they go to datagen.run as they are; so does a --size)
NEW_OK=""  # --new-binary-ok among them: datagen.run goes ahead in a finished folder of another format, and so does this
prev=""
for a in "$@"; do
  case "$prev" in --data-dir) DATA_DIR=$a ;; --size) SIZE=$a ;; esac
  case "$a" in --data-dir=*) DATA_DIR=${a#--data-dir=} ;; --size=*) SIZE=${a#--size=} ;; --new-binary-ok) NEW_OK=1 ;; esac
  prev=$a
done
DATA=${DATA_DIR:-data/gen/$SIZE}
MODELS="gpt-oss:120b hydra:1.0 qwen3.8:27b qwen3:8b"
HOST=${OLLAMA_HOST:-127.0.0.1:11434}
case "$HOST" in http://*|https://*) ;; *) HOST="http://$HOST" ;; esac
HOST=${HOST/0.0.0.0/127.0.0.1}
case "${HOST#*://}" in *:*) ;; *) HOST="$HOST:11434" ;; esac

PY=""
for p in python3 /usr/bin/python3; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    PY=$p; break
  fi
done
[ -n "$PY" ] || { echo "Need Python 3.9 or newer as python3."; exit 1; }

# A run that has finished in the data folder: its report is written and every seed it chose is finished (done or
# no_plan; the last line of a seed's wins, a half line is skipped). Exit 0 when it hasn't (an unfinished or errored run
# carries on), 10 when it has, 11 when it has and every finished record is another data generator format's than
# datagen/task.py's DATAGEN_FORMAT (the formats printed): datagen.run refuses that folder too, but only after this
# script has started a log in it.
ENDED=0
FORMATS=$("$PY" - "$DATA" <<'FINISHED'
import json, os, re, sys
d = sys.argv[1]


def rows(name):
    try:
        with open(os.path.join(d, name), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return []
    out = []
    for line in text.split("\n"):
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return [r for r in out if isinstance(r, dict)]


last = {}
for r in rows("tasks.jsonl"):
    last[r.get("key")] = r
seeds = [s.get("seed_id") for s in rows("seeds.jsonl")]
if not (os.path.isfile(os.path.join(d, "REPORT.md")) and seeds and
        all((last.get(s) or {}).get("status") in ("done", "no_plan") for s in seeds)):
    sys.exit(0)
try:
    with open(os.path.join("datagen", "task.py"), encoding="utf-8") as f:
        now = int(re.search(r"^DATAGEN_FORMAT = (\d+)", f.read(), re.M).group(1))
except (OSError, AttributeError, ValueError):
    sys.exit(10)  # this format unknown: nothing more is said here
formats = sorted({last[s].get("format") or 1 for s in seeds})
if now in formats:
    sys.exit(10)
print(", ".join(map(str, formats)) + ", %d now" % now)
sys.exit(11)
FINISHED
) || ENDED=$?
if [ "$ENDED" != 0 ] && [ "$SIZE" = smoke ] && [ -z "$DATA_DIR" ]; then
  echo "$DATA/ holds a smoke run that has finished (its REPORT.md is written and every seed is done). A run there"
  echo "would skip those seeds or make them again, and replace that run's report and training files."
  echo "Give a new run its own folder: bash run_datagen.sh --data-dir data/gen/smoke6 (--limit N for fewer seeds)."
  echo "To rebuild a run's files, copy its folder and build the copy with its own --data-dir; a folder that another"
  echo "data generator format made (the first five smoke runs') can't be rebuilt: the build drops its records as old_format."
  exit 1
fi
if [ "$ENDED" = 11 ] && [ -z "$NEW_OK" ]; then
  echo "$DATA/ holds a run that has finished, made by another version of the data generator (format $FORMATS)."
  echo "A run there would make its seeds again and replace its report and training files, which this generator can't"
  echo "rebuild. Give a new run its own folder: bash run_datagen.sh --data-dir data/gen/smoke6 (--limit N for fewer"
  echo "seeds), or add --new-binary-ok to go ahead in that folder anyway."
  exit 1
fi

# Is this Mac's Chimera lending? Its window's port answers GET /api/state (read only) with lending.state.
for p in ${CHIMERA_UI_PORTS:-7470 7471 7472 7473 7474}; do
  STATE=$(curl -s --max-time 2 "http://127.0.0.1:$p/api/state" 2>/dev/null \
          | "$PY" -c 'import json, sys; print(json.load(sys.stdin)["lending"]["state"])' 2>/dev/null || true)
  [ -n "$STATE" ] || continue  # nothing there, or not Chimera
  [ "$STATE" = "disconnected" ] && continue
  echo "Chimera is lending this Mac to the pool (lending state \"$STATE\", on port $p): pool work would load other"
  echo "models beside the 65 GB teacher, and slow or break both. In Chimera, switch it to Disconnected; if you'll run"
  echo "long tasks of your own from this Mac meanwhile, also turn off auto-help, which connects it again for them."
  if [ -n "${FORCE:-}" ]; then
    echo "FORCE is set: going on anyway (the timings in REPORT.md may include pool work)."
  else
    echo "Then run this again (FORCE=1 skips this check)."
    exit 1
  fi
done

GO=$(command -v go || true)
[ -n "$GO" ] || GO=/opt/homebrew/bin/go
[ -x "$GO" ] || { echo "Need Go to build Chimera (brew install go)."; exit 1; }

case "${TMPDIR:-}" in ""|/Users/*|/Volumes/*) SCRATCH_BASE=/tmp ;; *) SCRATCH_BASE=${TMPDIR%/} ;; esac
export WM_SCRATCH=${WM_SCRATCH:-$SCRATCH_BASE/chimera-wm-scratch}  # outside the home folder (see the top)
mkdir -p data/gen/bin "$WM_SCRATCH"
BIN=$PWD/data/gen/bin/chimera
echo "== Building Chimera into $BIN"
rm -f "$BIN"  # macOS kills a signed binary that was overwritten in place
(cd ../app && PATH="$(dirname "$GO"):$PATH" "$GO" build -o "$BIN" .)
"$BIN" --version

if [ -z "${SKIP_TESTS:-}" ]; then
  echo "== Checking the data generator (its tests, about 3 minutes)"
  if ! CHIMERA_BIN="$BIN" PYTHONDONTWRITEBYTECODE=1 "$PY" -m unittest discover -s tests -t . -p 'test_datagen_*.py' \
       >data/gen/tests.log 2>&1; then
    tail -40 data/gen/tests.log
    echo "The datagen tests failed (data/gen/tests.log); nothing was started."
    exit 1
  fi
fi

if ! curl -sf "$HOST/api/version" >/dev/null; then
  echo "Ollama isn't answering at $HOST. Open Ollama, then run this again."; exit 1
fi
MISSING=""
for m in $MODELS; do
  curl -sf "$HOST/api/show" -d "{\"model\": \"$m\"}" >/dev/null || MISSING="$MISSING $m"
done
if [ -n "$MISSING" ]; then
  echo "Not in Ollama:$MISSING. Pull them (ollama pull$MISSING; hydra:1.0 comes from Chimera's Models page), then run this again."
  exit 1
fi

command -v caffeinate >/dev/null 2>&1 && { caffeinate -i -w $$ & }  # keep the Mac awake until this finishes
mkdir -p "$DATA"
echo "== Data generation, size $SIZE, into $DATA/ (log: $DATA/run.log)"
set +e
"$PY" -m datagen.run --size "$SIZE" --host "$HOST" --chimera "$BIN" --parallel "$PARALLEL" "$@" 2>&1 \
  | tee -a "$DATA/run.log"
CODE=${PIPESTATUS[0]}
set -e
echo
case $CODE in
  0) echo "Done. Report: $DATA/REPORT.md. Training files: $DATA/sft/ (STATS.md says what's in them)." ;;
  4) echo "Every stage ran, but some seeds ended in an error (the last lines above say how many; $DATA/progress.log"
     echo "says which). The report and training files were made without them. Run this again to retry them."
     exit 4 ;;
  *) echo "The run stopped. See $DATA/STOPPED.md (if it exists) and $DATA/run.log; run this again to carry on."
     exit 1 ;;
esac

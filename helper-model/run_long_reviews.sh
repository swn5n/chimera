#!/bin/bash
# The long review cases (eval-long/) on Hydra 1.0 and on the teacher, then side by side.
#
#   bash run_long_reviews.sh                    # hydra:1.0 and gpt-oss:120b, about 10 minutes
#   MODELS="hydra:1.0" bash run_long_reviews.sh
#
# Runs go to results/runs-long/, apart from the eval v1.1 baselines.
set -euo pipefail
cd "$(dirname "$0")"
MODELS=${MODELS:-hydra:1.0 gpt-oss:120b}
PY=""
for p in python3 /usr/bin/python3 "$HOME/.local/bin/python3.11"; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then PY=$p; break; fi
done
[ -n "$PY" ] || { echo "Need Python 3.9 or newer as python3."; exit 1; }
OUT=results/runs-long
mkdir -p "$OUT"
RUNS=()
for m in $MODELS; do
  echo "== $m"
  before=$(find "$OUT" -maxdepth 1 -type d -name '20*' | sort | tail -1)
  "$PY" runner/run_eval.py --model "$m" --jobs reviewer --eval-dir eval-long --out "$OUT"
  after=$(find "$OUT" -maxdepth 1 -type d -name '20*' | sort | tail -1)
  [ "$after" != "$before" ] || { echo "No run folder for $m"; exit 1; }
  RUNS+=("$after")
done
echo
"$PY" runner/compare.py --jobs reviewer "${RUNS[@]}" | tee "$OUT/compare-$(date +%Y%m%d-%H%M%S).txt"
echo
echo "Done. Summaries: ${RUNS[*]/%//summary.md}"

#!/bin/bash
# Double-click in Finder to make v2's data, train v2 and score it in Terminal (same as: bash run_v2.sh).
cd "$(dirname "$0")" && bash run_v2.sh
echo
read -n 1 -s -r -p "Press any key to close this window."

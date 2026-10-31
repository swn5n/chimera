#!/bin/bash
# Double-click in Finder to make v3's data, train v3 and score it in Terminal (same as: bash run_v3.sh).
cd "$(dirname "$0")" && bash run_v3.sh
echo
read -n 1 -s -r -p "Press any key to close this window."

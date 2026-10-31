#!/bin/bash
# Double-click in Finder to run the baselines in Terminal (same as: bash run_baselines.sh).
cd "$(dirname "$0")" && bash run_baselines.sh
echo
read -n 1 -s -r -p "Press any key to close this window."

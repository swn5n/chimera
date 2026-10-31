#!/bin/bash
# Double-click in Finder to train and score the helper model in Terminal (same as: bash run_train.sh).
cd "$(dirname "$0")" && bash run_train.sh
echo
read -n 1 -s -r -p "Press any key to close this window."

#!/bin/bash
# Double-click in Finder to generate the training data in Terminal (same as: bash run_datagen.sh).
cd "$(dirname "$0")" && bash run_datagen.sh
echo
read -n 1 -s -r -p "Press any key to close this window."

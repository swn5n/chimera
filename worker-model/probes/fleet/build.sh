#!/bin/bash
# Build fleet-probe for the machines probe (d) runs on, into the folder docs/probe-d-steps.md serves from the Studio.
set -euo pipefail
cd "$(dirname "$0")"
OUT=${OUT:-$HOME/chimera-tools/worker-train/probes/fleet-out}
GGUF=${GGUF:-$HOME/chimera-tools/worker-train/probes/round-trip/rt2-q5_k_m.gguf}
command -v go >/dev/null 2>&1 || PATH=$PATH:/opt/homebrew/bin
mkdir -p "$OUT"
rm -f "$OUT/fleet-probe-mac"  # overwriting a signed binary in place gets it killed at launch
# the GGUF's size and checksum go into the tool, so a cut-off copy is caught before it goes near Ollama
FLAGS="-X main.wantSize=$(stat -f %z "$GGUF") -X main.wantDigest=sha256:$(shasum -a 256 "$GGUF" | cut -d' ' -f1)"
GOOS=darwin GOARCH=arm64 go build -ldflags "$FLAGS" -o "$OUT/fleet-probe-mac" .
GOOS=windows GOARCH=amd64 go build -ldflags "$FLAGS" -o "$OUT/fleet-probe.exe" .
GOOS=linux GOARCH=amd64 go build -ldflags "$FLAGS" -o "$OUT/fleet-probe-linux" .
ln -sf "$GGUF" "$OUT/worker-q5.gguf"
ls -lhL "$OUT"

#!/usr/bin/env python3
"""Unload every model Ollama has in memory (frees the GPU before training).

    python3 train/ollama_unload.py [host]
"""
import json
import sys
import urllib.request

host = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:11434").rstrip("/")
try:
    with urllib.request.urlopen(host + "/api/ps", timeout=10) as r:
        models = [m.get("name") or m.get("model") for m in json.load(r).get("models", [])]
except Exception as e:  # noqa: BLE001
    print(f"couldn't ask Ollama what's loaded: {e}")
    sys.exit(0)
for name in models:
    req = urllib.request.Request(host + "/api/generate", data=json.dumps({"model": name, "keep_alive": 0}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=60).read()
        print("unloaded", name)
    except Exception as e:  # noqa: BLE001
        print(f"couldn't unload {name}: {e}")

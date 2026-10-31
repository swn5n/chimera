# Probe d: fit on the 3080 Ti and the M4 Pro

The last probe of the worker base-model rule (`docs/hydra-worker-plan.md`, "Probes a-c"). It answers one question: does
the worker's model sit fully on the GPU at 8K, 16K and 32K context on these two computers? If it does on both, the base
is Gemma 4 12B. If it doesn't, the rule says Qwen3-14B.

About 20 minutes per computer one at a time, most of it copying 8.5 GB over Wi-Fi. Both at once takes about 30 minutes
in all, because they share the Studio's Wi-Fi. `fleet-probe` is one file with nothing to install. It imports the model
the way Chimera's Get from host will, so it also tries that path on Windows for the first time.

## Before you start

On each of the two computers:
- **Ollama is installed, running and up to date.** The Studio's is 0.40.1, so use that or newer. `ollama --version`
  shows it. If it's missing, install it from ollama.com.
- **In Chimera, click Disconnect** on the Network tab, so nothing else loads a model. If a step is running, choose
  "Finish it, then disconnect" and wait. Don't start long tasks on your other computers during the probe, because
  Chimera reconnects your computers to help with those. Don't reopen Chimera until you've done step 5, because it
  connects by itself when it opens.
- **You have 18 GB free.** The model takes 8.5 GB in the folder and 8.5 GB more inside Ollama until step 5. `df -h ~`
  shows it on the Mac, `Get-PSDrive C` on the PC.
- **Plug it in, keep the lid open, and turn off sleep.** A laptop that sleeps stops the copy. On the PC: Settings,
  System, Power, set sleep to Never for now. On the Mac the commands below keep it awake.
- **On the 3080 Ti, close anything that uses the GPU**, such as Blender, games and ComfyUI, because the display and
  those apps share its 16 GB. `nvidia-smi` lists what's using it.

## 1. On the Studio

Check the Studio's address, which should be `192.168.0.25`. If it's different, use it in the commands below.

```bash
ipconfig getifaddr en1
```

Start a small file server, and leave it running until both computers are done. Allow incoming connections if macOS
asks.

```bash
cd ~/chimera-tools/worker-train/probes/fleet-out && python3 -m http.server 7490
```

## 2. On the M4 Pro

In Terminal:

```bash
mkdir -p ~/fleet-probe && cd ~/fleet-probe
caffeinate -i curl -fO http://192.168.0.25:7490/worker-q5.gguf
curl -fO http://192.168.0.25:7490/fleet-probe-mac
chmod +x fleet-probe-mac
caffeinate -i ./fleet-probe-mac --gguf worker-q5.gguf
```

## 3. On the 3080 Ti PC

In PowerShell (use `curl.exe`, not `curl`, which PowerShell treats as something else):

```powershell
mkdir $HOME\fleet-probe; cd $HOME\fleet-probe
curl.exe -fO http://192.168.0.25:7490/worker-q5.gguf
curl.exe -fO http://192.168.0.25:7490/fleet-probe.exe
.\fleet-probe.exe --gguf worker-q5.gguf
```

If that PC runs Linux, follow the M4 Pro's commands with `fleet-probe-linux` in place of `fleet-probe-mac`, without
`caffeinate`.

## 4. Read the results

Each run ends with a list of PASS and FAIL lines, even when a measurement failed. If it ends with `STOPPED` and no
list, see "If something goes wrong".

| Lines | What they decide |
|---|---|
| Fit at 8K, 16K and 32K | **The rule.** All three must pass on both computers. A Fit that fails is measured once more automatically |
| Worker setup, Replies, Short and Long prompt tokens | Whether the import works on that computer: the renderer and parser, no thinking, and the same prompt tokens as training |
| Speed, the 1,500-token step, and Speed at larger contexts | The plan's bar for shipping, not the rule. A miss here doesn't change the base, but I'd want to know |

The M4 Pro's memory is shared with its GPU, so its Fit lines will nearly always pass and its Speed line says more.

**Bring the results back to this chat on the Studio before you clean up**, because step 5 deletes the folder they're
in. A phone photo of the lines is enough. If you can, also copy `fleet-probe-<computer>.json` from that folder (AirDrop
on the Mac, a USB stick on the PC): it has each context's speed and, on the PC, how much GPU memory was in use.

## 5. Clean up

Do this on each of the two computers before you connect or reopen Chimera. It shares every model it finds, so it would
offer the test model to the pool.

On the M4 Pro:

```bash
cd ~
ollama rm wm-probe-fleet:q5
rm -r ~/fleet-probe
```

On the PC, in PowerShell:

```powershell
cd $HOME
ollama rm wm-probe-fleet:q5
Remove-Item -Recurse $HOME\fleet-probe
```

Then press Ctrl+C on the Studio to stop the file server.

## If something goes wrong

| It says | Do this |
|---|---|
| Ollama isn't answering | Open Ollama and run the tool again |
| Ollama has a model loaded | Disconnect in Chimera, run the `ollama stop` lines it shows, and run the tool again |
| A Fit line fails at **0.0%** | Ollama isn't using the GPU at all, which says nothing about fit. Run `nvidia-smi`, update the NVIDIA driver if that fails, restart Ollama and run the tool again |
| A Fit line fails with another percentage or an error | Close whatever `nvidia-smi` lists and run the tool again once. If it still fails, send me the line and the `nvidia-smi` output. That's the real result, and the rule then points to Qwen3-14B |
| A Fit line says another model was loaded too | That reading doesn't count. Disconnect in Chimera and run the tool again |
| Worker setup, Replies or a prompt-token line fails | The Fit lines still count. Update Ollama, run the tool again, and send me both sets of results. The tool's first line shows each version |
| This Ollama doesn't know the worker's renderer | Update Ollama and run the tool again. Tell me the version that failed and the version that worked, so I can set the worker's minimum |
| This copy of the file is the wrong size, or damaged | The copy was cut off. It should be 8,547,263,520 bytes, which `curl` shows as 8151M. Delete `worker-q5.gguf`, run that `curl` line again from the start (this server can't resume), then run the tool again |
| `curl: (18)` or `curl: (56)` | Same as above: the copy was cut off |
| `curl` can't connect | Check that the computer is on the same network and that the Studio's file server is still running. If the PC can't get on that network, use an exFAT USB drive (FAT32 can't hold 8.5 GB). On the Studio run `cp -L ~/chimera-tools/worker-train/probes/fleet-out/{fleet-probe.exe,worker-q5.gguf} /Volumes/<drive>/`. The `-L` matters, because `worker-q5.gguf` there is a link. Then copy both files into `$HOME\fleet-probe` and run the last line of step 3 |
| `fleet-probe.exe` is missing, or Windows says it contains a virus | Windows Defender blocked it, which can happen with small unsigned programs. If the alert names `fleet-probe.exe`, open Windows Security, Protection history, choose Allow, then run its `curl.exe` line again |
| `ollama` isn't found | On a Mac use `/Applications/Ollama.app/Contents/Resources/ollama` in its place. On the PC, open a new PowerShell window |
| Anything else starting with `STOPPED` | Send me that line, the tool's first line, and any `Measuring` lines above it |

A second run on the same computer skips the copy into Ollama.

If the rule points to Qwen3-14B, the tool can measure it the same way once it's installed there:
`fleet-probe --model qwen3:14b`. Read its 8K and 16K lines: the plan gives Qwen a 16K limit, so a 32K FAIL there is
expected and isn't a rule result.

The tool's source is `worker-model/probes/fleet/`, and `build.sh` there rebuilds it.

# Screenshots

Makes the pictures in [`docs/screenshots/`](../../docs/screenshots) (the ones in the main README) from a made-up pool, so they can be taken again whenever the interface changes.

```bash
cd app && go build -o /tmp/chimera . && cd ..
python3 tests/screenshots/screenshots.py /tmp/chimera docs/screenshots
```

It takes under a minute. It needs Python 3 (standard library only), Chrome (set `CHROME` to its path if it isn't the Mac default) and a build of Chimera for the computer you run it on (not the Linux build on a Mac). It writes `network.png`, `models.png`, `chat.png`, `long-task.png`, `long-task-done.png` and `setup.png`.

## What it does

1. Starts four copies of the app, each with its own data folder, its own `HOME` and its own fake Ollama (`fake_ollama_shots.py`). Three are a pool called Friends: Maya's MacBook hosts it, Leo's Gaming PC and Priya's Mac mini join, and all three lend. The fourth is a fresh computer for the first-run card.
2. Drives the real interface in headless Chrome over the DevTools protocol (`cdp.py`, no Playwright): opens each tab, sends a chat to another computer, starts a long task, and waits for it to finish.
3. Saves the six PNGs, then stops everything, the workers before the host. It does that after an error or Ctrl-C too.

Everything on screen is invented: names, hardware, models, replies and the bakery plan. Three things the real app would show are replaced first, and the pictures should still be looked at before they're committed:

- The Network tab shows this computer's LAN address and an invite code. They're swapped for the examples the app's own join form uses, and the run stops if the real address is still on screen.
- The first-run card prefills this computer's real name. It's replaced with a made-up one.
- The Models page ends before its Tools block, which lists what is installed on this computer.

## Safe beside a real Chimera

It uses its own ports (interfaces 18470 to 18473, hub 18480, fake Ollamas 18434 to 18437, Chrome 19222), its own data folders and `HOME` in a temporary folder, and never the real Ollama. The pool is closed and `CHIMERA_NO_AUTOPOOL` is set, so it never merges with a real pool on the same Wi-Fi. The work folder is created fresh and removed afterwards.

## Changing what they show

- The pool's names, hardware and models: `DEVICES` and `MODELS` at the top of `stack.py`. Hardware goes through the app's `CHIMERA_SYSINFO` switch.
- The plan, the pieces and the replies: `fake_ollama_shots.py`.
- Window sizes and which views are captured: `shoot.py`. The chat pictures use a narrower window (1100 px) so the text stays readable when the README scales them down.

`stack.py` can also run on its own (`python3 stack.py /tmp/chimera /tmp/some-new-folder`) and keeps the pool up until `STOP` appears in that folder, so a person can open the four interfaces and look around.

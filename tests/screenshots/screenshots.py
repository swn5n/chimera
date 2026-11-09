"""Takes the screenshots in docs/screenshots from a made-up pool, in one go.

Usage: python3 screenshots.py <chimera binary> <folder for the pictures>
       (from the repository root: python3 tests/screenshots/screenshots.py /tmp/chimera docs/screenshots)

It starts four copies of the app (three computers in a pool called Friends, and a fresh one for the first-run card),
each with its own data folder and HOME and its own fake Ollama, drives the real interface in headless Chrome the way a
person would, saves six PNGs and stops everything again, workers before the host, also after an error or Ctrl-C.
Nothing on screen is real: names, hardware, models and replies are invented. See README.md in this folder."""
import os, shutil, signal, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shoot, stack


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    binary, out = sys.argv[1], os.path.abspath(sys.argv[2])
    if not os.path.isfile(binary):
        sys.exit("no such file: " + binary + " (build one with: cd app && go build -o /tmp/chimera .)")
    work = tempfile.mkdtemp(prefix="chimera-shots-")
    signal.signal(signal.SIGTERM, lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        stack.up(binary, work)
        shoot.run(out)
    finally:
        stack.down()
        shutil.rmtree(work, ignore_errors=True)


main()

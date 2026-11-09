"""datagen/pysandbox.py and datagen/code_gate.py.

The sandbox for real, under sandbox-exec: no network (not even to a socket this test listens on), no writes outside
the run folder, nothing of the user's home readable, no new processes, but Python's own standard library loads; a
timeout kills the script, also one that left its process group with setsid, and (unsandboxed, where it can fork) its
children; the watchdog kills a script whose parent is killed with kill -9; output is capped.

The code gate against a real Chimera binary, built from app/ once per run into a scratch folder ($WM_SCRATCH, else
data/scratch/; $CHIMERA_BIN's, copied there, when it names one) and removed afterwards; its Ollama is a stand-in (runner/mock_ollama), so the real one is never asked.
python-script and files joins, the seams that fail and those a dropped step excuses, Python's compile, the provided
symbols, the import run (crashes, timeouts, a missing module of the project's own), the teacher's tests and their stub
and hollow rules, crashes located in the piece (and usable as Go's workerCrash in Chimera's own repair request, with
the interpreter's own version as runner) but never taken from a failed teacher test, the plan check with Chimera's
result check and the files entry point, and the run cache (keyed by the interpreter, tool failures never cached).
After the smoke (Nov 3): files-mode tests see the candidate's own quiet modules (star-imported, and as step_modules),
the stub none; a (part) of structured data fails (part_not_mergeable) in the piece and the plan check while a
Markdown or Python part doesn't; a stub of another step's file fails (stub_for_other_step) but Block Kit
placeholder: keys, an empty __init__.py and "[]" data don't; the tell lines; tests_fault (a sandbox refusal, a
guessed module, a later step's module, a third-party module, and what stays unconfirmed) and no_python.
After the second check of the smoke (Nov 4): the harness's two lines are taken out of a run's output, and a run the
project or the tests end with SystemExit (sys.exit, argparse, exit("message"), after a printed traceback too) is the
script's verdict, cached: a test failure for the tests, import_exit for the import run, unsure for an entry point,
while a run Python never finished (os._exit) or never started is still an error; a files piece's JSON, TOML, YAML
and JavaScript files are parsed (parse:<ext>, with its line), tsconfig's comments, templates and JSX aren't failed,
an ES module .js is really parsed, and a JavaScript part is blamed only for what it broke; names_python and
no_python with the step's words; a step's own placeholders need a later title or their own word naming the owner,
and a longer placeholder that says so at its top is a stub; a module an earlier step names (a dropped one too) is
never third_party, "python-docx" is no docx module, and import_fault reads a kept piece's import run; run_tool runs
node in the same sandbox.
After the third check (Nov 4): YAML is composed, never constructed, so CloudFormation's, Home Assistant's, Ansible's,
mkdocs' and GitLab's tags pass (and an anchor set again), while broken syntax still fails; a file over 3 lines is
another step's stub only when it holds nothing but its note (a placeholder page, Python of stubs), so a step's own
real module or config headed by a TODO or "placeholder" naming another step passes; no_python is False for a Python
project; only a dropped earlier code step's words exempt a bare module name from third_party, and the texts the
caller adds (a variant's input pieces) count as written; piece_check's "tests" and "run" say what ran.
After the second smoke (Nov 4): a files piece whose root file imports a module the project has only in src/ fails
layout_import with a tell line and nothing run (a variant read against the pieces it was written for, project=), the
plan check fails entry_layout on such an entry and blames the file whose import failed (an earlier piece's bare
sibling import inside src/ too); a shell file is parsed by bash -n and lands in the gate's "parse"; tests that reached
only a module of a step outside the dependencies are tests_unreachable when the kept piece wrote its own file (the
rewrite's errors, kept apart, aren't read); a package imported only inside a function, unguarded and not installed,
is recorded as lazy_imports and makes a piece no tests ran on third_party.
"""
import glob
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from tests import _paths
from tests import datagen_fakes as F
from datagen import code_gate as G
from datagen import lang_check, layout
from datagen import pysandbox as P
from datagen.chimera import Chimera
from datagen.common import Cache
from runner import mock_ollama
from tools import blender_check

MARK = mock_ollama.MARK
SANDBOX = P.can_sandbox()

_bin = _tmp = _srv = None
_url = ""


def setUpModule():
    global _bin, _tmp, _srv, _url
    _tmp = tempfile.mkdtemp(prefix="test-datagen-code-", dir=blender_check.scratch_root())
    _srv, _url = mock_ollama.serve(0, os.path.join(_tmp, "ollama.jsonl"))
    if not F.HAVE_CHIMERA:
        return
    try:
        _bin = F.build_chimera(_tmp)  # a fresh copy of $CHIMERA_BIN, else built from app/
    except RuntimeError:
        shutil.rmtree(_tmp, ignore_errors=True)
        raise


def tearDownModule():
    if _srv:
        _srv.shutdown()
        _srv.server_close()
    if _tmp:
        shutil.rmtree(_tmp, ignore_errors=True)


def gone(pid, within=5.0):
    """The process has ended (and been reaped) within the time given."""
    end = time.monotonic() + within
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        time.sleep(0.05)
    return False


class WorkCase(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="work-", dir=_tmp)

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def run_py(self, code, **kw):
        return P.run({"main.py": MARK + "\n" + code}, "main.py", work=self.work, **kw)


# ---------------------------------------------------------------- the sandbox

@unittest.skipUnless(SANDBOX, "needs sandbox-exec (macOS)")
class SandboxTests(WorkCase):
    def test_a_run_gets_its_stdin_and_exit_code_and_leaves_nothing(self):
        r = self.run_py("import sys\nprint(sys.stdin.read().upper())\nraise SystemExit(3)\n", stdin="hello")
        self.assertEqual((r["exit"], r["output"], r["timed_out"], r["sandboxed"], r["cut"]),
                         (3, "HELLO\n", False, True, 0), r)
        self.assertEqual(os.listdir(self.work), [])  # the run folder is gone

    def test_pythons_own_standard_library_loads(self):
        r = self.run_py("import json, csv, decimal, hashlib, sqlite3, ssl, tempfile, zlib\n"
                        "db = sqlite3.connect(':memory:')\n"
                        "db.execute('create table t (x)')\n"
                        "fd, path = tempfile.mkstemp()\n"
                        "print('stdlib ok', json.dumps([decimal.Decimal('1.5') + 1], default=str), "
                        "hashlib.sha256(b'x').hexdigest()[:4])\n")
        self.assertEqual(r["exit"], 0, r)
        self.assertIn("stdlib ok", r["output"])

    def test_no_network_not_even_localhost(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        try:
            r = self.run_py("import socket\n"
                            f"for host, port in ((\"1.1.1.1\", 53), (\"127.0.0.1\", {port})):\n"
                            "    try:\n"
                            "        socket.create_connection((host, port), timeout=3)\n"
                            "        print('OPEN', host)\n"
                            "    except OSError as e:\n"
                            "        print('blocked', host, type(e).__name__)\n")
        finally:
            listener.close()
        self.assertEqual(r["exit"], 0, r)
        self.assertNotIn("OPEN", r["output"])
        self.assertIn("blocked 1.1.1.1 PermissionError", r["output"])
        self.assertIn("blocked 127.0.0.1 PermissionError", r["output"])

    def test_no_writes_outside_the_run_folder(self):
        outside = [os.path.join(self.work, "escape.txt"), os.path.join(_tmp, "escape.txt"),
                   os.path.join(os.path.dirname(_tmp), f"wm-escape-{os.getpid()}.txt")]
        r = self.run_py("import os\n"
                        "open('inside.txt', 'w').write('fine')\n"
                        "print('inside', open('inside.txt').read())\n"
                        "for p in [os.path.join(os.path.dirname(os.getcwd()), 'escape.txt')] + %r:\n"
                        "    try:\n"
                        "        open(p, 'w').write('x')\n"
                        "        print('WROTE', p)\n"
                        "    except OSError as e:\n"
                        "        print('denied', type(e).__name__)\n" % outside)
        self.assertEqual(r["exit"], 0, r)
        self.assertIn("inside fine", r["output"])
        self.assertNotIn("WROTE", r["output"])
        self.assertEqual(r["output"].count("denied PermissionError"), 4, r["output"])
        for p in outside:
            self.assertFalse(os.path.exists(p), p)

    def test_the_users_home_is_unreadable(self):
        home = os.path.expanduser("~")
        tries = [os.path.join(home, "Desktop"), os.path.abspath(__file__), os.path.join(home, ".zshrc")]
        r = self.run_py("import os\n"
                        "for p in %r:\n"
                        "    try:\n"
                        "        got = os.listdir(p) if os.path.isdir(p) else open(p).read()\n"
                        "        print('READ', p)\n"
                        "    except FileNotFoundError:\n"
                        "        print('missing')\n"
                        "    except OSError as e:\n"
                        "        print('denied', type(e).__name__)\n" % tries)
        self.assertEqual(r["exit"], 0, r)
        self.assertNotIn("READ", r["output"])
        self.assertGreaterEqual(r["output"].count("denied PermissionError"), 2, r["output"])
        self.assertTrue(os.path.isdir(tries[0]) and os.path.exists(tries[1]))  # they are there to be read

    def test_no_new_processes(self):
        r = self.run_py("import os, subprocess\n"
                        "try:\n"
                        "    pid = os.fork()\n"
                        "    if pid == 0:\n"
                        "        os._exit(0)\n"
                        "    print('FORKED')\n"
                        "except OSError as e:\n"
                        "    print('fork', type(e).__name__)\n"
                        "try:\n"
                        "    subprocess.run(['/bin/echo', 'RAN'])\n"
                        "except OSError as e:\n"
                        "    print('exec', type(e).__name__)\n")
        self.assertEqual(r["exit"], 0, r)
        self.assertIn("fork PermissionError", r["output"])
        self.assertIn("exec PermissionError", r["output"])
        self.assertNotIn("FORKED", r["output"])
        self.assertNotIn("RAN", r["output"])

    def test_a_timeout_kills_the_script(self):
        t0 = time.monotonic()
        r = self.run_py("import os\nprint('pid', os.getpid(), flush=True)\nwhile True:\n    pass\n", timeout=1)
        self.assertLess(time.monotonic() - t0, 1 + P._GRACE_S + 2)
        self.assertEqual((r["exit"], r["timed_out"]), (None, True), r)
        self.assertIn("(timed out after 1 s)", r["output"])
        self.assertTrue(gone(int(r["output"].split()[1])))

    def test_a_script_that_left_its_group_is_still_killed(self):
        r = self.run_py("import os, time\nos.setsid()\nprint('pid', os.getpid(), flush=True)\ntime.sleep(60)\n",
                        timeout=1)
        self.assertTrue(r["timed_out"], r)
        self.assertTrue(gone(int(r["output"].split()[1])), "the setsid script outlived its timeout")

    def test_the_watchdog_kills_a_script_whose_parent_is_killed(self):
        script = MARK + "\nimport os, time\nopen('pid', 'w').write(str(os.getpid()))\nwhile True:\n    time.sleep(0.1)\n"
        helper = subprocess.Popen([sys.executable, "-c",
                                   "import sys\nsys.path.insert(0, %r)\nfrom datagen import pysandbox\n"
                                   "pysandbox.run({'a.py': %r}, 'a.py', timeout=120, work=%r)\n"
                                   % (_paths.HERE, script, self.work)])
        try:
            pid, end = None, time.monotonic() + 15
            while pid is None and time.monotonic() < end:
                for f in glob.glob(os.path.join(self.work, "wm-py-*", "run", "pid")):
                    with open(f) as fh:
                        pid = int(fh.read() or 0) or None
                time.sleep(0.05)
            self.assertIsNotNone(pid, "the script never started")
            os.kill(helper.pid, signal.SIGKILL)
            helper.wait()
            self.assertTrue(gone(pid), "the script outlived its parent")
        finally:
            if helper.poll() is None:
                helper.kill()
                helper.wait()

    def test_output_is_capped_keeping_both_ends(self):
        r = self.run_py("print('start')\nprint('x' * 100000)\nprint('the end')\n")
        self.assertEqual(r["exit"], 0)
        self.assertLessEqual(len(r["output"]), P.OUTPUT_CAP)
        self.assertTrue(r["output"].startswith("start\n"))
        self.assertTrue(r["output"].endswith("the end\n"))
        self.assertGreater(r["cut"], 80000)
        self.assertIn(f"… ({r['cut']} characters cut) …", r["output"])
        self.assertEqual(len(r["output"]) - len(f"\n… ({r['cut']} characters cut) …\n") + r["cut"],
                         len("start\n") + 100001 + len("the end\n"))

    def test_the_run_folder_is_hidden_in_tracebacks(self):
        r = P.run({"pkg/mod.py": MARK + "\ndef f():\n    return 1 / 0\n",
                   "main.py": MARK + "\nimport sys\nsys.path.insert(0, '.')\nfrom pkg.mod import f\nf()\n"},
                  "main.py", work=self.work)
        self.assertEqual(r["exit"], 1)
        self.assertIn('File "pkg/mod.py", line 3, in f', r["output"])
        self.assertNotIn(self.work, r["output"])
        e = G.last_error(r["output"])
        self.assertEqual((e["type"], e["frames"][-1]["file"], e["frames"][-1]["line"], e["last"]),
                         ("ZeroDivisionError", "pkg/mod.py", 3, True))


class SandboxPlumbingTests(WorkCase):
    def test_paths_that_leave_the_folder_are_refused(self):
        for bad in ("../x.py", "/etc/x.py", "", "a/../../x.py", "src/", "C:/x.py"):
            with self.assertRaises(ValueError, msg=bad):
                P.run({bad: "x = 1\n", "main.py": "x = 1\n"}, "main.py", work=self.work)
        with self.assertRaises(ValueError):
            P.run({"a.py": "x = 1\n"}, "b.py", work=self.work)
        self.assertEqual(P.safe_path("./src//m.py"), "src/m.py")

    def test_the_profile_keeps_an_interpreter_in_a_home_folder_readable(self):
        prof = P.profile(self.work, "/Users/someone/.pyenv/versions/3.13.1/bin/python3")
        self.assertIn('(allow file-read* (subpath "%s") (subpath "/Users/someone/.pyenv/versions/3.13.1"))'
                      % os.path.realpath(self.work), prof)
        self.assertIn('(subpath "/Users/someone/.pyenv/versions/3.13.1"))', prof.split("process-exec*")[-1])
        prof = P.profile(self.work, "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3")
        self.assertIn('(allow file-read* (subpath "%s"))' % os.path.realpath(self.work), prof)
        self.assertIn("(deny network*)", prof)
        self.assertIn("(deny process-fork)", prof)

    @unittest.skipUnless(os.name == "posix", "needs fork")
    def test_unsandboxed_a_timeout_kills_the_scripts_children(self):
        r = self.run_py("import subprocess, time\nc = subprocess.Popen(['/bin/sleep', '30'])\n"
                        "print('child', c.pid, flush=True)\nwhile True:\n    time.sleep(0.1)\n",
                        timeout=1, sandbox=False)
        self.assertEqual((r["timed_out"], r["sandboxed"]), (True, False), r)
        self.assertTrue(gone(int(r["output"].split()[1])), "the child outlived the timeout")


# ---------------------------------------------------------------- fixtures: a python-script plan

PLAN = {"title": "Word counter", "kind": "code", "summary": "A word counter that prints the top words. " + MARK,
        "steps": [{"id": "s1", "title": "Counting", "kind": "code",
                   "instructions": "Write count_words(text) returning a dict of lower-case word counts."},
                  {"id": "s2", "title": "Report", "kind": "code", "depends_on": ["s1"],
                   "instructions": "Write top_words(counts, n), the n most common (word, count) pairs, and main(), "
                                   "which reads standard input and prints the top 3."}]}


def piece(code, provides, uses="none"):
    return f"```python\n{MARK}\n{code}```\n\n```handoff\nprovides: {provides}\nuses: {uses}\nassumed: none\n```"


P1 = piece("import re\n\n\ndef count_words(text):\n    counts = {}\n    for w in re.findall(r\"[a-z']+\", text.lower()):\n"
           "        counts[w] = counts.get(w, 0) + 1\n    return counts\n", "count_words(text) -> dict of word counts")
TOP = "def top_words(counts, n):\n    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]\n"
MAIN = "\n\ndef main():\n    counts = count_words(sys.stdin.read())\n    for w, c in top_words(counts, 3):\n" \
       "        print(w, c)\n"
P2 = piece("import sys\n\n\n" + TOP + MAIN, "top_words(counts, n), main()", "count_words from s1")
P2_ITEMZ = P2.replace("counts.items()", "counts.itemz()")
P2_DUP = piece("import sys\n\n\n" + TOP + "\n\ndef count_words(text):\n    return {}\n" + MAIN,
               "top_words(counts, n), main()", "count_words from s1")
P2_ARGS = piece("import sys\n\n\n" + TOP.replace("(counts, n)", "(counts, counts)") + MAIN,
                "top_words(counts, n), main()", "count_words from s1")
P2_SYMBOL = piece("import sys\n\n\n" + TOP + MAIN, "top_words(counts, n), main() and `format_report(pairs)`",
                  "count_words from s1")
P2_INTO_S1 = piece("import sys\n\n\ndef top_words(counts, n):\n    extra = count_words(n)\n"
                   "    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]\n" + MAIN,
                   "top_words(counts, n), main()", "count_words from s1")
P2_IMPORT = piece("import sys\n\n\nclass Report:\n    LIMIT = DEFAULT_LIMIT\n\n\n" + TOP + MAIN,
                  "top_words(counts, n), main(), Report", "count_words from s1")
P2_MAIN_CRASH = P2.replace("for w, c in top_words(counts, 3):", "for w, c in top_word(counts, 3):")
P2_ITEMZ_ON_IMPORT = P2_ITEMZ.replace("\n\ndef main():", "\n\nSAMPLE = top_words({'a': 1}, 1)\n\n\ndef main():")
P2_INTO_S1_ON_IMPORT = P2_INTO_S1.replace("\n\ndef main():", "\n\nSAMPLE = top_words({'a': 1}, 1)\n\n\ndef main():")
P1_SPIN = P1.replace("    return counts\n", "    return counts\n\n\ndef _spin():\n    while True:\n        pass\n\n\n"
                                            "READY = _spin()\n")
TESTS2 = MARK + "\nassert top_words({'a': 2, 'b': 1, 'c': 2}, 2) == [('a', 2), ('c', 2)]\n" \
                "assert top_words(count_words('b a b'), 1) == [('b', 2)]\nprint('tests ok')\n"
NAMES_ONLY = MARK + "\nassert callable(top_words)\nprint('tests ok')\n"  # names the step's symbol, checks nothing
MAIN_PLAN = {"title": "Word report", "kind": "code", "summary": "Count words and report them. " + MARK, "steps": [
    {"id": "s1", "title": "Count", "kind": "code", "depends_on": [],
     "instructions": "Write count_words(text), which returns a dict of each lower-cased word's count."},
    {"id": "s2", "title": "Report", "kind": "code", "depends_on": [],
     "instructions": "Write report(counts), which returns the lines 'word: n', most frequent first."},
    {"id": "s3", "title": "Main", "kind": "code", "depends_on": ["s1", "s2"],
     "instructions": "Write main(), which prints report(count_words('a b a'))."}]}
REPORT = piece("def report(counts):\n    return [f'{w}: {n}' for w, n in sorted(counts.items(), key=lambda x: -x[1])]"
               "\n", "report(counts) -> list of str")
MAIN3 = piece("def main():\n    for line in report(count_words('a b a')):\n        print(line)\n", "main()",
              "count_words from s1 (assumed); report from s2")


# ---------------------------------------------------------------- fixtures: a files plan

FPLAN = {"title": "Notes tool", "kind": "code", "summary": "A small notes store with a command line. " + MARK,
         "steps": [{"id": "s1", "title": "Store", "kind": "code",
                    "instructions": "Write store.py with class Store(path) and methods add(text) and all()."},
                   {"id": "s2", "title": "CLI", "kind": "code", "depends_on": ["s1"],
                    "instructions": "Write cli.py with main(), which adds its arguments as a note and prints all."}]}
STORE = (MARK + "\nimport json\nimport os\n\n\nclass Store:\n    def __init__(self, path):\n        self.path = path\n\n"
         "    def add(self, text):\n        notes = self.all()\n        notes.append(text)\n"
         "        with open(self.path, \"w\") as f:\n            json.dump(notes, f)\n\n"
         "    def all(self):\n        if not os.path.exists(self.path):\n            return []\n"
         "        with open(self.path) as f:\n            return json.load(f)\n")
CLI = (MARK + "\nimport sys\n\nfrom store import Store\n\n\ndef main():\n    s = Store(\"notes.json\")\n"
       "    s.add(\" \".join(sys.argv[1:]) or \"empty\")\n    for n in s.all():\n        print(n)\n\n\n"
       "if __name__ == \"__main__\":\n    main()\n")


def files_piece(path, body, provides, uses="none"):
    return f"File: {path}\n```python\n{body}```\n\n```handoff\nprovides: {provides}\nuses: {uses}\nassumed: none\n```"


F1 = files_piece("store.py", STORE, "store.py with Store(path), Store.add(text), Store.all()")
F2 = files_piece("cli.py", CLI, "cli.py with main(); run with python3 cli.py <note>", "Store from s1")
F1_BAD = F1.replace("notes.append(text)", "notes.appendd(text)")
F1_ARGS = F1.replace("def add(self, text):", "def add(self, text, text):")
F2_SHOP = F2.replace("from store import Store", "from store import Shop")
F1_LIMIT = F1.replace("\n\n\nclass Store:", "\n\n\ndef _limit():\n    return MAX_NOTES\n\n\nLIMIT = _limit()\n\n\n"
                                            "class Store:")  # a NameError when store.py is imported
FTESTS = MARK + "\nfrom store import Store\ns = Store('t.json')\ns.add('a')\ns.add('b')\n" \
                "assert s.all() == ['a', 'b']\nassert Store('t.json').all() == ['a', 'b']\n"

# A tally tool in a package; its Format step (s3) is the one that gets dropped.
TPLAN = {"title": "Tally tool", "kind": "code", "summary": "Totals a line of numbers. " + MARK, "steps": [
    {"id": "s1", "title": "Parser", "kind": "code", "depends_on": [],
     "instructions": "Write tool/parse.py with parse_line(line), the line's comma-separated fields, stripped."},
    {"id": "s2", "title": "Totals", "kind": "code", "depends_on": ["s1"],
     "instructions": "Write tool/totals.py with total(line), the sum of the line's fields, using parse_line from s1."},
    {"id": "s3", "title": "Format", "kind": "code", "depends_on": ["s1"],
     "instructions": "Write tool/fmt.py with show(n), which returns 'total: <n>'."},
    {"id": "s4", "title": "Main", "kind": "code", "depends_on": ["s2", "s3"],
     "instructions": "Write tool/main.py with main(), which prints the total of the line '1,2,3'."}]}
TGOAL = "A small command-line tool that totals a comma-separated line of numbers. " + MARK
T1 = files_piece("tool/parse.py", MARK + "\ndef parse_line(line):\n    return [f.strip() for f in line.split(',') if "
                 "f.strip()]\n", "tool/parse.py: parse_line(line) -> list of str")
T2 = files_piece("tool/totals.py", MARK + "\nfrom tool.parse import parse_line\n\n\ndef total(line):\n"
                 "    return sum(int(f) for f in parse_line(line))\n", "tool/totals.py: total(line) -> int",
                 "parse_line from s1")
T3_IMPORTLIB = files_piece("tool/fmt.py", MARK + "\nimport importlib\n\nparse = importlib.import_module("
                           "\"tool.parsee\")\n\n\ndef show(n):\n    return \"total: %d\" % n\n",
                           "tool/fmt.py: show(n) -> str", "parse_line from s1")  # Go can't see it; Python can


def tally_main(imports, uses="total from s2; show from s3 (assumed)"):
    return files_piece("tool/main.py", MARK + "\n" + imports + "\n\n\ndef main():\n    print(show(total('1,2,3')))"
                       "\n\n\nif __name__ == '__main__':\n    main()\n",
                       "tool/main.py: main(), run with python3 tool/main.py", uses)


# A contacts tool whose second step names no file of its own (as n-python-0001-02's did in the smoke).
CPLAN = {"title": "Contacts", "kind": "code", "summary": "A contacts list on the command line. " + MARK, "steps": [
    {"id": "s1", "title": "Store", "kind": "code", "depends_on": [],
     "instructions": "Write contacts_store.py with DATA_FILE = 'contacts.json', load() and save(contacts)."},
    {"id": "s2", "title": "Add command", "kind": "code", "depends_on": ["s1"],
     "instructions": "Write the command that adds a contact, cmd_add(name, email), using load and save from s1."},
    {"id": "s3", "title": "Main", "kind": "code", "depends_on": ["s2"],
     "instructions": "Write contactmgr.py with main(), which calls cmd_add with its arguments."}]}
C1 = files_piece("contacts_store.py", MARK + "\nimport json\nimport os\n\nDATA_FILE = 'contacts.json'\n\n\ndef load():\n"
                 "    if not os.path.exists(DATA_FILE):\n        return []\n    with open(DATA_FILE) as f:\n"
                 "        return json.load(f)\n\n\ndef save(contacts):\n    with open(DATA_FILE, 'w') as f:\n"
                 "        json.dump(contacts, f)\n", "contacts_store.py: DATA_FILE, load(), save(contacts)")
C2 = files_piece("cmd_add.py", MARK + "\nfrom contacts_store import load, save\n\n\ndef cmd_add(name, email):\n"
                 "    contacts = load()\n    contacts.append({'name': name, 'email': email})\n    save(contacts)\n"
                 "    return len(contacts)\n", "cmd_add.py: cmd_add(name, email)", "load, save from s1")
C2_RUNS = C2.replace("    return len(contacts)\n", "    return len(contacts)\n\n\ncmd_add('x', 'y')\n")  # not quiet
CTESTS = (MARK + "\nimport contacts_store\nassert [m.__name__ for m in step_modules] == ['cmd_add']\n"
          "assert cmd_add('Ann', 'ann@example.org') == 1\n"
          "assert [c['name'] for c in contacts_store.load()] == ['Ann']\nprint('tests ok')\n")

T4 = tally_main("from tool.totals import total\nfrom tool.fmt import show")  # the dropped step's module, by its name
T4_TRY = tally_main("from tool.totals import total\ntry:\n    from tool.fmt import show\nexcept ImportError:\n"
                    "    def show(n):\n        return 'total: %d' % n")
T4_PKG = tally_main("from tool.totals import total\nfrom tool import fmt\nshow = fmt.show")
T4_PASS = tally_main("from tool.totals import total\ntry:\n    from tool.fmt import show\nexcept ImportError:\n"
                     "    pass")  # a NameError for show when main() runs
T4_TYPO = tally_main("from tool.totls import total\nfrom tool.fmt import show")  # s2's module, misspelt
T4_PKG_TYPO = tally_main("from tool import totls\nfrom tool.fmt import show\ntotal = totls.total")
T4_UNNAMED = tally_main("from tool.totals import total\nfrom tool.colours import show")  # no step names it


@unittest.skipUnless(F.HAVE_CHIMERA and SANDBOX, "needs Go to build Chimera (or CHIMERA_BIN), and sandbox-exec")
class GateCase(WorkCase):
    def setUp(self):
        super().setUp()
        self.ch = Chimera(_bin, env={"OLLAMA_HOST": _url})
        self.gate = G.CodeGate(self.ch, Cache(os.path.join(self.work, "runs.jsonl")), work=self.work)

    def verdict(self, plan, i, text, mode):
        ids = {st["id"]: f"s{k + 1}" for k, st in enumerate(plan["steps"])}
        deps = [ids[d] for d in plan["steps"][i].get("depends_on") or []]
        return self.ch.validate([{"text": text, "mode": mode, "sid": f"s{i + 1}", "deps": deps,
                                  "step": plan["steps"][i]}])[0]

    def check(self, i, text, earlier=None, tests=None, plan=PLAN, mode="python-script"):
        v = self.verdict(plan, i, text, mode)
        self.assertTrue(v["form_ok"], v["issues"])  # the gate only sees what the validator let through
        return self.gate.piece_check(plan, i, text, v, earlier or {}, mode, tests=tests)


class PythonScriptTests(GateCase):
    def test_good_pieces_pass_with_an_import_run(self):
        got = self.check(0, P1)
        self.assertEqual((got["ok"], got["reasons"], got["stage"], got["crash"]), (True, [], "done", None), got)
        self.assertEqual((got["run"]["exit"], got["run"]["sandboxed"]), (0, True))
        got = self.check(1, P2, {"s1": P1}, tests={"code": TESTS2, "valid": True})
        self.assertTrue(got["ok"], got)
        self.assertTrue(got["tests"]["passed"])

    def test_earlier_pieces_by_plan_id_or_worker_name(self):
        plan = dict(PLAN, steps=[dict(PLAN["steps"][0], id="count"), dict(PLAN["steps"][1], id="report",
                                                                             depends_on=["count"])])
        for earlier in ({"count": P1}, {"s1": P1}):
            got = self.check(1, P2, earlier, tests=TESTS2, plan=plan)
            self.assertTrue(got["ok"], (earlier, got))
        self.assertEqual(self.check(1, P2, {}, tests=TESTS2, plan=plan)["reasons"], ["tests_failed"])

    def test_the_goal_is_read_for_the_mode(self):
        v = self.verdict(PLAN, 0, P1, "python-script")
        got = self.gate.piece_check(PLAN, 0, P1, v, {}, "python-script", goal="Put it in src/count.py. " + MARK)
        self.assertEqual(got["reasons"], ["mode_mismatch"])  # with that goal Chimera makes it a files plan

    def test_a_name_defined_twice_fails_the_join(self):
        got = self.check(1, P2_DUP, {"s1": P1})
        self.assertEqual((got["ok"], got["reasons"], got["stage"]), (False, ["seam:duplicate_name"], "join"), got)

    def test_a_piece_that_parses_but_wont_compile(self):
        got = self.check(1, P2_ARGS, {"s1": P1})  # Go's reader takes it; Python's compiler doesn't
        self.assertEqual((got["reasons"], got["stage"]), (["compile"], "compile"), got)
        self.assertIn("duplicate argument 'counts'", got["compile_error"])
        self.assertEqual({k: got["crash"][k] for k in ("step", "function", "piece_line", "runner")},
                         {"step": "s2", "function": "top_words", "piece_line": 5, "runner": self.gate.runner})

    def test_a_provided_name_the_piece_lacks(self):
        got = self.check(1, P2_SYMBOL, {"s1": P1})
        self.assertEqual((got["reasons"], got["symbols_missing"]), (["symbols_missing"], ["format_report"]), got)

    def test_crashes_name_the_python_that_ran_them_as_chimera_does(self):
        said = subprocess.run([P.python3(), "--version"], capture_output=True, text=True).stdout.strip()
        self.assertTrue(said.startswith("Python 3."), said)
        self.assertEqual(self.gate.runner, said)
        check = self.gate.plan_check(PLAN, {"s1": P1, "s2": P2_MAIN_CRASH}, PLAN["summary"])["check"]
        self.assertEqual((check["runner"], check["stated"]), (said, said))  # what Chimera's own check ran
        self.assertEqual(self.check(1, P2_IMPORT, {"s1": P1})["crash"]["runner"], said)

    def test_a_failed_teacher_test_is_no_crash_to_repair_from(self):
        got = self.check(1, P2_ITEMZ, {"s1": P1}, tests={"code": TESTS2, "valid": True})
        self.assertEqual((got["reasons"], got["stage"], got["crash"]), (["tests_failed"], "run", None), got)
        self.assertIn("AttributeError: 'dict' object has no attribute 'itemz'", got["tests"]["error"])
        self.assertEqual(got["run"]["exit"], 0)  # the import run, all Chimera's own check could show of it here

    def test_a_crash_on_import_is_located_and_makes_chimeras_repair_request(self):
        got = self.check(1, P2_ITEMZ_ON_IMPORT, {"s1": P1}, tests={"code": TESTS2, "valid": True})
        self.assertEqual((got["reasons"], got["stage"]), (["tests_failed", "import_crash"], "run"), got)
        crash = got["crash"]
        self.assertEqual({k: crash[k] for k in ("step", "part", "function", "piece_line", "runner")},
                         {"step": "s2", "part": "code", "function": "top_words", "piece_line": 6,
                          "runner": self.gate.runner})
        self.assertEqual(crash["source"], "return sorted(counts.itemz(), key=lambda kv: (-kv[1], kv[0]))[:n]")
        joined = self.ch.join(PLAN, {"s1": P1, "s2": P2_ITEMZ_ON_IMPORT})["script"].split("\n")
        self.assertEqual(joined[crash["line"] - 1].strip(), crash["source"])
        req = self.ch.worker_request(PLAN, 1, {"s1": P1}, piece=P2_ITEMZ_ON_IMPORT, crash=crash)
        self.assertIn(f"Your piece crashed when Chimera ran the joined script in {self.gate.runner}:\nline 6 in "
                      "top_words: return sorted(counts.itemz(), key=lambda kv: (-kv[1], kv[0]))[:n]\nAttributeError: "
                      "'dict' object has no attribute 'itemz'", req["messages"][1]["content"])

    def test_a_crash_inside_an_earlier_steps_code_isnt_this_pieces(self):
        got = self.check(1, P2_INTO_S1_ON_IMPORT, {"s1": P1})
        self.assertEqual(got["reasons"], ["import_crash"], got)
        self.assertIn("AttributeError: 'int' object has no attribute 'lower'", got["run"]["error"])
        self.assertIsNone(got["crash"])

    def test_without_tests_a_crash_on_import_fails_and_is_located(self):
        got = self.check(1, P2_IMPORT, {"s1": P1})
        self.assertEqual(got["reasons"], ["import_crash"], got)
        self.assertEqual({k: got["crash"][k] for k in ("step", "function", "piece_line", "error")},
                         {"step": "s2", "function": "Report", "piece_line": 6,
                          "error": "NameError: name 'DEFAULT_LIMIT' is not defined"})

    def test_an_import_that_never_ends_fails(self):
        gate = G.CodeGate(self.ch, None, work=self.work, timeout=2)
        got = gate.piece_check(PLAN, 0, P1_SPIN, self.verdict(PLAN, 0, P1_SPIN, "python-script"), {}, "python-script")
        self.assertEqual((got["ok"], got["reasons"], got["crash"]), (False, ["import_timeout"], None), got)
        self.assertTrue(got["run"]["timed_out"])

    def test_tests_that_arent_valid_are_not_run(self):
        got = self.check(1, P2_ITEMZ, {"s1": P1}, tests={"code": TESTS2, "valid": False})
        self.assertTrue(got["ok"], got)  # only the import run: the bug isn't reached
        self.assertIsNone(got["tests"])

    def test_runs_are_cached(self):
        first = self.check(1, P2, {"s1": P1}, tests=TESTS2)
        with open(os.path.join(self.work, "runs.jsonl")) as f:
            lines = f.read()
        again = G.CodeGate(self.ch, Cache(os.path.join(self.work, "runs.jsonl")), work=self.work).piece_check(
            PLAN, 1, P2, self.verdict(PLAN, 1, P2, "python-script"), {"s1": P1}, "python-script", tests=TESTS2)
        self.assertEqual((first["tests"]["cached"], again["tests"]["cached"]), (False, True))
        self.assertEqual(first["tests"]["passed"], again["tests"]["passed"])
        with open(os.path.join(self.work, "runs.jsonl")) as f:
            self.assertEqual(f.read(), lines)


class RunCacheTests(GateCase):
    def runs(self):
        path = os.path.join(self.work, "runs.jsonl")
        if not os.path.exists(path):
            return 0
        with open(path) as f:
            return len(f.read().splitlines())

    def test_a_run_that_says_nothing_about_the_script_is_an_error_and_isnt_cached(self):
        for code, why in (("raise SystemExit(3)\n", "exit 3 with no Python traceback"),
                          ("import os\nos._exit(71)\n", "the interpreter couldn't run the script (exit 71)")):
            files = {"main.py": MARK + "\n" + code}
            for _ in range(2):
                r = self.gate.run(files, "main.py")
                self.assertEqual((r["error"], r["cached"]), (why, False), r)
        self.assertEqual(self.runs(), 0)
        for code in ("1 / 0\n", "print('tests ok')\nraise SystemExit(1)\n", "while True:\n    pass\n"):
            gate = G.CodeGate(self.ch, self.gate.cache, work=self.work, timeout=1)
            files = {"main.py": MARK + "\n" + code}
            self.assertNotIn("error", gate.run(files, "main.py"), code)  # the script's own verdict
            self.assertTrue(gate.run(files, "main.py")["cached"], code)
        self.assertEqual(self.runs(), 3)

    @unittest.skipUnless(os.path.exists("/usr/bin/python3"), "no /usr/bin/python3")
    def test_an_interpreter_that_cant_start_in_the_sandbox_is_an_error(self):
        self.gate.python, self.gate.runner = "/usr/bin/python3", P.version("/usr/bin/python3") or G.RUNNER
        r = self.gate.run({"main.py": MARK + "\nprint('hi')\n"}, "main.py")
        if r["exit"] == 0:
            self.skipTest("this /usr/bin/python3 runs in the sandbox")  # not the Xcode shim
        self.assertEqual((r["exit"], r["error"], r["cached"]), (71, "the interpreter couldn't run the script (exit 71)",
                                                                 False), r)
        self.assertEqual(self.runs(), 0)

    def test_the_run_key_has_the_interpreters_real_path_and_version(self):
        files = {"main.py": MARK + "\nprint('hi')\n"}
        self.assertEqual([self.gate.run(files, "main.py")["cached"] for _ in range(2)], [False, True])
        python, link = self.gate.python, os.path.join(self.work, "python3")
        os.symlink(os.path.realpath(python), link)
        self.gate.python = link
        self.assertTrue(self.gate.run(files, "main.py")["cached"])  # the same interpreter by another path
        self.gate.python, self.gate.runner = python, "Python 3.0.1"
        self.assertFalse(self.gate.run(files, "main.py")["cached"])


class TestsRuleTests(GateCase):
    def test_tests_fail_on_the_stub_and_pass_on_a_candidate(self):
        got = self.gate.tests_check(PLAN, 1, TESTS2, {"s1": P1}, [P2_ITEMZ, P2], "python-script")
        self.assertEqual((got["valid"], got["why"], got["stub_failed"], got["passed"]),
                         (True, "", True, [False, True]), got)
        self.assertEqual(got["stub"]["error"], "NameError: name 'top_words' is not defined")
        self.assertEqual((got["hollow"]["candidate"], got["hollow"]["error"]), (1, "AssertionError"), got)

    def test_tests_that_only_name_the_steps_symbols_dont_count(self):
        got = self.gate.tests_check(PLAN, 1, NAMES_ONLY, {"s1": P1}, [P2], "python-script")
        self.assertEqual((got["valid"], got["why"], got["stub_failed"], got["passed"]),
                         (False, "passes_on_hollow", True, [True]), got)
        self.assertEqual((got["hollow"]["candidate"], got["hollow"]["error"]), (0, None))

    def test_tests_that_pass_on_the_stub_dont_count(self):
        got = self.gate.tests_check(PLAN, 1, MARK + "\nassert count_words('a a') == {'a': 2}\nprint('tests ok')\n",
                                    {"s1": P1}, [P2], "python-script")
        self.assertEqual((got["valid"], got["why"], got["stub_failed"]), (False, "passes_on_stub", False), got)

    def test_tests_no_candidate_passes_dont_count(self):
        wrong = TESTS2.replace("[('b', 2)]", "[('b', 3)]")
        got = self.gate.tests_check(PLAN, 1, wrong, {"s1": P1}, [P2, P2_ITEMZ], "python-script")
        self.assertEqual((got["valid"], got["why"], got["passed"]), (False, "no_candidate_passed", [False, False]))
        self.assertIn("AssertionError", got["errors"][0])

    def test_tests_must_reach_their_end(self):
        quiet = TESTS2.replace("print('tests ok')\n", "")
        got = self.gate.tests_check(PLAN, 1, quiet, {"s1": P1}, [P2], "python-script")
        self.assertFalse(got["valid"])
        self.assertEqual(got["errors"][0], "exited 0 without printing 'tests ok'")

    def test_empty_or_broken_tests(self):
        for code, why in (("", "no_tests"), ("assert (\n", "tests_syntax")):
            got = self.gate.tests_check(PLAN, 1, code, {"s1": P1}, [P2], "python-script")
            self.assertEqual((got["valid"], got["why"], got["passed"]), (False, why, [False]))

    def test_a_first_steps_stub_is_an_empty_project(self):
        tests = MARK + "\nassert count_words('A a b') == {'a': 2, 'b': 1}\nprint('tests ok')\n"
        got = self.gate.tests_check(PLAN, 0, tests, {}, [P1], "python-script")
        self.assertEqual((got["valid"], got["passed"]), (True, [True]), got)


class FilesTests(GateCase):
    def check(self, i, text, earlier=None, tests=None, plan=FPLAN, mode="files"):
        return super().check(i, text, earlier, tests, plan, mode)

    def test_good_files_pieces_pass(self):
        got = self.check(0, F1)
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["run"]["exit"], 0)  # store.py imported: it only defines things
        got = self.check(1, F2, {"s1": F1})
        self.assertTrue(got["ok"], got)

    def test_an_import_that_doesnt_resolve_fails(self):
        got = self.check(1, F2_SHOP, {"s1": F1})
        self.assertEqual(got["reasons"], ["seam:import_unresolved"], got)

    def test_a_dropped_dependency_excuses_an_unresolved_import(self):
        plan = {"title": "Notes app", "kind": "code", "summary": "Notes in app/. " + MARK, "steps": [
            {"id": "s1", "title": "Store", "kind": "code", "instructions": "Write app/store.py with class Store."},
            {"id": "s2", "title": "CLI", "kind": "code", "depends_on": ["s1"],
             "instructions": "Write app/cli.py with main(), using app.store's Store."}]}
        cli = files_piece("app/cli.py", CLI.replace("from store import", "from app.store import"), "app/cli.py: main()",
                          "Store from s1")
        other = files_piece("app/store.py", MARK + "\nclass Shop:\n    pass\n", "app/store.py: Shop")
        self.assertEqual(self.check(1, cli, {"s1": other}, plan=plan)["reasons"], ["seam:import_unresolved"])
        self.assertTrue(self.check(1, cli, {}, plan=plan)["ok"])  # s1 was dropped, and s2 was told it failed

    def test_a_merged_file_that_wont_compile_is_located_in_the_block(self):
        got = self.check(0, F1_ARGS)
        self.assertEqual(got["reasons"], ["compile"], got)
        self.assertEqual({k: got["crash"][k] for k in ("step", "function", "piece_line")},
                         {"step": "s1", "function": "store.py", "piece_line": 10})

    def test_files_tests_and_a_crash_in_a_block(self):
        tc = self.gate.tests_check(FPLAN, 0, FTESTS, {}, [F1_BAD, F1], "files")
        self.assertEqual((tc["valid"], tc["passed"]), (False, [False, False]))  # FTESTS has no "tests ok" line
        tests = FTESTS + "print('tests ok')\n"
        tc = self.gate.tests_check(FPLAN, 0, tests, {}, [F1_BAD, F1], "files")
        self.assertEqual((tc["valid"], tc["passed"], tc["stub"]["error"], tc["hollow"]["error"]),
                         (True, [False, True], "ModuleNotFoundError: No module named 'store'", "AssertionError"), tc)
        tc = self.gate.tests_check(FPLAN, 0, MARK + "\nfrom store import Store\nassert Store\nprint('tests ok')\n", {},
                                   [F1], "files")
        self.assertEqual((tc["valid"], tc["why"]), (False, "passes_on_hollow"), tc)
        got = self.check(0, F1_BAD, tests={"code": tests, "valid": True})
        self.assertEqual((got["reasons"], got["crash"]), (["tests_failed"], None), got)  # a teacher test's failure
        got = self.check(0, F1_LIMIT, tests={"code": tests, "valid": True})
        self.assertEqual(got["reasons"], ["tests_failed", "import_crash"], got)
        self.assertEqual({k: got["crash"][k] for k in ("step", "function", "piece_line", "source", "runner")},
                         {"step": "s1", "function": "_limit in store.py", "piece_line": 7,
                          "source": "return MAX_NOTES", "runner": self.gate.runner})

    def test_an_import_of_a_dropped_steps_module_is_excused_in_the_piece_and_the_plan(self):
        earlier = {"s1": T1, "s2": T2}  # s3, Format (tool/fmt.py), was dropped, and Main was told so
        for main, entry in ((T4, "unsure"), (T4_TRY, "passed"), (T4_PKG, "unsure"), (T4_PASS, "unsure_dropped")):
            got = self.check(3, main, earlier, plan=TPLAN)
            self.assertTrue(got["ok"], got)
            self.assertEqual([s["code"] for s in got["excused"]], ["import_unresolved"])
            pc = self.gate.plan_check(TPLAN, dict(earlier, s4=main), TGOAL)
            self.assertEqual((pc["ok"], pc["reasons"], pc["entry"]["outcome"]), (True, [], entry), pc)
        got = self.check(3, T4, earlier, plan=dict(TPLAN, steps=TPLAN["steps"][:2] + [
            dict(TPLAN["steps"][2], instructions="Write the formatting, show(n), which returns 'total: <n>'.")] +
            TPLAN["steps"][3:]))
        self.assertEqual(got["reasons"], ["seam:import_unresolved"], got)  # a module no dropped step names

    def test_a_misspelt_or_unnamed_import_isnt_excused_by_a_dropped_step(self):
        earlier = {"s1": T1, "s2": T2}
        for main in (T4_TYPO, T4_PKG_TYPO, T4_UNNAMED):
            got = self.check(3, main, earlier, plan=TPLAN)
            self.assertEqual(got["reasons"], ["seam:import_unresolved"], got)
            pc = self.gate.plan_check(TPLAN, dict(earlier, s4=main), TGOAL)
            self.assertEqual((pc["ok"], pc["reasons"]), (False, ["seam:import_unresolved"]), pc)

    def test_a_missing_module_of_the_projects_own_fails_the_import_run(self):
        got = self.check(2, T3_IMPORTLIB, {"s1": T1, "s2": T2}, plan=TPLAN)
        self.assertEqual((got["reasons"], got["crash"]), (["import_crash"], None), got)
        self.assertEqual(got["run"]["error"], "ModuleNotFoundError: No module named 'tool.parsee'")
        other = T3_IMPORTLIB.replace('"tool.parsee"', '"wm_not_installed"')  # not the project's: the computer's?
        self.assertTrue(self.check(2, other, {"s1": T1, "s2": T2}, plan=TPLAN)["ok"])


def block(path, lang, body, part=False):
    return f"File: {path}{' (part)' if part else ''}\n```{lang}\n{body}\n```\n"


def handoff(provides, uses="none"):
    return f"\n```handoff\nprovides: {provides}\nuses: {uses}\nassumed: none\n```"


# A bot whose s1 writes package.json and README.md and whose s2 adds to both (the smoke's coding-0012-01 round 2 s6).
JPLAN = {"title": "Poll bot", "kind": "code", "summary": "A small bot with a deploy script. " + MARK, "steps": [
    {"id": "s1", "title": "Project files", "kind": "code", "depends_on": [],
     "instructions": "Write package.json (name poll-bot, a start script) and README.md with the title."},
    {"id": "s2", "title": "Deploy", "kind": "code", "depends_on": ["s1"],
     "instructions": "Add a deploy script to package.json, a Deploy section to README.md and deploy.py with "
                     "deploy()."}]}
PKG = '{\n  "name": "poll-bot",\n  "scripts": {\n    "start": "node index.js"\n  }\n}'
J1 = block("package.json", "json", PKG) + "\n" + block("README.md", "markdown", "# Poll bot\n\n" + MARK.lstrip("# ")) \
    + handoff("package.json with a start script; README.md")
DEPLOY = block("deploy.py", "python", MARK + "\ndef deploy():\n    return 'vercel --prod'")
J2_JSON = block("package.json", "json", '{\n  "scripts": {\n    "deploy": "vercel --prod"\n  }\n}', part=True) + \
    "\n" + DEPLOY + handoff("deploy.py: deploy(); a deploy script in package.json", "package.json from s1")
J2_MD = block("README.md", "markdown", "## Deploy\n\nRun `npm run deploy`.", part=True) + "\n" + DEPLOY + \
    handoff("deploy.py: deploy(); a Deploy section in README.md", "README.md from s1")

# A Slack app whose setup step stubs the files later steps own (coding-0012-01 round 1 s1 in the smoke).
SPLAN = {"title": "Slack poll", "kind": "code", "summary": "A Slack poll app in Node. " + MARK, "steps": [
    {"id": "s1", "title": "Set up the project", "kind": "code", "depends_on": [],
     "instructions": "Create package.json with the dependency @slack/bolt and a .gitignore."},
    {"id": "s2", "title": "Write src/index.js", "kind": "code", "depends_on": ["s1"],
     "instructions": "Write the Bolt app's entry point, which opens the modal from s3."},
    {"id": "s3", "title": "Poll modal", "kind": "code", "depends_on": [],
     "instructions": "Write src/modal.js exporting pollModal, a Block Kit modal with a question input, and read "
                     "data/polls.json."}]}
S1_OWN = block("package.json", "json", '{\n  "name": "slack-poll",\n  "dependencies": {"@slack/bolt": "^3.15.0"}\n}'
               ) + "\n" + block(".gitignore", "text", "node_modules/\n.env")
S1_STUBS = S1_OWN + "\n" + block("src/index.js", "js", "// Placeholder - the full Bolt app is provided by step s2.") + \
    "\n" + block("src/modal.js", "js", "// TODO: the modal") + handoff("package.json, .gitignore")
S1_HOLLOW = S1_OWN + "\n" + block("src/modal.js", "js", "/* " + MARK.lstrip("# ") + " */") + \
    handoff("package.json, .gitignore")  # nothing but a comment, for a file s3 owns
S1_DATA = S1_OWN + "\n" + block("data/polls.json", "json", "[]") + "\n" + \
    block("src/notes.js", "js", "// Notes for whoever reads this repo. " + MARK.lstrip("# ")) + \
    handoff("package.json, .gitignore, data/polls.json")  # data, and a comment file no later step names
S3_BLOCK_KIT = block("src/modal.js", "js", "// " + MARK.lstrip("# ") + "\nconst pollModal = {\n  type: 'modal',\n"
                     "  blocks: [{type: 'input', element: {type: 'plain_text_input', placeholder: {type: 'plain_text',"
                     " text: 'Your question'}}}],\n};\nmodule.exports = { pollModal };") + \
    handoff("src/modal.js: pollModal")

# A package whose first step's __init__.py is empty and named by the next step.
IPLAN = {"title": "Tally package", "kind": "code", "summary": "A tally package. " + MARK, "steps": [
    {"id": "s1", "title": "Package", "kind": "code", "depends_on": [],
     "instructions": "Write tool/parse.py with parse_line(line), and make tool a package."},
    {"id": "s2", "title": "Totals", "kind": "code", "depends_on": ["s1"],
     "instructions": "Write tool/totals.py with total(line), importing parse_line from tool (tool/__init__.py)."}]}
I1 = block("tool/__init__.py", "python", "") + "\n" + \
    block("tool/parse.py", "python", MARK + "\ndef parse_line(line):\n    return line.split(',')") + \
    handoff("tool/parse.py: parse_line(line); tool/__init__.py")


class FilesTestsHarnessTests(GateCase):
    def check(self, i, text, earlier=None, tests=None, plan=CPLAN, mode="files"):
        return super().check(i, text, earlier, tests, plan, mode)

    def test_the_tests_see_the_steps_own_modules_and_the_stub_none(self):
        got = self.gate.tests_check(CPLAN, 1, CTESTS, {"s1": C1}, [C2_RUNS, C2], "files")
        self.assertEqual((got["valid"], got["why"], got["passed"]), (True, "", [False, True]), got)
        self.assertEqual(got["stub"]["error"], "NameError: name 'step_modules' is not defined")
        self.assertEqual(got["errors"][0], "NameError: name 'step_modules' is not defined")  # not quiet: not imported
        self.assertEqual((got["hollow"]["candidate"], got["hollow"]["error"]), (1, "AssertionError"), got)
        tests = CTESTS.replace("assert [m.__name__ for m in step_modules] == ['cmd_add']\n", "")
        self.assertEqual(self.gate.tests_check(CPLAN, 1, tests, {"s1": C1}, [C2], "files")["stub"]["error"],
                         "NameError: name 'cmd_add' is not defined")
        got = self.check(1, C2, {"s1": C1}, tests={"code": CTESTS, "valid": True})
        self.assertEqual((got["ok"], got["tests"]["passed"]), (True, True), got)

    def test_a_test_can_patch_a_step_modules_globals(self):
        tests = (MARK + "\nimport os\nsaved = []\nstep_modules[0].save = saved.append  # cmd_add's own global\n"
                 "assert cmd_add('Bo', 'bo@example.org') == 1\n"
                 "assert saved == [[{'name': 'Bo', 'email': 'bo@example.org'}]]\n"
                 "assert not os.path.exists('contacts.json')\n"
                 "print('tests ok')\n")
        got = self.check(1, C2, {"s1": C1}, tests={"code": tests, "valid": True})
        self.assertTrue(got["tests"]["passed"], got)

    def test_python_script_tests_are_as_before(self):
        prelude = self.gate._with_tests({G.PROJECT: "x = 1\n"}, "python-script", "pass")[G.TESTS_FILE]
        self.assertEqual(prelude, G.HARNESS + 'import sys\nsys.path.insert(0, ".")\nimport project\n'
                                  'from project import *\n\npass\n')


class StructuredPartTests(GateCase):
    def check(self, i, text, earlier=None, tests=None, plan=JPLAN, mode="files"):
        return super().check(i, text, earlier, tests, plan, mode)

    def test_a_part_of_a_json_file_fails_in_the_piece_and_the_plan(self):
        got = self.check(1, J2_JSON, {"s1": J1})
        self.assertEqual((got["ok"], got["reasons"], got["stage"]), (False, ["seam:part_not_mergeable"], "join"), got)
        self.assertEqual(got["tell"], ["package.json is structured data, so a (part) block of it can't be added to "
                                       "the file: write it whole, and only if your step owns it"])
        pc = self.gate.plan_check(JPLAN, {"s1": J1, "s2": J2_JSON}, "")
        self.assertEqual((pc["ok"], pc["reasons"], pc["culprit"]), (False, ["seam:part_not_mergeable"], "s2"), pc)
        alone = self.check(1, J2_JSON)  # a part alone is still a part: nobody's file can take it
        self.assertEqual(alone["reasons"], ["seam:part_not_mergeable"], alone)

    def test_a_markdown_part_still_appends(self):
        got = self.check(1, J2_MD, {"s1": J1})
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["tell"], [])
        self.assertTrue(self.gate.plan_check(JPLAN, {"s1": J1, "s2": J2_MD}, "")["ok"])

    def test_which_paths_are_structured(self):
        for path in ("package.json", "a/b.JSON", "pyproject.toml", "ci.yml", "k8s/app.yaml", "yarn.lock",
                     "Pipfile", "x/Pipfile", "pom.xml", "nb.ipynb", "bun.lockb"):
            self.assertTrue(G.STRUCTURED.search(path), path)
        for path in ("README.md", ".gitignore", ".env", "notes.txt", "app.py", "Pipfile.txt", "lockfile.md"):
            self.assertFalse(G.STRUCTURED.search(path), path)


class StubTests(GateCase):
    def check(self, i, text, earlier=None, tests=None, plan=SPLAN, mode="files"):
        return super().check(i, text, earlier, tests, plan, mode)

    def test_stubs_of_later_steps_files_fail(self):
        got = self.check(0, S1_STUBS)
        self.assertEqual((got["ok"], got["reasons"], got["stubs"]),
                         (False, ["stub_for_other_step"], ["src/index.js", "src/modal.js"]), got)
        self.assertEqual(got["tell"], [
            "it writes src/index.js, which step s2 owns: write only the files your step owns",
            "it writes src/modal.js, which step s3 owns: write only the files your step owns"])
        got = self.check(0, S1_HOLLOW)
        self.assertEqual((got["reasons"], got["stubs"]), (["stub_for_other_step"], ["src/modal.js"]), got)

    def test_data_block_kit_placeholders_and_an_empty_init_are_not_stubs(self):
        for plan, i, text in ((SPLAN, 0, S1_OWN + handoff("package.json, .gitignore")), (SPLAN, 0, S1_DATA),
                              (SPLAN, 2, S3_BLOCK_KIT), (IPLAN, 0, I1)):
            got = self.check(i, text, plan=plan)
            self.assertTrue(got["ok"], (text, got))
            self.assertEqual(got["stubs"], [])
        v = self.verdict(SPLAN, 2, S3_BLOCK_KIT, "files")
        self.assertIn("placeholder", [x["code"] for x in v["issues"]])  # Go's warning fires; the stub rule doesn't

    def test_a_stub_that_names_its_owner_or_a_later_step(self):
        own = lambda body, path="src/index.js": [type("FP", (), {"path": path, "part": False, "body": body})()]
        for body, want in (("// Placeholder - full app provided by step s2.", [("src/index.js", "s2")]),
                           ("// Implementation will be added in a later step.", [("src/index.js", "s2")]),
                           ("# later steps overwrite this", [("src/index.js", "s2")]),
                           ('{\n  "_comment": "full config written in step s3."\n}', [("src/index.js", "s3")]),
                           ("// provided by step s1\nconst app = 1;", []),  # its own id names nobody else
                           ("// provided by step s1", [("src/index.js", "s2")]),  # but only a comment: s2's title
                           ("// the app; s2 reads it\nconst a = 1;\nconst b = 2;\nconst c = 3;", [])):
            self.assertEqual(G.stubs_for_others(SPLAN, 0, own(body)), want, body)
        self.assertEqual(G.stubs_for_others(SPLAN, 0, own("// notes", "src/util.js")), [])  # no step names it


class TellTests(GateCase):
    def test_what_the_next_try_is_told(self):
        got = self.check(1, P2_SYMBOL, {"s1": P1})
        self.assertEqual(got["tell"], ["its handoff's provides line names format_report, which the piece doesn't "
                                       "define"])
        got = self.check(1, P2_IMPORT, {"s1": P1})
        self.assertEqual(got["tell"], ["importing it crashed: NameError: name 'DEFAULT_LIMIT' is not defined"])
        got = self.check(1, P2_DUP, {"s1": P1})
        self.assertEqual(len(got["tell"]), 1)
        self.assertTrue(got["tell"][0].startswith("the join says: "), got["tell"])
        got = self.check(1, P2_ARGS, {"s1": P1})
        self.assertEqual(got["tell"], ["it doesn't compile: line 5: SyntaxError: duplicate argument 'counts' in "
                                       "function definition"])
        got = self.check(1, P2_ITEMZ, {"s1": P1}, tests={"code": TESTS2, "valid": True})
        self.assertEqual((got["reasons"], got["tell"]), (["tests_failed"], []), got)  # a teacher test isn't told
        self.assertEqual(self.check(1, P2, {"s1": P1})["tell"], [])


class TestsFaultTests(GateCase):
    def test_tests_that_start_a_process_are_unreachable(self):
        tests = (MARK + "\nimport subprocess, sys\nr = subprocess.run([sys.executable, '-m', 'cmd_add'], "
                        "capture_output=True)\nassert r.returncode == 0\nprint('tests ok')\n")
        tc = self.gate.tests_check(CPLAN, 1, tests, {"s1": C1}, [C2], "files")
        self.assertEqual((tc["why"], tc["stub"]["error"]), ("no_candidate_passed",
                                                            "PermissionError: [Errno 1] Operation not permitted"), tc)
        self.assertEqual(G.tests_fault({"code": tests, "check": tc}, CPLAN, 1, [C2]), "tests_unreachable")

    def test_a_guessed_module_or_a_later_steps_is_unreachable(self):
        for module in ("add_cmd", "contactmgr"):  # no step names add_cmd; contactmgr is s3's
            tests = MARK + f"\nfrom {module} import cmd_add\nassert cmd_add('a', 'b') == 1\nprint('tests ok')\n"
            tc = self.gate.tests_check(CPLAN, 1, tests, {"s1": C1}, [C2], "files")
            self.assertEqual(tc["errors"], [f"ModuleNotFoundError: No module named '{module}'"], tc)
            self.assertEqual(G.tests_fault({"code": tests, "check": tc}, CPLAN, 1, [C2]), "tests_unreachable")
            self.assertEqual(G.tests_fault({"code": tests, "check": tc}, CPLAN, 1), "tests_unreachable")
        tests = (MARK + "\nimport contacts_store\ntry:\n    from add_cmd import cmd_add\nexcept ImportError as e:\n"
                 "    raise ImportError('Could not import cmd_add from add_cmd') from e\nprint('tests ok')\n")
        tc = self.gate.tests_check(CPLAN, 1, tests, {"s1": C1}, [C2], "files")
        self.assertEqual(tc["errors"], ["ImportError: Could not import cmd_add from add_cmd"], tc)
        self.assertEqual(G.tests_fault({"code": tests, "check": tc}, CPLAN, 1, [C2]), "tests_unreachable")
        self.assertIsNone(G.tests_fault({"code": tests, "check": tc}, CPLAN, 1))  # which module: needs the candidates
        tests = MARK + "\nfrom contacts_store import DATA_FILE\nassert cmd_add('a', 'b') == 2\nprint('tests ok')\n"
        tc = self.gate.tests_check(CPLAN, 1, tests, {"s1": C1}, [C2], "files")
        self.assertIsNone(G.tests_fault({"code": tests, "check": tc}, CPLAN, 1, [C2]), tc)  # an AssertionError

    def test_a_missing_third_party_module_the_candidates_import(self):
        piece = files_piece("report.py", MARK + "\nimport wm_not_installed_docx\n\n\ndef cmd_add(name, email):\n"
                            "    return wm_not_installed_docx.Document()\n", "report.py: cmd_add(name, email)")
        tc = self.gate.tests_check(CPLAN, 1, CTESTS, {"s1": C1}, [piece], "files")
        self.assertEqual(tc["errors"], ["ModuleNotFoundError: No module named 'wm_not_installed_docx'"], tc)
        record = {"code": CTESTS, "check": tc}
        self.assertEqual(G.tests_fault(record, CPLAN, 1, [piece]), "third_party")
        self.assertEqual(G.tests_fault(dict(record, candidates=[piece]), CPLAN, 1), "third_party")
        self.assertEqual(G.tests_fault(record, CPLAN, 1), "third_party")  # the tests don't import it: a candidate does

    def test_what_stays_unconfirmed(self):
        stub = {"exit": 1, "error": "NameError: name 'cmd_add' is not defined", "timed_out": False}
        named = MARK + "\nfrom contacts_store import load\nprint('tests ok')\n"
        for record in (
                {"code": "x", "check": {"stub": stub, "errors": ["AssertionError"], "passed": [False]}},
                {"code": "x", "check": {"stub": stub, "errors": [None], "passed": [True]}},  # a candidate passed
                {"code": named, "check": {"stub": dict(stub, error="ModuleNotFoundError: No module named "
                                                                   "'contacts_store'"),
                                          "errors": ["ModuleNotFoundError: No module named 'contacts_store'"]}},
                {"code": MARK + "\nimport os\nos.listdir('x')\n",  # refused, but the tests start no process
                 "check": {"stub": dict(stub, error="PermissionError: [Errno 1] Operation not permitted"),
                           "errors": ["PermissionError: [Errno 1] Operation not permitted"]}},
                {"code": "x", "check": None}):
            self.assertIsNone(G.tests_fault(record, CPLAN, 1, [C2]), record)
        gone = "ModuleNotFoundError: No module named 'add_cmd'"
        mixed = {"code": "import add_cmd", "check": {"stub": dict(stub, error=gone), "errors": ["AssertionError"]},
                 "errors": [{"error": gone}]}
        self.assertIsNone(G.tests_fault(mixed, CPLAN, 1, [C2]))  # one candidate got past the import


class NoPythonTests(unittest.TestCase):
    def test_a_files_step_without_python(self):
        self.assertTrue(G.no_python([S1_OWN + handoff("package.json"), S3_BLOCK_KIT], "files"))
        self.assertFalse(G.no_python([S3_BLOCK_KIT, J2_JSON], "files"))  # deploy.py
        self.assertFalse(G.no_python([S3_BLOCK_KIT], "python-script"))
        self.assertFalse(G.no_python([], "files"))
        self.assertFalse(G.no_python(None, "files"))


class PlanCheckTests(GateCase):
    def test_a_python_script_plan_runs_chimeras_check(self):
        got = self.gate.plan_check(PLAN, {"s1": P1, "s2": P2}, PLAN["summary"])
        self.assertEqual((got["ok"], got["mode"], got["check"]["outcome"]), (True, "python-script", "passed"), got)
        self.assertTrue(got["check"]["runner"].startswith("Python"))

    def test_a_crashing_main_names_its_step(self):
        got = self.gate.plan_check(PLAN, {"s1": P1, "s2": P2_MAIN_CRASH}, PLAN["summary"])
        self.assertEqual((got["ok"], got["reasons"], got["culprit"], got["check"]["outcome"]),
                         (False, ["entry_failed"], "s2", "failed"), got)
        again = self.gate.plan_check(PLAN, {"s1": P1, "s2": P2_MAIN_CRASH}, PLAN["summary"])
        self.assertTrue(again["check"]["cached"])

    def test_a_name_a_dropped_step_was_to_give_is_unsure_not_failed(self):
        goal = "Count words in a text and report them; run it with main(). " + MARK
        got = self.gate.plan_check(MAIN_PLAN, {"s2": REPORT, "s3": MAIN3}, goal)  # s1, Count, was dropped
        self.assertEqual((got["ok"], got["reasons"], got["check"]["outcome"]), (True, [], "unsure_dropped"), got)
        self.assertEqual(got["check"]["error"], "NameError: name 'count_words' is not defined")
        typo = MAIN3.replace("count_words(", "count_wordz(")  # a name the dropped step never gave
        got = self.gate.plan_check(MAIN_PLAN, {"s2": REPORT, "s3": typo}, goal)
        self.assertEqual((got["ok"], got["reasons"], got["culprit"]), (False, ["entry_failed"], "s3"), got)
        got = self.gate.plan_check(MAIN_PLAN, {"s1": P1, "s3": MAIN3}, goal)  # s2, Report, dropped instead
        self.assertEqual((got["ok"], got["check"]["outcome"]), (True, "unsure_dropped"), got)
        self.assertTrue(got["check"]["error"].startswith("NameError: name 'report' is not defined"), got)

    def test_no_main_means_nothing_to_run(self):
        got = self.gate.plan_check(PLAN, {"s1": P1}, "")
        self.assertEqual((got["ok"], got["check"]["outcome"]), (True, "skipped"), got)

    def test_a_files_plan_runs_its_entry_point(self):
        got = self.gate.plan_check(FPLAN, {"s1": F1, "s2": F2}, "")
        self.assertEqual((got["ok"], got["entry"]["path"], got["entry"]["outcome"]), (True, "cli.py", "passed"), got)
        got = self.gate.plan_check(FPLAN, {"s1": F1_BAD, "s2": F2}, "")
        self.assertEqual((got["ok"], got["reasons"], got["culprit"], got["entry"]["outcome"]),
                         (False, ["entry_failed"], "s1", "failed"), got)

    def test_a_seam_names_its_step(self):
        got = self.gate.plan_check(PLAN, {"s1": P1, "s2": P2_DUP}, "")
        self.assertEqual((got["ok"], got["reasons"], got["culprit"]), (False, ["seam:duplicate_name"], "s2"), got)


class HollowTests(unittest.TestCase):
    def test_function_and_method_bodies_return_none_and_the_rest_stays(self):
        head = MARK + "\nimport re\n\nLIMIT = 3  # kept\n\n\ndef f(a, b=\"é\"):\n"
        code = (head + "    \"\"\"Doc.\"\"\"\n    c = a + 1\n    return c\n\n\nclass K:\n    N = 2\n\n    @property\n"
                "    def p(self): return self.N * \"é\"  # one line\n\n    async def q(self):\n        yield 1\n")
        self.assertEqual(G.hollow(code), head + "    return None\n\n\nclass K:\n    N = 2\n\n    @property\n"
                         "    def p(self): return None  # one line\n\n    async def q(self):\n        return None\n")
        self.assertIsNone(G.hollow("def f(:\n"))

    def test_a_piece_is_hollowed_block_by_block(self):
        self.assertEqual(G.hollow_piece(P1), P1.replace(
            "    counts = {}\n    for w in re.findall(r\"[a-z']+\", text.lower()):\n"
            "        counts[w] = counts.get(w, 0) + 1\n    return counts\n", "    return None\n"))
        both = F1 + "\n\nFile: cli.py\n```python\n" + MARK + "\ndef main():\n    print(1)\n```\n"
        hollow = G.hollow_piece(both)
        self.assertIn("    def add(self, text):\n        return None\n", hollow)
        self.assertIn("def main():\n    return None\n```", hollow)
        self.assertIn("```handoff\nprovides: store.py with Store(path)", hollow)
        self.assertIsNone(G.hollow_piece(piece("LIMIT = 3\n", "LIMIT")))  # nothing to hollow


class ProvidesTests(unittest.TestCase):
    def test_names_as_code_are_strict_and_words_are_loose(self):
        strict, loose = G.provided_symbols(
            "count_words(text, top_n=10) -> dict; `WordCounter.add(word)`; prints \"tests ok\"; runs with "
            "python3 main.py or src/app.py; the word_counts mapping; uses print() and len()")
        self.assertEqual((strict, loose), (["WordCounter.add", "count_words"], ["word_counts"]))
        self.assertEqual(G.provided_symbols("none"), ([], []))

    def test_missing_symbols(self):
        tops = {"count_words", "WordCounter", "json"}
        hay = "class WordCounter:\n    def add(self, w):\n        return json.dumps(w)\n"
        self.assertEqual(G.missing_symbols("count_words(), `WordCounter.add`, json.dumps()", tops, hay), [])
        self.assertEqual(G.missing_symbols("top_words(), `WordCounter.remove()`, word_counts", tops, hay),
                         ["WordCounter.remove", "top_words", "word_counts"])


# ---------------------------------------------------------------- after the second check of the smoke (Nov 4)

NODE = shutil.which("node")

P2_EXIT = P2.replace("def top_words(counts, n):\n", "def top_words(counts, n):\n    if n > 1:\n        sys.exit(1)\n")
P2_TOP_EXIT = P2.replace("\n\ndef main():", "\n\ndef _limit():\n    sys.exit(3)\n\n\nLIMIT = _limit()\n\n\n"
                                            "def main():")  # exits when it is imported
P2_DOCX = P2.replace("import sys\n", "import sys\nimport wm_not_installed_docx\n", 1)
F2_ARGS = files_piece("cli.py", MARK + "\nimport argparse\n\nfrom store import Store\n\n\ndef main():\n"
                      "    p = argparse.ArgumentParser()\n    p.add_argument('--text', required=True)\n"
                      "    Store('notes.json').add(p.parse_args().text)\n\n\nif __name__ == '__main__':\n    main()\n",
                      "cli.py with main(); run with python3 cli.py --text <note>", "Store from s1")


class HarnessTests(GateCase):
    """G10: a run the project or the tests end with SystemExit is their verdict, cached; one Python never finished
    is a tool failure, as before."""

    def harnessed(self, code):
        return {"main.py": G.HARNESS + MARK + "\n" + code}

    def test_the_harness_lines_are_taken_out_and_kept_as_flags(self):
        r = self.gate.run(self.harnessed("print('hello')\n"), "main.py")
        self.assertEqual((r["exit"], r["output"], r["harness"]), (0, "hello\n", {"started": True, "ended": True}), r)
        r = self.gate.run(self.harnessed("import sys\nsys.stdout.write('no newline')\n"), "main.py")
        self.assertEqual(r["output"], "no newline")
        r = self.gate.run(self.harnessed("import sys\nsys.stdout = open('elsewhere.txt', 'w')\nprint('x')\n"),
                          "main.py")  # the end line goes to fd 1 whatever the tests did with sys.stdout
        self.assertEqual((r["exit"], r["harness"]["ended"]), (0, True), r)
        # tests that import every .py file in the folder import themselves too (n-python-0001-02 s5's, in the smoke)
        files = {"main.py": G.HARNESS + MARK + "\nimport importlib, os\nfor f in sorted(os.listdir('.')):\n"
                                         "    try:\n        importlib.import_module(f[:-3])\n"
                                         "    except Exception:\n        pass\n"
                                         "assert False, 'the real failure'\n"}
        r = self.gate.run(files, "main.py")
        self.assertEqual((r["exit"], G._run_error(r), G.system_exit(r)),
                         (1, "AssertionError: the real failure", False), r)
        self.assertNotIn("wm-harness", r["output"])

    def test_a_system_exit_is_the_scripts_verdict_and_is_cached(self):
        for code, exit_code, error in (
                ("raise SystemExit(1)\n", 1, "SystemExit: exit 1 with no traceback"),
                ("import argparse\np = argparse.ArgumentParser(prog='cli')\np.add_argument('--name', required=True)\n"
                 "p.parse_args([])\n", 2, "SystemExit: exit 2 with no traceback (its last output: cli: error: the "
                                          "following arguments are required: --name)"),
                ("import sys\nprint('starting')\nsys.exit('bad input')\n", 1,
                 "SystemExit: exit 1 with no traceback (its last output: bad input)"),
                ("import traceback\ntry:\n    1 / 0\nexcept ZeroDivisionError:\n    traceback.print_exc()\n"
                 "raise SystemExit(4)\n", 4, "SystemExit: exit 4 with no traceback (its last output: "
                                             "ZeroDivisionError: division by zero)")):
            files = self.harnessed(code)
            r = self.gate.run(files, "main.py")
            self.assertEqual((r["exit"], r.get("error"), r["cached"], G.system_exit(r)),
                             (exit_code, None, False, True), r)
            self.assertEqual(G._run_error(r), error)
            self.assertTrue(self.gate.run(files, "main.py")["cached"])
        r = self.gate.run(self.harnessed("1 / 0\n"), "main.py")  # a traceback says it all, as before
        self.assertEqual((G.system_exit(r), G._run_error(r)), (False, "ZeroDivisionError: division by zero"))

    def test_python_that_never_finished_is_still_an_error(self):
        files = self.harnessed("import os\nprint('x', flush=True)\nos._exit(1)\n")
        for _ in range(2):
            r = self.gate.run(files, "main.py")
            self.assertEqual((r["error"], r["cached"], r["harness"]),
                             ("exit 1 with no Python traceback, and Python didn't finish", False,
                              {"started": True, "ended": False}), r)
        self.assertEqual(G.tool_failure({"exit": 1, "output": "", "harness": {"started": False, "ended": False}}),
                         "the interpreter didn't start the script (exit 1)")
        self.assertEqual(G.tool_failure({"exit": 71, "output": "", "harness": {"started": False, "ended": False}}),
                         "the interpreter couldn't run the script (exit 71)")
        self.assertIsNone(G.tool_failure({"exit": 127, "output": "", "harness": {"started": True, "ended": True}}))

    def test_tests_that_end_in_system_exit_fail_the_piece_on_its_tests(self):
        tests = {"code": TESTS2, "valid": True}
        got = self.check(1, P2_EXIT, {"s1": P1}, tests=tests)
        self.assertEqual((got["ok"], got["reasons"], got["stage"], got["crash"]),
                         (False, ["tests_failed"], "run", None), got)  # not run_error: untested() gates it again
        self.assertEqual((got["tests"]["error"], got["tests"]["cached"], got["run"]["error"]),
                         ("SystemExit: exit 1 with no traceback", False, None), got)
        self.assertEqual(got["tell"], [])  # a teacher test is never told
        self.assertTrue(self.check(1, P2_EXIT, {"s1": P1}, tests=tests)["tests"]["cached"])
        tc = self.gate.tests_check(PLAN, 1, TESTS2, {"s1": P1}, [P2_EXIT, P2], "python-script")
        self.assertEqual((tc["valid"], tc["passed"], tc["errors"][0]),
                         (True, [False, True], "SystemExit: exit 1 with no traceback"), tc)

    def test_an_import_that_exits_fails(self):
        got = self.check(1, P2_TOP_EXIT, {"s1": P1})
        self.assertEqual((got["ok"], got["reasons"], got["stage"]), (False, ["import_exit"], "run"), got)
        self.assertEqual(got["tell"], ["importing it exited (exit 3) before it finished: nothing should run when it "
                                       "is imported"])
        self.assertTrue(got["run"]["cached"] is False and got["run"]["error"].startswith("SystemExit: exit 3"), got)

    def test_an_entry_point_that_exits_on_its_arguments_is_unsure(self):
        got = self.gate.plan_check(FPLAN, {"s1": F1, "s2": F2_ARGS}, "")
        self.assertEqual((got["ok"], got["entry"]["outcome"], got["entry"]["exit"]), (True, "unsure", 2), got)
        self.assertTrue(got["entry"]["error"].startswith("SystemExit: exit 2 with no traceback"), got)


# A web project's config files, and a JavaScript part added later.
DPLAN = {"title": "Web config", "kind": "code", "summary": "A small web service's files. " + MARK, "steps": [
    {"id": "s1", "title": "Config files", "kind": "code", "depends_on": [],
     "instructions": "Write config.json with the port, settings.yml with the log level, pyproject.toml with the "
                     "name, tsconfig.json for the build, and src/app.js with start()."},
    {"id": "s2", "title": "Routes", "kind": "code", "depends_on": ["s1"],
     "instructions": "Add routes() to src/app.js."}]}
JS_MARK = "// " + MARK.lstrip("# ")
D_JSON = '{\n  "port": 8080\n}'
D_YAML = MARK + "\nlog_level: info\nhosts:\n  - a\n  - b"
D_TOML = MARK + '\n[project]\nname = "web"'
D_TSCONFIG = '{\n  // the build\n  "compilerOptions": {"strict": true, /* on */},\n}'
D_JS = JS_MARK + "\nfunction start() {\n  return 1;\n}\nmodule.exports = { start };"


def config_piece(json_body=D_JSON, yaml_body=D_YAML, toml_body=D_TOML, js_body=D_JS, extra=""):
    return (block("config.json", "json", json_body) + "\n" + block("settings.yml", "yaml", yaml_body) + "\n" +
            block("pyproject.toml", "toml", toml_body) + "\n" + block("tsconfig.json", "json", D_TSCONFIG) + "\n" +
            block("src/app.js", "javascript", js_body) + extra +
            handoff("config.json, settings.yml, pyproject.toml, tsconfig.json, src/app.js with start()"))


def routes_part(body="function routes() {\n  return ['/'];\n}"):
    return block("src/app.js", "javascript", JS_MARK + "\n" + body, part=True) + \
        handoff("routes() in src/app.js", "start from s1")


class ParseTests(GateCase):
    """K2: a files piece's other files are parsed (JSON, TOML, YAML, JavaScript) and a file that doesn't parse
    fails it, with a tell line; what a checker can't read isn't failed."""

    def check(self, i, text, earlier=None, tests=None, plan=DPLAN, mode="files"):
        return super().check(i, text, earlier, tests, plan, mode)

    def test_files_that_parse_pass_and_are_recorded(self):
        got = self.check(0, config_piece())
        self.assertEqual((got["ok"], got["reasons"]), (True, []), got)
        kinds = {p["path"]: (p["kind"], p.get("ok"), p.get("skipped")) for p in got["parse"]}
        self.assertEqual(kinds["tsconfig.json"], ("JSON", True, None))  # comments and trailing commas: tsc's own
        self.assertEqual(kinds["settings.yml"], ("YAML", True, None))
        self.assertEqual(kinds["pyproject.toml"], ("TOML", True, None))
        self.assertEqual(kinds["src/app.js"], ("JavaScript", True, None) if NODE else
                         ("JavaScript", None, "no node on PATH"))

    def test_a_file_that_doesnt_parse_fails_with_its_line(self):
        for piece_text, reason, tell in (
                (config_piece(json_body='{\n  "port": 8080\n  "host": "x"\n}'), "parse:json",
                 "config.json isn't valid JSON: line 3: Expecting ',' delimiter"),
                (config_piece(json_body='{\n  // the port\n  "port": 8080\n}'), "parse:json",
                 "config.json isn't valid JSON: line 2: Expecting property name enclosed in double quotes"),
                (config_piece(yaml_body=MARK + "\nlog_level: [info\nhosts: 2"), "parse:yml",
                 "settings.yml isn't valid YAML: line 3: while parsing a flow sequence expected ',' or ']', but got "
                 "':'"),
                (config_piece(toml_body=MARK + "\n[project]\nname = "), "parse:toml",
                 "pyproject.toml isn't valid TOML: line 3: Invalid value (at line 3, column 8)")):
            got = self.check(0, piece_text)
            self.assertEqual((got["ok"], got["reasons"], got["stage"], got["crash"]),
                             (False, [reason], "compile", None), got)
            self.assertEqual(got["tell"], [tell])
        got = self.check(0, config_piece(json_body="{,}", toml_body="x ="))
        self.assertEqual(got["reasons"], ["parse:json", "parse:toml"], got)  # every file is told, not the first only

    @unittest.skipUnless(NODE, "node isn't on PATH")
    def test_javascript_is_parsed_by_node_and_cached(self):
        got = self.check(0, config_piece(js_body=JS_MARK + "\nfunction start( {\n  return 1;\n}"))
        self.assertEqual((got["reasons"], got["tell"]),
                         (["parse:js"], ["src/app.js isn't valid JavaScript: line 3: SyntaxError: Unexpected number"]),
                         got)
        again = self.check(0, config_piece(js_body=JS_MARK + "\nfunction start( {\n  return 1;\n}"))
        self.assertTrue(next(p for p in again["parse"] if p["path"] == "src/app.js").get("cached") is not False)
        esm = JS_MARK + "\nimport fs from 'fs';\nexport function start() {\n  return fs;\n}\nawait 1;"
        self.assertTrue(self.check(0, config_piece(js_body=esm))["ok"])
        got = self.check(0, config_piece(js_body=esm.replace("start() {", "start( {")))  # node --check alone passes it
        self.assertEqual((got["reasons"], got["tell"]), (["parse:js"], [
            "src/app.js isn't valid JavaScript: line 4: SyntaxError: Unexpected identifier 'fs'"]), got)
        jsx = JS_MARK + "\nexport const start = () => <div className=\"app\">hi</div>;"
        got = self.check(0, config_piece(js_body=jsx))
        self.assertEqual(got["reasons"], [], got)  # node can't read JSX: not the piece's fault
        self.assertEqual(next(p for p in got["parse"] if p["path"] == "src/app.js")["skipped"],
                         "jsx or flow, which node can't read")

    def test_templates_arent_failed(self):
        helm = block("chart/templates/svc.yaml", "yaml", MARK + "\nimage: {{ .Values.image }}:{{ .Values.tag }}\n"
                     "labels:\n  {{- include \"web.labels\" . | nindent 4 }}")
        got = self.check(0, config_piece(extra="\n" + helm))
        self.assertEqual(got["reasons"], [], got)
        self.assertEqual(next(p for p in got["parse"] if p["path"] == "chart/templates/svc.yaml")["skipped"],
                         "a template")
        flow = block("chart/templates/svc.yaml", "yaml", MARK + "\nport: {{ .Values.port }}\nname: {{ include "
                     "\"web.name\" . }}")  # YAML as it stands: flow mappings
        got = self.check(0, config_piece(extra="\n" + flow))
        self.assertEqual(got["reasons"], [], got)
        self.assertTrue(next(p for p in got["parse"] if p["path"] == "chart/templates/svc.yaml")["ok"])

    @unittest.skipUnless(NODE, "node isn't on PATH")
    def test_a_javascript_part_is_blamed_only_for_what_it_broke(self):
        got = self.check(1, routes_part(), {"s1": config_piece()})
        self.assertEqual((got["ok"], got["reasons"]), (True, []), got)
        got = self.check(1, routes_part("function routes( {\n  return ['/'];\n}"), {"s1": config_piece()})
        self.assertEqual(got["reasons"], ["parse:js"], got)
        broken = config_piece(js_body=JS_MARK + "\nfunction start( {")
        got = self.check(1, routes_part(), {"s1": broken})  # the file didn't parse before this part either
        self.assertEqual(got["reasons"], [], got)
        self.assertEqual(got["parse"][0]["skipped"], "the file didn't parse before this piece's part either")

    def test_the_jsonc_reader_keeps_strings(self):
        text = '{\n  // c\n  "a": "x // not a comment, /* nor this */",\n  "b": [1, 2,],  // tail\n  "c": "q\\"",\n}'
        self.assertEqual(json.loads(G._strip_jsonc(text)),
                         {"a": "x // not a comment, /* nor this */", "b": [1, 2], "c": 'q"'})
        self.assertEqual(G._strip_jsonc('{"a": 1, /* x */ }'), '{"a": 1  }')


class NamesPythonTests(unittest.TestCase):
    """K1: a files step whose own words ask for Python keeps its tests even when its candidates write no .py."""

    def test_what_names_python(self):
        for words in ("Write a Python script that reads the CSV", "Create tasktimer/__init__.py and start.py",
                      "Using the utilities from `data_utils.py`, implement add", "Target Python 3.12",
                      "Use python-docx to write the report", "Use Python‑pptx for the slides",
                      "Expose it as `from tasktimer import utils`", 'guard it with if __name__ == "__main__":',
                      "Write it in python3.", "Bash (or Python) benchmark script"):
            self.assertTrue(G.names_python(words), words)
        for words in ("Write src/index.js with the Bolt app", "Create a Lua module `csv.lua`",
                      "Write the `cmd_add` module",  # a module by the word alone: Lua, Go and JS say so too
                      "blender -b scene.blend --python-expr \"import bpy\"", "Serve it with `python -m http.server`",
                      "Run /usr/bin/python3 there", "An IPython notebook (.ipynb)", "See python.org", ""):
            self.assertFalse(G.names_python(words), words)

    def test_no_python_reads_the_steps_words(self):
        js = [S1_OWN + handoff("package.json"), S3_BLOCK_KIT]
        self.assertTrue(G.no_python(js, "files"))
        self.assertTrue(G.no_python(js, "files", "Set up\nCreate package.json and a .gitignore."))
        self.assertFalse(G.no_python(js, "files", "Package\nCreate tasktimer/__init__.py and tasktimer/start.py."))
        self.assertFalse(G.no_python(js, "files", "Data\nWrite a Python module that loads the JSON."))
        self.assertFalse(G.no_python([S3_BLOCK_KIT, J2_JSON], "files", "Set up\nCreate package.json."))  # deploy.py


def own(*pairs):
    """FileParts as the validator gives them, all whole files: (path, body) pairs."""
    return [type("FP", (), {"path": p, "part": False, "body": b})() for p, b in pairs]


# A Slack app whose first step's own words list the placeholders (coding-0012-01 rounds 1 and 2 in the smoke).
OPLAN = {"title": "Poll bot", "kind": "code", "summary": "A Slack poll bot. " + MARK, "steps": [
    {"id": "s1", "title": "Initialize the project", "kind": "code", "depends_on": [],
     "instructions": "Create package.json, README.md (placeholder), vercel.json (placeholder), .env.example and "
                     "src/index.js. List the dependencies in requirements.txt."},
    {"id": "s2", "title": "Implement src/index.js", "kind": "code", "depends_on": ["s1"],
     "instructions": "Write the Bolt app. Read the tokens as listed in .env.example; add slack_bolt to "
                     "requirements.txt."},
    {"id": "s3", "title": "Vercel config", "kind": "code", "depends_on": ["s1"],
     "instructions": "Write vercel.json for the serverless function."},
    {"id": "s4", "title": "Add environment variables example & README", "kind": "code", "depends_on": ["s1"],
     "instructions": "Update README.md with the setup steps."}]}
LONG_README = ("# Poll bot\n\n> Placeholder: the full README will be expanded in later steps.\n\n## Overview\n\n"
               "A Slack poll bot. " + MARK.lstrip("# ") + "\n\n## Setup\n\nTo come.\n\n## Usage\n\nTo come.")


class OwnStubTests(unittest.TestCase):
    """code-3: a step's own files need stronger evidence to be a stub of another step's; a longer placeholder that
    says so at its top is a stub."""

    def test_a_steps_own_placeholders_pass_unless_a_later_title_or_its_own_word_names_the_owner(self):
        files = own(("README.md", "# Placeholder README\n\nThis file will be populated in a later step."),
                    ("vercel.json", '{\n  // Placeholder; the configuration will be added in a later step.\n}'),
                    ("src/index.js", "// Placeholder for the entry point.\n// Implementation will be added later."),
                    (".env.example", "SLACK_BOT_TOKEN=xoxb-placeholder\nSLACK_SIGNING_SECRET=placeholder"),
                    ("requirements.txt", "requests  # TODO pin"))
        self.assertEqual(G.stubs_for_others(OPLAN, 0, files), [("src/index.js", "s2")])  # s2's title names it
        named = own(("vercel.json", '{\n  // Placeholder - will be replaced in step s3.\n}'))
        self.assertEqual(G.stubs_for_others(OPLAN, 0, named), [("vercel.json", "s3")])  # its own word names s3
        self.assertEqual(G.stubs_for_others(OPLAN, 0, own(("README.md", LONG_README))), [])  # asked as a placeholder
        titled = dict(OPLAN, steps=OPLAN["steps"][:3] + [dict(OPLAN["steps"][3], title="Write README.md")])
        self.assertEqual(G.stubs_for_others(titled, 0, own(("README.md", LONG_README))), [("README.md", "s4")])

    def test_files_the_step_wasnt_asked_for_keep_the_weaker_signals(self):
        plan = dict(OPLAN, steps=[dict(OPLAN["steps"][0], instructions="Create package.json.")] + OPLAN["steps"][1:])
        files = own((".env.example", "SLACK_BOT_TOKEN=xoxb-placeholder"), ("requirements.txt", "requests  # TODO pin"),
                    ("README.md", LONG_README))
        self.assertEqual(G.stubs_for_others(plan, 0, files),
                         [(".env.example", "s2"), ("requirements.txt", "s2"), ("README.md", "s4")])
        real = LONG_README.replace("> Placeholder: the full README will be expanded in later steps.",
                                   "A bot for polls.") + "\n\nMore in later steps."
        self.assertEqual(G.stubs_for_others(plan, 0, own(("README.md", real))), [])  # not a placeholder at its top

    def test_a_packages_own_init_with_a_docstring_isnt_a_stub(self):
        plan = {"title": "Timer", "kind": "code", "summary": MARK, "steps": [
            {"id": "s1", "title": "Package", "kind": "code", "depends_on": [],
             "instructions": "Create tasktimer/__init__.py and tasktimer/utils.py with read_tasks()."},
            {"id": "s2", "title": "start", "kind": "code", "depends_on": ["s1"],
             "instructions": "Implement tasktimer/start.py."}]}
        init = own(("tasktimer/__init__.py", '"""Task timer. The sub-commands are implemented in later steps."""'))
        self.assertEqual(G.stubs_for_others(plan, 0, init), [])
        unasked = dict(plan, steps=[dict(plan["steps"][0], instructions="Write tasktimer/utils.py.")] +
                       plan["steps"][1:])
        self.assertEqual(G.stubs_for_others(unasked, 0, init), [("tasktimer/__init__.py", None)])


# A contacts tool whose add command (s2) names its module only in words and backticks.
KPLAN = {"title": "Contacts", "kind": "code", "summary": "A contacts list. " + MARK, "steps": [
    {"id": "s1", "title": "Store", "kind": "code", "depends_on": [],
     "instructions": "Write contacts_store.py with load() and save(contacts). Install python-docx for the export."},
    {"id": "s2", "title": "Add command", "kind": "code", "depends_on": ["s1"],
     "instructions": "Write the `cmd_add` module with cmd_add(args)."},
    {"id": "s3", "title": "Main", "kind": "code", "depends_on": ["s2"],
     "instructions": "Write contactmgr.py with main(), which calls cmd_add, and export(), which writes report.docx "
                     "with docx."}]}
K3_MAIN = files_piece("contactmgr.py", MARK + "\nimport docx\nfrom cmd_add import cmd_add\n\n\ndef main():\n"
                      "    cmd_add([])\n\n\ndef export():\n    return docx.Document()\n",
                      "contactmgr.py: main(), export()", "cmd_add from s2")


def missing(module):
    err = f"ModuleNotFoundError: No module named '{module}'"
    return {"code": "x", "check": {"stub": {"error": err}, "errors": [err], "passed": [False]}}


class ThirdPartyTests(GateCase):
    """code-4, K3 and K12: a module a dropped earlier code step names is the project's; one inside a library's name
    ("python-docx") isn't; import_fault reads a kept piece's import run."""

    def test_a_dropped_earlier_steps_module_is_never_third_party(self):
        self.assertIsNone(G.tests_fault(missing("cmd_add"), KPLAN, 2, [K3_MAIN], dropped=["s2"]))  # s2 names `cmd_add`
        self.assertEqual(G.tests_fault(missing("docx"), KPLAN, 2, [K3_MAIN], dropped=["s1", "s2"]),
                         "third_party")  # python-docx names no docx module
        self.assertTrue(G.outside_project("docx", KPLAN, 2, dropped=["s1", "s2"]))
        self.assertFalse(G.outside_project("cmd_add", KPLAN, 2, dropped=["s2"]))
        self.assertFalse(G.outside_project("json", KPLAN, 2))
        self.assertTrue(G.outside_project("cmd_add", KPLAN, 1, dropped=["s2"]))  # s2's own words: a library, maybe
        named = dict(KPLAN, steps=[dict(KPLAN["steps"][0], instructions="Use the `docx` package.")] +
                     KPLAN["steps"][1:])
        self.assertFalse(G.outside_project("docx", named, 2, dropped=["s1"]))

    def test_a_kept_piece_whose_import_misses_a_package(self):
        piece = files_piece("report.py", MARK + "\nimport wm_not_installed_docx\n\n\ndef cmd_add(name, email):\n"
                            "    return wm_not_installed_docx.Document()\n", "report.py: cmd_add(name, email)")
        got = self.check(1, piece, {"s1": C1}, plan=CPLAN, mode="files")
        self.assertEqual((got["ok"], got["run"]["error"]),
                         (True, "ModuleNotFoundError: No module named 'wm_not_installed_docx'"), got)
        self.assertEqual(got["run"]["missing"], {"module": "wm_not_installed_docx", "project": False, "piece": True})
        self.assertEqual(G.import_fault(got, CPLAN, 1, [piece]), "third_party")
        old = dict(got, run={k: v for k, v in got["run"].items() if k != "missing"})  # a gate from before "missing"
        self.assertEqual(G.import_fault(old, CPLAN, 1, [piece]), "third_party")
        self.assertIsNone(G.import_fault(old, CPLAN, 1, []))  # nothing says the piece imports it
        named = dict(CPLAN, steps=[dict(CPLAN["steps"][0], instructions=CPLAN["steps"][0]["instructions"] +
                                        " Keep `wm_not_installed_docx` in mind.")] + CPLAN["steps"][1:])
        self.assertIsNone(G.import_fault(got, named, 1, [piece], dropped=["s1"]))
        self.assertEqual(G.import_fault(got, named, 1, [piece]), "third_party")  # s1 kept: its piece didn't write it
        for change in ({"piece": False}, {"project": True}):  # an earlier step's import; one of the project's own
            seen = dict(got, run=dict(got["run"], missing=dict(got["run"]["missing"], **change)))
            self.assertIsNone(G.import_fault(seen, CPLAN, 1, [piece]), change)
        self.assertIsNone(G.import_fault(self.check(1, C2, {"s1": C1}, plan=CPLAN, mode="files"), CPLAN, 1, [C2]))
        self.assertIsNone(G.import_fault(None, CPLAN, 1, [piece]))

    def test_a_python_script_piece_whose_project_misses_a_package(self):
        got = self.check(1, P2_DOCX, {"s1": P1})
        self.assertEqual((got["ok"], got["run"]["missing"]),
                         (True, {"module": "wm_not_installed_docx", "project": False, "piece": True}), got)
        self.assertEqual(G.import_fault(got, PLAN, 1, [P2_DOCX]), "third_party")
        got = self.check(1, P2, {"s1": P1.replace("import re\n", "import re\nimport wm_not_installed_docx\n")})
        self.assertEqual(got["run"]["missing"]["piece"], False)  # an earlier step's import: not this piece's
        self.assertIsNone(G.import_fault(got, PLAN, 1, [P2]))


# ---------------------------------------------------------------- after the third check of the smoke (Nov 4)

try:
    import yaml  # noqa: F401
    YAML = True
except ImportError:
    YAML = False

# YAML files that real tools read with tags of their own (r2-code-0): PyYAML's constructors refuse every one of them.
TAGGED_YAML = {
    "template.yaml": MARK + "\nAWSTemplateFormatVersion: '2010-09-09'\nTransform: AWS::Serverless-2016-10-31\n"
                     "Resources:\n  Fn:\n    Type: AWS::Serverless::Function\n    Properties:\n"
                     "      Role: !GetAtt Role.Arn\n      Environment:\n        Variables:\n"
                     "          TABLE: !Ref Table\n          URL: !Sub 'https://${Api}.example.org'\n"
                     "      Tags: !If [IsProd, {stage: prod}, !Ref AWS::NoValue]\n",
    "configuration.yaml": MARK + "\nhomeassistant:\n  name: Home\nautomation: !include automations.yaml\n"
                          "http:\n  api_password: !secret http_password\n",
    "playbook.yml": MARK + "\n- hosts: all\n  vars:\n    db_password: !vault |\n      $ANSIBLE_VAULT;1.1;AES256\n"
                    "      62313365396662343061\n  tasks:\n    - debug: msg=hi\n",
    "mkdocs.yml": MARK + "\nsite_name: Docs\nmarkdown_extensions:\n  - pymdownx.emoji:\n"
                  "      emoji_index: !!python/name:material.extensions.emoji.twemoji\n",
    ".gitlab-ci.yml": MARK + "\n.setup:\n  script:\n    - echo setup\ntest:\n  script:\n"
                      "    - !reference [.setup, script]\n    - echo test\n",
    "compose.yml": MARK + "\nx-base: &base\n  restart: always\nservices:\n  web:\n    <<: *base\n    image: web\n"
                   "x-base: &base\n  restart: never\n  worker:\n    <<: *base\n",  # an anchor set again: YAML allows it
}


@unittest.skipUnless(YAML, "PyYAML isn't installed")
class TaggedYamlTests(unittest.TestCase):
    """r2-code-0: YAML is composed, never constructed, so the tags real files use pass, and so does an anchor set
    again, while broken syntax, a tab indent and an undefined alias still fail with their line."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="work-", dir=_tmp)
        self.gate = G.CodeGate(None, None, work=self.work)  # a YAML parse never asks Chimera nor runs anything

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def test_tags_pass(self):
        for path, body in TAGGED_YAML.items():
            self.assertEqual(G._parse_data("YAML", body), (None, 0), path)
            self.assertEqual(self.gate.parse_file(path, body),
                             {"path": path, "kind": "YAML", "ok": True, "error": None, "line": 0}, path)
        self.assertEqual(G._parse_data("YAML", MARK + "\nwhen: 2024-13-45\ncount: !!int many\n"), (None, 0))

    def test_broken_yaml_still_fails_with_its_line(self):
        for body, error, line in (
                (MARK + "\nlog_level: [info\nhosts: 2", "while parsing a flow sequence expected ',' or ']', but got "
                                                       "':'", 3),
                (MARK + "\na:\n\tb: 1", "while scanning for the next token found character '\\t' that cannot start "
                                        "any token", 3),
                (MARK + "\nbase: &b {a: 1}\nother: *nothere", "found undefined alias 'nothere'", 3),
                (MARK + "\nrole: !GetAtt Role.Arn\n  name: [x", "mapping values are not allowed here", 3)):
            self.assertEqual(G._parse_data("YAML", body), (error, line), body)
        got = self.gate.parse_file("template.yaml", TAGGED_YAML["template.yaml"] + "Outputs: [Fn\n")
        self.assertEqual((got["ok"], got["line"]), (False, 15), got)


class TaggedYamlPieceTests(GateCase):
    """r2-code-0 through the gate: a files piece with a CloudFormation template passes its parse check."""

    @unittest.skipUnless(YAML, "PyYAML isn't installed")
    def test_a_piece_with_a_tagged_template_passes(self):
        extra = "\n" + block("template.yaml", "yaml", TAGGED_YAML["template.yaml"].rstrip("\n"))
        got = super().check(0, config_piece(yaml_body=TAGGED_YAML["configuration.yaml"].rstrip("\n"), extra=extra),
                            plan=DPLAN, mode="files")
        self.assertEqual((got["ok"], got["reasons"]), (True, []), got)
        kinds = {p["path"]: p.get("ok") for p in got["parse"]}
        self.assertEqual((kinds["template.yaml"], kinds["settings.yml"]), (True, True), got["parse"])


# A task timer whose package step writes its own real modules (r2-code-2). s3 and s4 name no file of s1's.
UPLAN = {"title": "Task timer", "kind": "code", "summary": "A command-line task timer. " + MARK, "steps": [
    {"id": "s1", "title": "Package", "kind": "code", "depends_on": [],
     "instructions": "Create tasktimer/__init__.py, tasktimer/utils.py with read_tasks() and write_tasks(tasks), "
                     "config.py with the defaults, and README.md."},
    {"id": "s2", "title": "start", "kind": "code", "depends_on": ["s1"],
     "instructions": "Implement tasktimer/start.py."},
    {"id": "s3", "title": "Settings", "kind": "code", "depends_on": ["s1"], "instructions": "Tune the defaults."},
    {"id": "s4", "title": "Report", "kind": "code", "depends_on": ["s1"],
     "instructions": "Write the report formatter in tasktimer/report.py."}]}
UTILS_49 = ('"""Helpers the task timer\'s commands share.\n\nTODO: the report formatter is added in step s4.\n"""\n' +
            MARK + "\nimport json\nimport os\nimport time\n\nDATA_FILE = 'tasks.json'\n\n\n"
            "def read_tasks(path=DATA_FILE):\n    if not os.path.exists(path):\n        return []\n"
            "    with open(path) as f:\n        return json.load(f)\n\n\n"
            "def write_tasks(tasks, path=DATA_FILE):\n    with open(path, 'w') as f:\n"
            "        json.dump(tasks, f, indent=2)\n\n\n"
            "def find_task(tasks, name):\n    for t in tasks:\n        if t['name'] == name:\n            return t\n"
            "    return None\n\n\n"
            "def running(tasks):\n    return [t for t in tasks if t.get('started') and not t.get('stopped')]\n\n\n"
            "def start_task(tasks, name, now=None):\n    task = find_task(tasks, name)\n    if task is None:\n"
            "        task = {'name': name, 'spans': []}\n        tasks.append(task)\n"
            "    task['started'] = now if now is not None else time.time()\n    task['stopped'] = None\n"
            "    return task\n\n\n"
            "def stop_task(tasks, name, now=None):\n    task = find_task(tasks, name)\n"
            "    if task is None or not task.get('started'):\n        return None\n"
            "    end = now if now is not None else time.time()\n    task['spans'].append([task['started'], end])\n"
            "    task['stopped'] = end\n    return task\n\n\n"
            "def total_seconds(task):\n    return sum(b - a for a, b in task.get('spans', []))\n\n\n"
            "def format_duration(seconds):\n    hours, rest = divmod(int(seconds), 3600)\n"
            "    minutes, secs = divmod(rest, 60)\n    if hours:\n        return f'{hours}h {minutes:02d}m'\n"
            "    return f'{minutes}m {secs:02d}s'\n\n\n"
            "def names(tasks):\n    return sorted(t['name'] for t in tasks)\n")
CONFIG_31 = "# placeholder defaults, replaced by step s3\n" + MARK + "\n" + \
    "".join(f"OPTION_{k} = {k * 5}\n" for k in range(29))
REPORT_STUB = ('"""Placeholder: the report formatter is written in step s4."""\n' + MARK + "\nimport json\n\n\n"
               "def format_report(tasks):\n    raise NotImplementedError\n\n\nclass Report:\n"
               "    \"\"\"The report's lines.\"\"\"\n\n    def render(self):\n        ...\n")
README_TODO = ("# Task timer\n\nTODO: the usage section is added in step s4.\n\nTimes the tasks you start and stop. " +
               MARK.lstrip("# ") + "\n\n## Install\n\nCopy the tasktimer folder next to your scripts.")


class LongerPlaceholderTests(unittest.TestCase):
    """r2-code-2: a file over 3 lines counts as another step's stub only when it holds nothing but its note: a doc
    page whose note says placeholder or stub, or Python of nothing but stubs."""

    def test_a_steps_own_real_files_with_a_note_at_their_top_pass(self):
        self.assertEqual(len([l for l in UTILS_49.split("\n") if l.strip()]), 49)
        self.assertEqual(len([l for l in CONFIG_31.split("\n") if l.strip()]), 31)
        for path, body in (("tasktimer/utils.py", UTILS_49), ("config.py", CONFIG_31), ("README.md", README_TODO)):
            self.assertEqual(G.stubs_for_others(UPLAN, 0, own((path, body))), [], path)
        unasked = dict(UPLAN, steps=[dict(UPLAN["steps"][0], instructions="Create tasktimer/__init__.py.")] +
                       UPLAN["steps"][1:])
        for path, body in (("tasktimer/utils.py", UTILS_49), ("config.py", CONFIG_31), ("README.md", README_TODO)):
            self.assertEqual(G.stubs_for_others(unasked, 0, own((path, body))), [], path)  # not stubs at all
        app = ("// Placeholder: step s2 replaces this with the full app.\nconst express = require('express');\n"
               "const app = express();\napp.get('/', (q, r) => r.send('hi'));\nmodule.exports = app;")
        pins = "# Placeholder: s2 adds slack_bolt.\nrequests==2.31.0\nflask==3.0.0\ngunicorn==21.2.0"
        for path, body in (("src/app.js", app), ("requirements.txt", pins)):  # real code and pins, whatever they say
            self.assertEqual(G.stubs_for_others(unasked, 0, own((path, body))), [], path)
        self.assertEqual(G.stubs_for_others(unasked, 0, own(("docs/README.txt", LONG_README.replace(
            "later steps", "step s4")))), [("docs/README.txt", "s4")])  # a page

    def test_a_longer_placeholder_still_fails(self):
        self.assertEqual(G.stubs_for_others(UPLAN, 0, own(("tasktimer/report.py", REPORT_STUB))),
                         [("tasktimer/report.py", "s4")])
        self.assertEqual(G.stubs_for_others(UPLAN, 0, own(("tasktimer/utils.py", REPORT_STUB))),
                         [("tasktimer/utils.py", "s4")])  # its own file, but nothing in it and s4's id
        plan = dict(OPLAN, steps=[dict(OPLAN["steps"][0], instructions="Create package.json.")] + OPLAN["steps"][1:])
        self.assertEqual(G.stubs_for_others(plan, 0, own(("README.md", LONG_README))), [("README.md", "s4")])

    def test_what_is_nothing_but_stubs(self):
        for code in ('"""Placeholder."""\ndef a():\n    pass\n\n\nasync def b(x):\n    ...\n',
                     '"""Placeholder."""\nimport os\n\n\nclass K:\n    """Doc."""\n\n    def m(self):\n'
                     '        raise NotImplementedError("later")\n',
                     '"""Placeholder: s3 writes this."""\n# more to come\n'):
            self.assertTrue(G._stub_python(code), code)
        for code in ('"""Placeholder."""\nimport os\nfrom .a import b\n',  # a package's re-exports
                     '"""Placeholder."""\nLIMIT = 3\n\n\ndef a():\n    pass\n',
                     '"""Placeholder."""\ndef a():\n    return 1\n',
                     '"""Placeholder."""\nclass K:\n    N = 2\n',
                     '"""Placeholder."""\nraise NotImplementedError\n',
                     "def a(:\n"):
            self.assertFalse(G._stub_python(code), code)


class PythonProjectTests(unittest.TestCase):
    """K11 (r2-code-3): a step of a Python project keeps its tests even when its words never say Python and its
    candidates write no .py file."""

    def test_a_python_project_has_python_to_test(self):
        docs = [block("docs/find.md", "markdown", "# find\n\n" + MARK.lstrip("# ")) + handoff("docs/find.md")]
        words = "Find\nImplement the `find` sub-command."
        self.assertTrue(G.no_python(docs, "files", words))
        self.assertFalse(G.no_python(docs, "files", words, python_project=True))
        self.assertTrue(G.no_python(docs, "files", words, python_project=False))
        self.assertFalse(G.no_python(docs, "python-script", words, python_project=True))


# A contacts tool whose store step names its module nowhere (r2-code-1), and a report whose writing step only
# mentions the library it will be read with (r2-code-4).
VPLAN = {"title": "Contacts", "kind": "code", "summary": "A contacts list. " + MARK, "steps": [
    {"id": "s1", "title": "Store", "kind": "code", "depends_on": [],
     "instructions": "Write the store, with load() and save(contacts)."},
    {"id": "s2", "title": "Add command", "kind": "code", "depends_on": ["s1"],
     "instructions": "Write adder.py with cmd_add(name, email), using load and save from s1."}]}
V1 = files_piece("contacts_db.py", MARK + "\nimport json\nimport os\n\n\ndef load():\n"
                 "    if not os.path.exists('c.json'):\n        return []\n    with open('c.json') as f:\n"
                 "        return json.load(f)\n\n\ndef save(contacts):\n    with open('c.json', 'w') as f:\n"
                 "        json.dump(contacts, f)\n", "contacts_db.py: load(), save(contacts)")
V2 = files_piece("adder.py", MARK + "\nfrom contacts_db import load, save\n\n\ndef cmd_add(name, email):\n"
                 "    contacts = load()\n    contacts.append({'name': name, 'email': email})\n    save(contacts)\n",
                 "adder.py: cmd_add(name, email)", "load, save from s1")
WPLAN = {"title": "Sales sheet", "kind": "writing", "summary": "Monthly sales, and an export. " + MARK, "steps": [
    {"id": "s1", "title": "Sales notes", "kind": "writing", "depends_on": [],
     "instructions": "Write the month's sales notes. Keep the data so that `openpyxl` can read it later."},
    {"id": "s2", "title": "Export", "kind": "code", "depends_on": ["s1"],
     "instructions": "Write export.py with export(rows), which writes rows.xlsx."}]}


class DroppedAndWrittenTests(GateCase):
    """K12: only a dropped earlier code step's words exempt a bare module name (r2-code-4), and the texts the
    caller adds (a variant's input pieces) count as the project's (r2-code-1)."""

    def test_only_a_dropped_earlier_code_step_exempts_a_bare_name(self):
        self.assertEqual(G.tests_fault(missing("cmd_add"), KPLAN, 2, [K3_MAIN]), "third_party")  # s2 kept
        self.assertIsNone(G.tests_fault(missing("cmd_add"), KPLAN, 2, [K3_MAIN], dropped=("s2",)))
        self.assertEqual(G.tests_fault(missing("cmd_add"), KPLAN, 2, [K3_MAIN], dropped=("s1",)), "third_party")
        self.assertTrue(G.outside_project("openpyxl", WPLAN, 1))  # a writing step's words write no module
        self.assertFalse(G.outside_project("export", WPLAN, 1))  # a file a step names stays the project's
        self.assertFalse(G.outside_project("cmd_add", KPLAN, 2, dropped=["s2"]))
        self.assertTrue(G.outside_project("cmd_add", KPLAN, 2, dropped=["s3"]))  # its own id: not an earlier step

    def test_a_variant_checked_alone_imports_its_dependencys_module(self):
        got = self.check(1, V2, {}, plan=VPLAN, mode="files")  # a variant is gated alone
        self.assertEqual((got["ok"], got["run"]["missing"]),
                         (True, {"module": "contacts_db", "project": False, "piece": True}), got)
        self.assertEqual(G.import_fault(got, VPLAN, 1, [V2]), "third_party")  # no step names contacts_db
        self.assertIsNone(G.import_fault(got, VPLAN, 1, [V2], written=[V1]))  # the piece its request carried
        self.assertIsNone(G.import_fault(got, VPLAN, 1, [V2], dropped=(), written=[V1, None, ""]))
        self.assertEqual(G.import_fault(got, VPLAN, 1, [V2], written=[C1]), "third_party")  # another module

    def test_what_ran_on_a_piece(self):
        """K14: "tests" and "run" in piece_check's result say whether anything of the piece ran."""
        got = self.check(0, config_piece(), plan=DPLAN, mode="files")
        self.assertEqual((got["ok"], got["tests"], got["run"]), (True, None, None), got)  # no .py: only parsed
        got = self.check(1, P2, {"s1": P1})
        self.assertEqual((got["ok"], got["tests"], got["run"]["exit"]), (True, None, 0), got)  # the import ran
        got = self.check(1, P2, {"s1": P1}, tests={"code": TESTS2, "valid": True})
        self.assertEqual((got["ok"], got["tests"]["passed"], got["run"]), (True, True, None), got)  # the tests ran


@unittest.skipUnless(SANDBOX and NODE, "needs sandbox-exec and node")
class RunToolTests(WorkCase):
    def test_another_program_runs_in_the_same_sandbox(self):
        r = P.run_tool({"a.js": "const a = 1;\n"}, NODE, ["--check", "a.js"], work=self.work)
        self.assertEqual((r["exit"], r["sandboxed"], r.get("error")), (0, True, None), r)
        r = P.run_tool({"a.js": "x"}, NODE, ["-e", "require('child_process').execSync('/bin/echo hi')"],
                       work=self.work)
        self.assertNotEqual(r["exit"], 0, r)  # the profile lets node start and nothing else
        self.assertIn("EPERM", r["output"])
        self.assertEqual(os.listdir(self.work), [])
        self.assertEqual(P.run_tool({}, os.path.join(self.work, "nothing"), [])["error"],
                         f"no such program: {os.path.join(self.work, 'nothing')!r}")
        self.assertTrue(P.tool_version(NODE).startswith("v"))


# ---------------------------------------------------------------- after the second smoke (Nov 4)

# A contacts CLI whose s1 put its module in src/ while the entry imports it from the root (smoke2's X80, X32).
LPLAN = {"title": "Contacts", "kind": "code", "summary": "A contacts list on the command line. " + MARK, "steps": [
    {"id": "s1", "title": "Find command", "kind": "code", "depends_on": [],
     "instructions": "Write the find sub-command, cmd_find(query), which returns the matching names."},
    {"id": "s2", "title": "Main", "kind": "code", "depends_on": ["s1"],
     "instructions": "Write contactmgr.py with main(), which prints cmd_find('a')."}]}
L1 = files_piece("src/find_cmd.py", MARK + "\ndef cmd_find(query):\n    return [n for n in ('ann', 'bo') if query in n]"
                 "\n", "src/find_cmd.py: cmd_find(query)")


def contactmgr(imports):
    return files_piece("contactmgr.py", MARK + "\n" + imports + "\n\n\ndef main():\n    print(cmd_find('a'))\n\n\n"
                       "if __name__ == '__main__':\n    main()\n", "contactmgr.py: main()", "cmd_find from s1")


L2_BARE = contactmgr("from find_cmd import cmd_find")
L2_PKG = contactmgr("from src.find_cmd import cmd_find")
# A package whose middle step imports its sibling by bare name inside src/: no gate of its own can see it.
BPLAN = {"title": "Totals", "kind": "code", "summary": "Totals. " + MARK, "steps": [
    {"id": "s1", "title": "Numbers", "kind": "code", "depends_on": [], "instructions": "Write src/wm_nums.py."},
    {"id": "s2", "title": "Core", "kind": "code", "depends_on": ["s1"], "instructions": "Write src/wm_core.py."},
    {"id": "s3", "title": "Main", "kind": "code", "depends_on": ["s2"], "instructions": "Write main.py."}]}
B1 = files_piece("src/wm_nums.py", MARK + "\nNUMS = [1, 2, 3]\n", "src/wm_nums.py: NUMS")
B2 = files_piece("src/wm_core.py", MARK + "\nfrom wm_nums import NUMS\n\n\ndef total():\n    return sum(NUMS)\n",
                 "src/wm_core.py: total()", "NUMS from s1")
B3 = files_piece("main.py", MARK + "\nfrom src.wm_core import total\n\n\ndef main():\n    print(total())\n\n\n"
                 "if __name__ == '__main__':\n    main()\n", "main.py: main()", "total from s2")
# A src-layout package two folders deep whose entry imports its own package inside main(): run as `python3 -m
# wm_notes.cli` from src/ (or installed by its pyproject.toml), the launcher's `python3 src/wm_notes/cli.py` can't see
# it (the integration check's case; smoke2's tasktimer/tasktimer/ is the runs' one such layout).
NPLAN = {"title": "Notes", "kind": "code", "summary": "A notes package. " + MARK, "steps": [
    {"id": "s1", "title": "Package", "kind": "code", "depends_on": [],
     "instructions": "Write the wm_notes package in src/ with store.py's load()."},
    {"id": "s2", "title": "CLI", "kind": "code", "depends_on": ["s1"],
     "instructions": "Write src/wm_notes/cli.py with main(), which prints load()."}]}
NOTES_PYPROJECT = '[project]\nname = "wm_notes"\nversion = "0.1.0"\n\n[tool.setuptools.packages.find]\nwhere = ["src"]'


def notes_package(config):
    return ((block("pyproject.toml", "toml", NOTES_PYPROJECT) + "\n" if config else "") +
            block("src/wm_notes/__init__.py", "python", MARK) + "\n" +
            block("src/wm_notes/store.py", "python", MARK + "\ndef load():\n    return ['a']") +
            handoff("src/wm_notes/store.py: load()" + ("; pyproject.toml" if config else "")))


NOTES_CLI = (block("src/wm_notes/cli.py", "python", MARK + "\n\n\ndef main():\n    from wm_notes.store import load\n"
            "    print(load())\n\n\nif __name__ == '__main__':\n    main()") +
      handoff("src/wm_notes/cli.py: main()", "s1: load"))


class LayoutGateTests(GateCase):
    """K8: the files gate's layout_import stage, a variant's reading through project=, and the plan check's
    entry_layout backstop."""

    def test_a_root_entry_importing_a_src_module_by_bare_name_fails(self):
        got = self.check(1, L2_BARE, {"s1": L1}, plan=LPLAN, mode="files")
        self.assertEqual((got["ok"], got["reasons"], got["stage"], got["crash"], got["run"]),
                         (False, ["layout_import"], "layout_import", None, None), got)  # no repair, nothing run
        self.assertEqual(got["seams"], [])  # Go's join resolves it by its suffix
        self.assertEqual(got["tell"], ["contactmgr.py imports find_cmd (`from find_cmd import cmd_find`), but from "
                                       "the project's root Python finds no find_cmd: the project has it only at "
                                       "src/find_cmd.py (from the root: src.find_cmd)"])
        self.assertEqual([f["module"] for f in got["layout"]["findings"]], ["find_cmd"])
        ok = self.check(1, L2_PKG, {"s1": L1}, plan=LPLAN, mode="files")
        self.assertEqual((ok["ok"], ok["layout"]["checked"], ok["layout"]["findings"]), (True, ["contactmgr.py"], []))
        self.assertNotIn("layout", self.check(1, P2, {"s1": P1}))  # python-script: one file

    def test_a_variant_is_read_against_the_pieces_it_was_written_for(self):
        alone = self.check(1, L2_BARE, {}, plan=LPLAN, mode="files")  # checked alone, its dependency isn't there
        self.assertTrue(alone["ok"], alone)
        v = self.verdict(LPLAN, 1, L2_BARE, "files")
        got = self.gate.piece_check(LPLAN, 1, L2_BARE, v, {}, "files", project={"s1": L1})
        self.assertEqual((got["ok"], got["reasons"]), (False, ["layout_import"]), got)
        got = self.gate.piece_check(LPLAN, 1, L2_PKG, v, {}, "files", project={"s1": L1})
        self.assertTrue(got["ok"], got)
        unjoinable = {"s1": "File: src/find_cmd.py\n```python\nX = 1\n```\n"}  # no handoff: Chimera can't join it
        got = self.gate.piece_check(LPLAN, 1, L2_BARE, v, {}, "files", project=unjoinable)
        self.assertTrue(got["ok"], got)  # left out, as a failed step would be: nothing says where find_cmd is

    def test_the_plan_check_blames_the_file_whose_import_failed(self):
        got = self.gate.plan_check(LPLAN, {"s1": L1, "s2": L2_BARE}, LPLAN["summary"])
        self.assertEqual((got["ok"], got["reasons"], got["culprit"], got["entry"]["outcome"]),
                         (False, ["entry_layout"], "s2", "failed"), got)
        self.assertEqual(got["entry"]["layout"], {"file": "contactmgr.py", "line": 2, "module": "find_cmd",
                                                  "found_at": ["src/find_cmd.py"]})
        self.assertTrue(self.gate.plan_check(LPLAN, {"s1": L1, "s2": L2_PKG}, LPLAN["summary"])["ok"])
        for i, (text, earlier) in enumerate(((B1, {}), (B2, {"s1": B1}), (B3, {"s1": B1, "s2": B2}))):
            self.assertTrue(self.check(i, text, earlier, plan=BPLAN, mode="files")["ok"])  # each passes its gate
        got = self.gate.plan_check(BPLAN, {"s1": B1, "s2": B2, "s3": B3}, BPLAN["summary"])
        self.assertEqual((got["ok"], got["reasons"], got["culprit"], got["entry"]["layout"]["file"]),
                         (False, ["entry_layout"], "s2", "src/wm_core.py"), got)
        gone = self.gate.plan_check(LPLAN, {"s2": L2_BARE}, LPLAN["summary"])  # a dropped step's module: no file
        self.assertEqual((gone["ok"], gone["entry"]["outcome"]), (True, "unsure"), gone)

    def test_a_package_two_folders_deep_stays_unsure(self):
        """The backstop reads where a real run of the entry could look (its folder and every folder above it, as the
        gate's layout reading does) and skips a project with a path config: a src-layout package's entry that imports
        its own package inside main() passes its gate and its plan check (unsure), with or without pyproject.toml.
        Before, the launcher's two folders alone counted, and the plan failed entry_layout on s2."""
        for config in (True, False):
            s1 = notes_package(config)
            for i, (text, earlier) in enumerate(((s1, {}), (NOTES_CLI, {"s1": s1}))):
                self.assertTrue(self.check(i, text, earlier, plan=NPLAN, mode="files")["ok"], (config, i))
            got = self.gate.plan_check(NPLAN, {"s1": s1, "s2": NOTES_CLI}, NPLAN["summary"])
            self.assertEqual((got["ok"], got["reasons"], got["entry"]["outcome"], got["entry"]["path"]),
                             (True, [], "unsure", "src/wm_notes/cli.py"), (config, got))
            self.assertIn("No module named 'wm_notes'", got["entry"]["error"])
        # The path config alone: the root entry's bare import of a src/ module is excused once one is there
        cfg = block("pyproject.toml", "toml", NOTES_PYPROJECT) + "\n" + L1
        self.assertTrue(self.gate.plan_check(LPLAN, {"s1": cfg, "s2": L2_BARE}, LPLAN["summary"])["ok"])


# A deploy step's shell script beside its Python (the parsers this computer has, through parse_file).
SHPLAN = {"title": "Deploy", "kind": "code", "summary": "A deploy script. " + MARK, "steps": [
    {"id": "s1", "title": "Deploy", "kind": "code", "depends_on": [],
     "instructions": "Write app.py with X, and deploy.sh, which echoes its first argument."}]}


def deploy_piece(script):
    return (block("app.py", "python", MARK + "\nX = 1") + "\n" + block("deploy.sh", "bash", "#!/bin/bash\n" + MARK +
            "\n" + script) + handoff("app.py: X; deploy.sh"))


class LocalParseGateTests(GateCase):
    """K4: a files piece's shell file is parsed by bash -n in the gate, and the result is in the gate's "parse",
    which lang_check.unchecked_code reads."""

    def test_a_broken_shell_file_fails_and_a_good_one_is_recorded(self):
        if not self.gate.local.has("Shell"):
            self.skipTest("no shell parser here")
        bad = deploy_piece('if [ -n "$1" ]; then\n  echo "$1"')
        got = self.check(0, bad, plan=SHPLAN, mode="files")
        self.assertEqual((got["ok"], got["reasons"], got["stage"]), (False, ["parse:sh"], "compile"), got)
        self.assertEqual([(p["path"], p["kind"], p["ok"]) for p in got["parse"]], [("deploy.sh", "Shell", False)])
        self.assertTrue(got["tell"][0].startswith("deploy.sh isn't valid Shell: line "), got["tell"])
        good = deploy_piece('if [ -n "$1" ]; then\n  echo "$1"\nfi')
        got = self.check(0, good, plan=SHPLAN, mode="files")
        self.assertEqual((got["ok"], [(p["path"], p["ok"]) for p in got["parse"]]), (True, [("deploy.sh", True)]))
        self.assertEqual(lang_check.unchecked_code(good, got["parse"]), [])
        self.assertEqual(lang_check.unchecked_code(good), [("deploy.sh", "Shell")])  # a record without "parse"


TTPLAN = {"title": "Task timer", "kind": "code", "summary": "A task timer. " + MARK, "steps": [
    {"id": "s1", "title": "Entry point", "kind": "code", "depends_on": [],
     "instructions": "Write `tasktimer/__main__.py` with cli(); layout: tasktimer/start.py, tasktimer/utils.py"},
    {"id": "s2", "title": "Utils", "kind": "code", "depends_on": [],
     "instructions": "Create `tasktimer/utils.py` with read_tasks()."},
    {"id": "s3", "title": "Start", "kind": "code", "depends_on": ["s2"],
     "instructions": "Implement `tasktimer/start.py` with main()."},
    {"id": "s4", "title": "Start sub-command", "kind": "code", "depends_on": ["s2"],
     "instructions": "Implement the start sub-command with main()."},
    {"id": "s5", "title": "Stop", "kind": "code", "depends_on": ["s3"],
     "instructions": "Implement `tasktimer/stop.py` with main(), after start."}]}
TT_MAIN = "ModuleNotFoundError: No module named 'tasktimer.__main__'"
TT_TESTS = MARK + "\nimport tasktimer.__main__ as e\nassert e.cli() == 0\nprint('tests ok')\n"
TT_OWN = files_piece("tasktimer/start.py", MARK + "\ndef main(argv=None):\n    return 0\n",
                     "tasktimer/start.py: main()")
TT_ROOT = files_piece("start.py", MARK + "\ndef main(argv=None):\n    return 0\n", "start.py: main()")


def tt_record(error=TT_MAIN, code=TT_TESTS, n=1):
    return {"code": code, "check": {"stub": {"error": error}, "passed": [False] * n, "errors": [error] * n}}


class TestsFaultClosureTests(unittest.TestCase):
    """K7: tests that reached only another step's module (smoke2's n-python-0001-01 s3, s4 and s6: s1's
    tasktimer.__main__, which those steps don't depend on) are tests_unreachable when the kept piece wrote its own file;
    a dependency's module, or a piece at another path than its words give, stays unconfirmed."""

    def test_a_module_only_a_step_outside_the_dependencies_names(self):
        self.assertEqual(G.tests_fault(tt_record(), TTPLAN, 2, [TT_OWN]), "tests_unreachable")
        self.assertEqual(G.tests_fault(tt_record(), TTPLAN, 2, [TT_OWN], kept=TT_OWN), "tests_unreachable")
        self.assertIsNone(G.tests_fault(tt_record(), TTPLAN, 2, [TT_OWN], kept=TT_ROOT))  # the kept one: elsewhere
        self.assertIsNone(G.tests_fault(tt_record(n=2), TTPLAN, 2, [TT_OWN, TT_ROOT]))  # without kept: every one
        self.assertIsNone(G.tests_fault(tt_record(), TTPLAN, 2, [TT_ROOT]))
        self.assertIsNone(G.tests_fault(tt_record(), TTPLAN, 3, [TT_OWN]))  # s4's words name no file of its own
        self.assertIsNone(G.tests_fault(tt_record(), TTPLAN, 0, [TT_OWN]))  # s1's own module

    def test_a_dependencys_module_stays_unconfirmed(self):
        utils = "ModuleNotFoundError: No module named 'tasktimer.utils'"
        rec = tt_record(utils, TT_TESTS.replace("tasktimer.__main__", "tasktimer.utils"))
        self.assertIsNone(G.tests_fault(rec, TTPLAN, 2, [TT_OWN]))  # s2 is s3's dependency
        stop = files_piece("tasktimer/stop.py", MARK + "\ndef main(argv=None):\n    return 0\n", "tasktimer/stop.py")
        self.assertIsNone(G.tests_fault(rec, TTPLAN, 4, [stop]))  # s5 -> s3 -> s2: through another step too
        self.assertEqual(G._closure(TTPLAN, 4), {1, 2})
        self.assertEqual(G._closure(TTPLAN, 0), set())

    def test_what_the_rewrite_said_is_kept_apart(self):
        """task's rewrite_tests keeps the new tests' errors under rewrite_errors; they are never read as the
        failures of the tests that failed the kept piece (those stay in "check")."""
        told = [{"from": "cand", "index": 0, "error": "AssertionError: Expected exit code 0, got 2"}]
        rec = dict(tt_record(), rewrite={"valid": False, "why": "no_candidate_passed",
                                         "check": {"valid": False, "errors": [told[0]["error"]]}},
                   rewrite_errors=told)
        self.assertEqual(G.tests_fault(rec, TTPLAN, 2, [TT_OWN], kept=TT_OWN), "tests_unreachable")
        self.assertEqual(G._record_errors(rec), (TT_MAIN, [TT_MAIN]))


P2_LAZY = piece("import sys\n\n\n" + TOP + "\n\ndef report(path):\n    import wm_not_installed_docx\n"
                "    from json import dumps\n    import yaml\n    try:\n        import wm_maybe_there\n"
                "    except ImportError:\n        wm_maybe_there = None\n"
                "    return wm_not_installed_docx.Document(path), dumps([])\n" + MAIN,
                "top_words(counts, n), main(), report(path)", "count_words from s1")


class LazyImportTests(GateCase):
    """K15: a third-party package imported only inside a function, unguarded, is what the import run never reaches
    (smoke2's X44: python-docx inside _load_docx_library); with no tests on the piece, import_fault calls it
    third_party."""

    def test_lazy_imports(self):
        code = (MARK + "\nimport os\n\n\ndef f():\n    import a.b\n    from c import d\n    from . import e\n"
                "    try:\n        import g\n    except (ValueError, ImportError):\n        import h\n"
                "    def inner():\n        import i\n    return lambda: 0\n\n\nclass K:\n    import j\n\n"
                "    def m(self):\n        import k\n        import k\n")
        self.assertEqual(G.lazy_imports(code), ["a.b", "c", "h", "i", "k"])
        self.assertEqual(G.lazy_imports("def f(:\n"), [])

    def test_the_gate_records_them_and_import_fault_reads_them(self):
        got = self.check(1, P2_LAZY, {"s1": P1})
        self.assertEqual((got["ok"], got["run"]["exit"]), (True, 0), got)  # the import run never reaches them
        want = ["wm_not_installed_docx"] + ([] if layout.interpreters("yaml", self.gate.own_paths) else ["yaml"])
        self.assertEqual(got["lazy_imports"], want)  # json is the standard library's, an installed one is there
        self.assertEqual(G.import_fault(got, PLAN, 1, [P2_LAZY]), "third_party")
        self.assertIsNone(G.import_fault(dict(got, tests={"passed": False, "error": "AssertionError"}), PLAN, 1,
                                         [P2_LAZY]))  # tests ran on it: their verdict, not this reading
        named = dict(PLAN, steps=[dict(PLAN["steps"][0], instructions=PLAN["steps"][0]["instructions"] +
                                       " Its report uses the `wm_not_installed_docx` module.")] + PLAN["steps"][1:])
        self.assertIsNone(G.import_fault(got, named, 1, [P2_LAZY], dropped=["s1"]))  # a dropped step may write it
        self.assertIsNone(G.import_fault(self.check(1, P2, {"s1": P1}), PLAN, 1, [P2]))
        self.assertEqual(self.check(1, P2, {"s1": P1})["lazy_imports"], [])
        self.assertIsNone(G.import_fault({"run": {"exit": 0}}, PLAN, 1, [P2_LAZY]))  # a gate from before the key

    def test_a_files_piece_and_the_projects_own_modules(self):
        lazy = files_piece("report.py", MARK + "\ndef cmd_add(name, email):\n    from contacts_store import load\n"
                           "    import wm_not_installed_xlsx\n    return load()\n", "report.py: cmd_add(name, email)")
        got = self.check(1, lazy, {"s1": C1}, plan=CPLAN, mode="files")
        self.assertEqual((got["ok"], got["lazy_imports"]), (True, ["contacts_store", "wm_not_installed_xlsx"]), got)
        self.assertEqual(G.import_fault(got, CPLAN, 1, [lazy], written=[C1]), "third_party")
        only_own = dict(got, lazy_imports=["contacts_store"])  # s1's module, which the round's earlier piece writes
        self.assertIsNone(G.import_fault(only_own, CPLAN, 1, [lazy], written=[C1]))
        self.assertIsNone(G.import_fault(only_own, CPLAN, 1, [lazy]))  # s1's words name contacts_store.py


if __name__ == "__main__":
    unittest.main()

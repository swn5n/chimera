"""datagen/layout.py: does each .py file a files piece writes find the project's own modules where the joined
project really puts them (the second smoke's audit, rc/files-layout and its skeptic's static-only variant)?

The shape of smoke2's X80 and X32 (a root-level entry importing src/find_cmd.py as find_cmd) is a finding, with a
tell line that says where the module is; the same import with the module at the root, a sibling import inside src/,
`from src import find_cmd`, a test file under tests/ importing a root module, and an import of a module no file of
the project holds (a dropped or left-out step's) aren't. A module named like the standard library's or an installed
package's never counts, nor a guarded import, one under TYPE_CHECKING, a file that changes sys.path, a project with a
packaging or pytest config or a PYTHONPATH line, or one whose later steps name such a config. `from pkg import mod`
counts when pkg is a folder here and mod only another pkg's, unless pkg's __init__.py binds it. TELL_FORMS is the
tell line's fixed wording, which hints.echoed_note learns.

Every file here is a hand-written test fixture (its code starts with the mark), never training data.
"""
import os
import re
import unittest

from tests import _paths  # noqa: F401
from contract import validate as cv
from datagen import layout as L
from datagen import pysandbox as P
from runner import mock_ollama

MARK = mock_ollama.MARK
PATHS = P.own_paths()


def piece(*blocks):
    """A files piece of (path, body) Python blocks and a handoff."""
    parts = [f"File: {path}\n```python\n{MARK}\n{body.rstrip()}\n```" for path, body in blocks]
    return "\n\n".join(parts) + "\n\n```handoff\nprovides: the files above\nuses: none\nassumed: none\n```"


def own(text):
    return cv.validate_piece(text, "files", reject_cut=False, max_tokens=None).files


def check(tree, *mine, later=""):
    """layout_findings on tree ({path: body}, the earlier pieces' files) plus this piece's blocks (path, body)."""
    files = dict({p: MARK + "\n" + b for p, b in tree.items()}, **{p: MARK + "\n" + b for p, b in mine})
    return L.layout_findings(files, own(piece(*mine)), PATHS, later)


UTILS = {"data_utils.py": "def load():\n    return []\n"}
SRC = dict(UTILS, **{"src/find_cmd.py": "from data_utils import load\n\n\ndef cmd_find(q):\n    return load()\n",
                     "src/export_cmd.py": "def cmd_export(p):\n    return 0\n"})
ENTRY = ("contactmgr.py", "from find_cmd import cmd_find\nfrom export_cmd import cmd_export\n\n\ndef main():\n"
         "    cmd_find('a')\n")


class FindingTests(unittest.TestCase):
    def test_a_root_entry_importing_a_src_module_by_bare_name(self):  # smoke2's X80
        got = check(SRC, ENTRY)
        self.assertFalse(got["ok"])
        self.assertEqual([(f["file"], f["line"], f["module"], f["found_at"]) for f in got["findings"]],
                         [("contactmgr.py", 2, "find_cmd", ["src/find_cmd.py"]),
                          ("contactmgr.py", 3, "export_cmd", ["src/export_cmd.py"])])
        self.assertEqual(got["checked"], ["contactmgr.py"])
        self.assertEqual(got["tell"][0],
                         "contactmgr.py imports find_cmd (`from find_cmd import cmd_find`), but from the project's "
                         "root Python finds no find_cmd: the project has it only at src/find_cmd.py (from the root: "
                         "src.find_cmd)")

    def test_a_left_out_steps_module_is_no_finding(self):  # smoke2's X32: its export_cmd is the left-out s4's
        tree = {k: v for k, v in SRC.items() if k != "src/export_cmd.py"}
        got = check(tree, ENTRY)
        self.assertEqual([f["module"] for f in got["findings"]], ["find_cmd"])
        self.assertTrue(check(UTILS, ENTRY)["ok"])  # nothing of the project holds either

    def test_imports_a_real_run_resolves_pass(self):
        root = {"find_cmd.py": SRC["src/find_cmd.py"], "export_cmd.py": SRC["src/export_cmd.py"], **UTILS}
        self.assertTrue(check(root, ENTRY)["ok"])
        self.assertTrue(check(SRC, ("contactmgr.py", "from src.find_cmd import cmd_find\nfrom src import export_cmd\n"
                                                     ))["ok"])
        # a src/ file importing a root module or a sibling: its own folder, then the root (python3 -m from there)
        self.assertTrue(check(UTILS, ("src/find_cmd.py", "from data_utils import load\n"))["ok"])
        self.assertTrue(check({"src/store.py": "X = 1\n"}, ("src/cli.py", "from store import X\n"))["ok"])
        self.assertTrue(check({"app.py": "X = 1\n"}, ("tests/test_app.py", "from app import X\n"))["ok"])
        self.assertTrue(check({"pkg/core/db.py": "X = 1\n"}, ("pkg/core/cli.py", "from pkg.core.db import X\n"))["ok"])
        # the piece's own other file, a relative import, a dotted import of a folder that is there
        self.assertTrue(check({}, ("tool/a.py", "from tool.b import X\nfrom . import b\n"), ("tool/b.py", "X = 1\n")
                              )["ok"])

    def test_the_interpreters_own_modules_never_count(self):
        tree = {"src/json.py": "X = 1\n", "src/yaml.py": "X = 1\n", "src/find_cmd.py": "X = 1\n"}
        got = check(tree, ("main.py", "import json\nimport yaml\nimport find_cmd\n"))
        self.assertEqual([f["module"] for f in got["findings"]], ["find_cmd"])
        self.assertTrue(L.interpreters("json"))
        self.assertTrue(L.interpreters("os.path"))
        self.assertFalse(L.interpreters("find_cmd", PATHS))
        self.assertFalse(L.interpreters("", PATHS))

    def test_the_interpreters_own_paths(self):
        paths = P.own_paths()
        self.assertTrue(paths and all(os.path.isabs(x) for x in paths), paths)
        self.assertNotIn(os.getcwd(), paths)  # -I: never a script's folder
        self.assertEqual(P.own_paths(os.path.join(os.sep, "no", "such", "python3")), ())

    def test_guarded_imports_are_skipped(self):
        body = ("try:\n    from find_cmd import cmd_find\nexcept ImportError:\n    from src.find_cmd import cmd_find\n"
                "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from export_cmd import cmd_export\n"
                "try:\n    import export_cmd\nexcept Exception:\n    export_cmd = None\n"
                "try:\n    import find_cmd as fc\nexcept:\n    fc = None\n")
        self.assertTrue(check(SRC, ("contactmgr.py", body))["ok"])
        # a handler, an else or a finally isn't guarded by its own try, nor TYPE_CHECKING's else
        unguarded = ("try:\n    import json\nexcept ImportError:\n    import find_cmd\n"
                     "if TYPE_CHECKING:\n    pass\nelse:\n    import export_cmd\n"
                     "try:\n    import json\nexcept ValueError:\n    pass\n")
        self.assertEqual([f["module"] for f in check(SRC, ("contactmgr.py", unguarded))["findings"]],
                         ["find_cmd", "export_cmd"])
        inner = "def main():\n    from find_cmd import cmd_find\n    return cmd_find\n"  # inside a function too
        self.assertEqual([f["line"] for f in check(SRC, ("contactmgr.py", inner))["findings"]], [3])

    def test_what_skips_a_file_or_the_project(self):
        got = check(SRC, ("contactmgr.py", "import sys\nsys.path.insert(0, 'src')\nfrom find_cmd import cmd_find\n"))
        self.assertEqual((got["ok"], got["checked"], got["skipped"]),
                         (True, [], {"contactmgr.py": "it changes sys.path itself"}))
        for path, body in (("pyproject.toml", "[project]\nname = 'x'\n"), ("setup.cfg", "[metadata]\n"),
                           ("conftest.py", "X = 1\n"), ("pytest.ini", "[pytest]\npythonpath = src\n"),
                           ("README.md", "Run with PYTHONPATH=src python3 contactmgr.py\n")):
            got = check(dict(SRC, **{path: body}), ENTRY)
            self.assertEqual((got["ok"], list(got["skipped"])), (True, ["project"]), path)
        got = check(SRC, ENTRY, later="Write pyproject.toml so the src/ layout installs.")
        self.assertEqual(got["skipped"], {"project": "a later step names pyproject.toml"})
        self.assertFalse(check(SRC, ENTRY, later="Keep a pyproject.toml.bak copy")["ok"])  # not that file
        broken = own(piece(("contactmgr.py", "from find_cmd import (\n")))
        got = L.layout_findings(dict(SRC, **{"contactmgr.py": "x"}), broken, PATHS)
        self.assertEqual(got["skipped"], {"contactmgr.py": "its block doesn't parse alone"})

    def test_a_submodule_only_another_package_has(self):
        tree = {"app/__init__.py": "", "src/app/models.py": "X = 1\n", "app/views.py": "Y = 1\n"}
        got = check(tree, ("main.py", "from app import models, views\n"))
        self.assertEqual([(f["module"], f["found_at"]) for f in got["findings"]], [("app.models",
                                                                                    ["src/app/models.py"])])
        tree["app/__init__.py"] = "models = None\n"  # the package binds the name itself
        self.assertTrue(check(tree, ("main.py", "from app import models, views\n"))["ok"])
        self.assertTrue(check(tree, ("main.py", "from app import *\n"))["ok"])


class ResolveTests(unittest.TestCase):
    def test_pythons_search_read_on_the_tree(self):
        files = {"a.py": "", "pkg/__init__.py": "", "pkg/m.py": "", "ns/x/y.py": "", "data/rows.csv": ""}
        dirs = L.folders(files)
        for module, search, want in (("a", [""], "a.py"), ("pkg", [""], "pkg/"), ("pkg.m", [""], "pkg/m.py"),
                                     ("ns.x.y", [""], "ns/x/y.py"), ("ns.x", [""], "ns/x/"), ("data", [""], "data/"),
                                     ("m", ["pkg", ""], "pkg/m.py"), ("m", [""], None), ("a.b", [""], None),
                                     ("y", ["ns/x", "ns", ""], "ns/x/y.py"), ("pkg.n", [""], None)):
            self.assertEqual(L.resolve(module, search, files, dirs), want, module)

    def test_project_modules_are_gos_suffixes_and_folders(self):
        mods = L.project_modules({"src/find_cmd.py": "", "src/pkg/__init__.py": "", "README.md": ""})
        self.assertEqual(sorted(mods), ["find_cmd", "pkg", "src", "src.find_cmd", "src.pkg"])
        self.assertEqual(mods["find_cmd"], ["src/find_cmd.py"])
        self.assertEqual(L.module_names("src/pkg/__init__.py"), ["src.pkg", "pkg"])

    def test_imports_of(self):
        code = MARK + "\nimport a.b, c\nfrom d.e import f, g\nfrom . import h\nfrom .i import j\n"
        self.assertEqual([(m, n) for _l, m, n, _s in L.imports_of(code)], [("a.b", None), ("c", None),
                                                                          ("d.e", ["f", "g"])])
        self.assertIsNone(L.imports_of("def f(:\n"))


class TellTests(unittest.TestCase):
    def test_the_tell_line_names_the_folder_and_fits(self):
        f = {"file": "app/cli.py", "line": 3, "module": "store", "statement": "from store import " + ", ".join(
            f"name_{k}" for k in range(30)), "found_at": ["lib/store.py", "old/store.py"]}
        line = L.tell_line(f)
        self.assertTrue(line.startswith("app/cli.py imports store (`from store import name_0, name_1"), line)
        self.assertIn("…`), but from app/ or a folder above it Python finds no store: the project has it", line)
        self.assertTrue(line.endswith("only at lib/store.py (from the root: lib.store) and 1 more"), line)
        self.assertLessEqual(len(line), 240)  # hints.FAILURE_CHARS
        f["file"] = "app/" + "deep/" * 40 + "cli.py"  # the statement gives way first, then nothing more is cut
        self.assertIn("(`from store import na…`)", L.tell_line(f))

    def test_the_fixed_wording_is_known(self):
        self.assertEqual(L.TELL_FORMS, ("but from the project's root Python finds no", "the project has it only at",
                                        "or a folder above it Python finds no"))
        line = L.tell_line(check(SRC, ENTRY)["findings"][0])
        words = lambda t: " ".join(re.findall(r"\w+", t.lower()))  # noqa: E731
        for form in L.TELL_FORMS:
            self.assertGreaterEqual(len(re.findall(r"\w+", form)), 5)
        self.assertTrue(all(words(form) in words(line) for form in L.TELL_FORMS[:2]))


if __name__ == "__main__":
    unittest.main()

"""datagen/lang_check.py: what of a files piece no check read, and the parsers for the other languages this computer
has (the second smoke's audit, rc/unverified-languages and its skeptic's extension-only variant).

The language of a file is its File: path's extension alone (no fence, no file name: a Dockerfile, a Makefile, go.mod
or bin/deploy is no fact either way); Python, a parse that passed (gate["parse"], the local parsers' included) and
markup never count as unchecked; the build filter reads only an unverified files example. The local parsers run for
real under sandbox-exec, each on a copy: gofmt -e, bash -n, zsh -n, bash --posix -n for #!/bin/sh (arrays and
`function f {` pass, as they run under this Mac's /bin/sh), ruby --disable-gems -c, xmllint --noout --nonet and
swift-frontend -parse; they parse only (bash -n prints nothing a run would), bash 4 and Ruby 3 grammar and a #! line
for another program are skipped, never failed, a verdict is cached and a skip isn't; and the code gate's parse_file
sends those extensions to them, so their results land in the gate's "parse".

Every piece and file here is a hand-written test fixture (each carries the mark, in its language's comment), never
training data.
"""
import os
import shutil
import tempfile
import unittest

from tests import _paths  # noqa: F401
from datagen import code_gate as G
from datagen import lang_check as L
from datagen import pysandbox as P
from datagen.common import Cache
from runner import mock_ollama
from tools import blender_check

MARK = mock_ollama.MARK  # "# test fixture, never training data"
SLASH_MARK = "// " + MARK[2:]
XML_MARK = "<!-- " + MARK[2:] + " -->"
SANDBOX = P.can_sandbox()
HANDOFF = "```handoff\nprovides: {p}\nuses: none\nassumed: none\n```"


def files_piece(*blocks, provides="the files above"):
    """A files piece of (path, fence language, body) blocks and a handoff."""
    parts = [f"File: {path}\n```{lang}\n{body.rstrip()}\n```" for path, lang, body in blocks]
    return "\n\n".join(parts) + "\n\n" + HANDOFF.format(p=provides)


PS1 = ("powershell", MARK + "\nparam([string]$Path)\nWrite-Output \"Reading $Path\"\n")
PIECE_PS1 = files_piece(("src/Get-Schema.ps1",) + PS1)
PIECE_LUA = files_piece(("config.lua", "lua", "-- " + MARK[2:] + "\nreturn { host = \"localhost\" }\n"))
PIECE_JS = files_piece(("src/index.js", "javascript", SLASH_MARK + "\nconsole.log(1);\n"),
                       ("Dockerfile", "dockerfile", MARK + "\nFROM node:20\n"),
                       ("README.md", "markdown", MARK + "\n# Tool\n"))
PIECE_PY = files_piece(("tool.py", "python", MARK + "\nX = 1\n"), ("notes.txt", "text", MARK + "\nplain\n"))
PIECE_NO_EXT = files_piece(("bin/deploy", "bash", MARK + "\necho deploy\n"), ("go.mod", "go", "module x\n"))


class LanguageTests(unittest.TestCase):
    def test_the_language_is_the_extension_alone(self):
        for path, want in (("a.py", "Python"), ("src/x.ps1", "PowerShell"), ("q.sql", "SQL"), ("m.go", "Go"),
                           ("s.sh", "Shell"), ("k.zsh", "Shell"), ("p.plist", "XML"), ("i.svg", "XML"),
                           ("App.csproj", "XML"), ("README.md", ""), ("index.html", ""), (".gitignore", ""),
                           (".env", ""), (".env.example", ""), ("requirements.txt", ""), ("Dockerfile", None),
                           ("Makefile", None), ("bin/deploy", None), ("go.mod", None), ("api.proto", None),
                           ("tsconfig.jsonc", None)):
            self.assertEqual(L.language(path), want, path)
        self.assertEqual(L.LOCAL_EXT["go"], "Go")
        self.assertNotIn("py", L.LOCAL_EXT)

    def test_unchecked_code_is_what_no_check_read_and_passed(self):
        self.assertEqual(L.unchecked_code(PIECE_PS1), [("src/Get-Schema.ps1", "PowerShell")])
        self.assertEqual(L.unchecked_code(PIECE_LUA), [("config.lua", "Lua")])
        self.assertEqual(L.unchecked_code(PIECE_PY), [])  # Python and plain text: never unchecked
        self.assertEqual(L.unchecked_code(PIECE_NO_EXT), [])  # no extension, or one nothing knows: no fact
        # JavaScript is checked only when its parse passed; the Dockerfile and README never count
        self.assertEqual(L.unchecked_code(PIECE_JS), [("src/index.js", "JavaScript")])
        ok = [{"path": "src/index.js", "kind": "JavaScript", "ok": True, "error": None, "line": 0}]
        self.assertEqual(L.unchecked_code(PIECE_JS, ok), [])
        skipped = [{"path": "src/index.js", "kind": "JavaScript", "skipped": "jsx or flow, which node can't read"}]
        self.assertEqual(L.unchecked_code(PIECE_JS, skipped), [("src/index.js", "JavaScript")])
        self.assertEqual(L.unchecked_code(PIECE_JS, local={"./src/index.js": {"ok": True}}), [])
        self.assertEqual(L.unchecked_code("no blocks at all"), [])

    def test_the_build_filter_reads_only_unverified_files_examples(self):
        self.assertEqual(L.build_drop({"mode": "files", "unverified": True}, PIECE_PS1), "unchecked_code")
        self.assertIsNone(L.build_drop({"mode": "files", "unverified": False}, PIECE_PS1))  # something ran on it
        self.assertIsNone(L.build_drop({"mode": "files"}, PIECE_PS1))
        self.assertIsNone(L.build_drop({"mode": "python-script", "unverified": True}, PIECE_PS1))
        self.assertIsNone(L.build_drop({"mode": "files", "unverified": True}, PIECE_PY))
        ok = [{"path": "src/index.js", "kind": "JavaScript", "ok": True, "error": None, "line": 0}]
        self.assertIsNone(L.build_drop({"mode": "files", "unverified": True}, PIECE_JS, ok))
        self.assertEqual(L.build_drop({"mode": "files", "unverified": True}, PIECE_JS, None), "unchecked_code")

    def test_which_shell_reads_a_script(self):
        for body, path, want in (("echo", "a.sh", "bash"), ("#!/bin/bash\n", "a.sh", "bash"),
                                 ("#!/usr/bin/env bash\n", "a.sh", "bash"), ("#!/bin/sh\n", "a.sh", "sh"),
                                 ("#!/usr/bin/env sh\n", "a.sh", "sh"), ("#!/bin/zsh\n", "a.sh", "zsh"),
                                 ("echo", "a.zsh", "zsh"), ("#!/bin/dash\n", "a.sh", "bash"),
                                 ("#!/usr/bin/env python3\n", "a.sh", None), ("#!/usr/bin/fish\n", "a.sh", None)):
            self.assertEqual(L._shell_for(body, path), want, body)


@unittest.skipUnless(SANDBOX, "needs sandbox-exec (macOS)")
class LocalParserTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="test-lang-", dir=blender_check.scratch_root())
        self.cache = Cache(os.path.join(self.work, "runs.jsonl"))
        self.lp = L.LocalParsers(self.cache, self.work)

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def need(self, lang):
        if not self.lp.has(lang):
            self.skipTest(f"no {lang} parser here")

    def verdict(self, got):
        return (got.get("ok"), got.get("line"), bool(got.get("error"))) if "skipped" not in got else got["skipped"]

    def test_go(self):
        self.need("Go")
        good = SLASH_MARK + "\npackage main\n\nimport \"fmt\"\n\nfunc main() {\n\tfmt.Println(1)\n}\n"
        self.assertEqual(self.verdict(self.lp.check("Go", good, "main.go")), (True, 0, False))
        got = self.lp.check("Go", SLASH_MARK + "\npackage main\n\nfunc main() {\n", "main.go")
        self.assertEqual((got["ok"], got["line"] > 0), (False, True), got)
        unused = SLASH_MARK + "\npackage main\n\nimport \"os\"\n\nfunc main() {}\n"  # syntax only
        self.assertTrue(self.lp.check("Go", unused, "main.go")["ok"])

    def test_shell(self):
        self.need("Shell")
        self.assertTrue(self.lp.check("Shell", "#!/bin/bash\n" + MARK + "\nif true; then echo hi; fi\n", "a.sh")["ok"])
        got = self.lp.check("Shell", "#!/bin/bash\n" + MARK + "\nif true; then\n  echo hi\n", "a.sh")
        self.assertEqual((got["ok"], got["line"] > 0), (False, True), got)
        posix = "#!/bin/sh\n" + MARK + "\narr=(a b)\nfunction f { echo \"$1\"; }\nf \"${arr[0]}\"\n"
        self.assertTrue(self.lp.check("Shell", posix, "run.sh")["ok"])  # what this Mac's /bin/sh runs
        bash4 = "#!/bin/bash\n" + MARK + "\nls |& cat\n"
        self.assertIn("bash 4", self.lp.check("Shell", bash4, "a.sh")["skipped"])
        other = "#!/usr/bin/env python3\n" + MARK + "\nprint(1)\n"
        self.assertIn("another program", self.lp.check("Shell", other, "a.sh")["skipped"])

    def test_shell_parses_and_runs_nothing(self):
        self.need("Shell")
        body = MARK + "\necho ran-it\n"
        self.assertTrue(self.lp.check("Shell", body, "a.sh")["ok"])
        files = {"wm_check.sh": body}
        ran = P.run_tool(files, self.lp.tools["bash"], ["wm_check.sh"], work=self.work)  # the control: it does run
        parsed = P.run_tool(files, self.lp.tools["bash"], ["-n", "wm_check.sh"], work=self.work)
        self.assertEqual((ran["exit"], ran["output"].strip(), ran["sandboxed"]), (0, "ran-it", True), ran)
        self.assertEqual((parsed["exit"], parsed["output"]), (0, ""), parsed)

    def test_zsh(self):
        if not self.lp.tools.get("zsh"):
            self.skipTest("no zsh here")
        self.assertTrue(self.lp.check("Shell", MARK + "\nfor x in a b; do print -r -- $x; done\n", "a.zsh")["ok"])
        got = self.lp.check("Shell", "#!/bin/zsh\n" + MARK + "\nfor x in a b; do\n", "a.sh")
        self.assertFalse(got["ok"], got)

    def test_ruby(self):
        self.need("Ruby")
        self.assertTrue(self.lp.check("Ruby", MARK + "\ndef add(a, b)\n  a + b\nend\n", "a.rb")["ok"])
        got = self.lp.check("Ruby", MARK + "\ndef add(a, b)\n  a +\n", "a.rb")
        self.assertEqual((got["ok"], got["line"] > 0), (False, True), got)
        self.assertIn("Ruby 3", self.lp.check("Ruby", MARK + "\ndef sq(x) = x * x\n", "a.rb")["skipped"])

    def test_xml(self):
        self.need("XML")
        plist = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" + XML_MARK + "\n<!DOCTYPE plist PUBLIC "
                 "\"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
                 "<plist version=\"1.0\"><dict><key>a</key><string>b</string></dict></plist>\n")
        self.assertTrue(self.lp.check("XML", plist, "Info.plist")["ok"])  # its DOCTYPE isn't fetched
        got = self.lp.check("XML", XML_MARK + "\n<a><b></a>\n", "a.xml")
        self.assertEqual((got["ok"], got["line"]), (False, 2), got)
        self.assertFalse(self.lp.check("XML", XML_MARK + "\n<svg>&nbsp;</svg>\n", "i.svg")["ok"])  # not XML's

    def test_swift(self):
        self.need("Swift")
        self.assertTrue(self.lp.check("Swift", SLASH_MARK + "\nlet x = 1\nprint(x)\n", "main.swift")["ok"])
        got = self.lp.check("Swift", SLASH_MARK + "\nfunc f( {\n", "main.swift")
        self.assertEqual((got["ok"], got["line"]), (False, 2), got)

    def test_a_verdict_is_cached_and_a_skip_isnt(self):
        self.need("Shell")
        body = "#!/bin/bash\n" + MARK + "\necho cached\n"
        self.assertFalse(self.lp.check("Shell", body, "a.sh")["cached"])
        self.assertTrue(self.lp.check("Shell", body, "a.sh")["cached"])
        self.assertNotIn("cached", self.lp.check("Shell", "#!/bin/bash\n" + MARK + "\nls |& cat\n", "a.sh"))
        lp = L.LocalParsers(self.cache, self.work)
        lp.tools = dict(lp.tools, Go=None)
        self.assertEqual(lp.check("Go", "package main\n", "m.go"), {"skipped": "no parser for Go here"})
        self.assertEqual(lp.check("Lua", "return 1\n", "a.lua"), {"skipped": "no parser for Lua here"})

    def test_check_piece_reads_each_own_file_it_has_a_parser_for(self):
        self.need("Shell")
        piece = files_piece(("deploy.sh", "bash", "#!/bin/bash\n" + MARK + "\nif true; then\n"),
                            ("tool.py", "python", MARK + "\nX = 1\n"), ("Get.ps1",) + PS1)
        got = self.lp.check_piece(piece)
        self.assertEqual(list(got), ["deploy.sh"])
        self.assertEqual((got["deploy.sh"]["ok"], got["deploy.sh"]["language"]), (False, "Shell"))
        self.assertEqual(L.unchecked_code(piece, local=got), [("deploy.sh", "Shell"), ("Get.ps1", "PowerShell")])


@unittest.skipUnless(SANDBOX, "needs sandbox-exec (macOS)")
class ParseFileTests(unittest.TestCase):
    """The code gate's parse_file sends the local parsers' extensions to them; their results are what lands in the
    gate's "parse" (piece_check's _parse_own), the one record lang_check.unchecked_code reads."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="test-lang-gate-", dir=blender_check.scratch_root())
        self.gate = G.CodeGate(None, Cache(os.path.join(self.work, "runs.jsonl")), work=self.work)

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def test_local_kinds_go_to_the_local_parsers(self):
        if not self.gate.local.has("Shell"):
            self.skipTest("no shell parser here")
        got = self.gate.parse_file("scripts/run.sh", "#!/bin/bash\n" + MARK + "\nif true; then\n")
        self.assertEqual((got["path"], got["kind"], got["ok"], got["line"] > 0), ("scripts/run.sh", "Shell", False,
                                                                                  True), got)
        got = self.gate.parse_file("scripts/run.sh", "#!/bin/bash\n" + MARK + "\necho {{ name }}\n")
        self.assertTrue(got["ok"], got)  # a template that parses passes as it is
        got = self.gate.parse_file("chart.xml", XML_MARK + "\n<a>{{ if .x }}<b>{{ end }}</a>\n")
        self.assertEqual(got.get("skipped"), "a template")  # a broken template isn't the file's own syntax
        self.assertIsNone(self.gate.parse_file("Get.ps1", PS1[1]))  # nothing here reads PowerShell
        self.assertIsNone(self.gate.parse_file("Dockerfile", "FROM x\n"))
        self.assertEqual(self.gate.parse_file("data.json", "{}")["kind"], "JSON")  # the others as before


if __name__ == "__main__":
    unittest.main()

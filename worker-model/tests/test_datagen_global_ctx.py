"""After the fifth smoke (Nov 6): global_ctx (datagen/blender_gate.global_ctx), a function of a Blender piece that reads
a ctx it is never given, read from the code, no run. The gate's alone run (Chimera's aloneScript) binds ctx at module
level before it calls build_sN, so such a read runs there, while Chimera's join calls build_sN(ctx) inside its main()
and the read raises NameError in the person's script (the fifth smoke's D14 and D10 tries; smoke4's n-blender-0000-01
r2 s2 c0 crashed so on its joined run). Python's own scopes (symtable) decide what is the function's own: a parameter,
an assignment, a loop, with, except, import or walrus target, a closure of build_sN's ctx. A reason at the alone stage
that still goes on to the joined run (JOINED_SHOWS), hard in task.py, ranked where the joined run is, told whatever
else fails, its wording ours and registered with the echo check. The real-Blender half (alone passes, Chimera's join
crashes, a variant fails alone) is tests/test_datagen_blender.py's GlobalCtxTests.

Every piece here is Claude-written test text and carries the fixture mark, never training data. Under a second.
"""
# test fixture, never training data
import unittest

from tests import _paths  # noqa: F401
from contract import texts
from datagen import blender_gate as BG
from datagen import hints as H
from datagen import report as RP
from datagen import task as T
from runner import mock_ollama

MARK = mock_ollama.MARK


def piece(top="", body='    obj = _s3_make("chimera_lamp")\n    ctx["objects"]["lamp"] = obj\n', sid="s3"):
    return (f"{MARK}\nimport bpy\n\nSETTINGS_{sid} = {{\"power\": 800}}\n\n\n{top}\n\ndef build_{sid}(ctx):\n{body}\n\n"
            f"if __name__ == \"__main__\":\n    build_{sid}({{\"scene\": bpy.context.scene, \"collection\": "
            f"bpy.context.scene.collection, \"objects\": {{}}, \"values\": {{}}}})\n")


# D14's shape (smoke5 n-blender-0000-01 r1 s3 c0): a module-level helper that links into ctx["collection"]
GLOBAL_HELPER = '''def _s3_make(name):
    obj = bpy.data.objects.new(name, None)
    ctx["collection"].objects.link(obj)
    return obj'''
OWN_HELPER = '''def _s3_make(name, ctx):
    obj = bpy.data.objects.new(name, None)
    ctx["collection"].objects.link(obj)
    return obj'''


class ReadingTests(unittest.TestCase):
    def names(self, code):
        return [(r["function"], r["line"]) for r in BG.global_ctx(code)]

    def test_a_module_level_helper_that_reads_the_global_ctx(self):
        code = piece(GLOBAL_HELPER)
        self.assertEqual(self.names(code), [("_s3_make", 7)])
        self.assertEqual(code.split("\n")[6], "def _s3_make(name):")
        # its own main guard binding ctx doesn't count: Chimera drops the guard (and the validator refuses any other
        # module-level ctx)
        guarded = code.replace('    build_s3({"scene"', '    ctx = {"scene"').replace(
            '"values": {}})\n', '"values": {}}\n    build_s3(ctx)\n')
        self.assertIn("    ctx = {", guarded)
        self.assertEqual(self.names(guarded), [("_s3_make", 7)])

    def test_what_is_the_functions_own_ctx(self):
        body = '    obj = _s3_make("chimera_lamp", ctx)\n    ctx["objects"]["lamp"] = obj\n'
        self.assertEqual(self.names(piece(OWN_HELPER, body)), [])  # a parameter
        own = {
            "assigned": "def _s3_make(name):\n    ctx = bpy.context.scene\n    return ctx",
            "a loop's": "def _s3_make(name):\n    for ctx in ():\n        pass\n    return name",
            "a with's": "def _s3_make(name):\n    with open(name) as ctx:\n        return ctx.read()",
            "an except's": ("def _s3_make(name):\n    try:\n        pass\n    except Exception as ctx:\n"
                            "        return ctx"),
            "an import's": "def _s3_make(name):\n    import bpy as ctx\n    return ctx",
            "a walrus'": "def _s3_make(name):\n    if (ctx := name):\n        return ctx",
            "a keyword-only one": "def _s3_make(name, *, ctx=None):\n    return ctx",
        }
        for what, top in own.items():
            with self.subTest(what):
                self.assertEqual(self.names(piece(top)), [])
        # build_sN's own ctx reaches what is nested in it: a closure, a lambda, a comprehension
        nested = ('    def link(obj):\n        ctx["collection"].objects.link(obj)\n'
                  '    pick = lambda k: ctx["objects"][k]\n    names = [k for k in ctx["objects"]]\n'
                  '    link(bpy.data.objects.new("chimera_lamp", None))\n')
        self.assertEqual(self.names(piece("", nested)), [])
        # declared global and assigned in a function: then there is a module-level ctx
        setter = "def _s3_keep(c):\n    global ctx\n    ctx = c\n\n\n" + GLOBAL_HELPER
        self.assertEqual(self.names(piece(setter)), [])

    def test_every_kind_of_scope_that_reads_it(self):
        cases = {
            "a lambda": ('_s3_link = lambda obj: ctx["collection"].objects.link(obj)', [("a lambda", 7)]),
            "a method": ('class _S3Rig:\n    def add(self, obj):\n        ctx["collection"].objects.link(obj)',
                         [("_S3Rig.add", 8)]),
            "a function inside a helper": ('def _s3_make(name):\n    def link(obj):\n        ctx["collection"].objects'
                                           '.link(obj)\n    return link', [("_s3_make.link", 8)]),
            "a comprehension in a helper": ('def _s3_all():\n    return [ctx["objects"][k] for k in ("lamp",)]',
                                            [("_s3_all.a comprehension", 7)]),
        }
        for what, (top, want) in cases.items():
            with self.subTest(what):
                got = self.names(piece(top))
                if what == "a comprehension in a helper":  # 3.12+ inlines it: the read is the helper's own then
                    self.assertIn(got, (want, [("_s3_all", 7)]))
                else:
                    self.assertEqual(got, want)
        # a build function whose parameter isn't named ctx, and what is nested in it
        renamed = piece("", '    ctx["objects"]["lamp"] = None\n    inner = lambda: ctx\n').replace(
            "def build_s3(ctx):", "def build_s3(context):")
        self.assertEqual(self.names(renamed), [("build_s3", 9), ("build_s3.a lambda", 11)])

    def test_code_that_doesnt_parse_reads_nothing(self):
        self.assertEqual(BG.global_ctx(piece(GLOBAL_HELPER) + "\ndef broken(:\n"), [])
        self.assertEqual(BG.global_ctx(""), [])


class LineTests(unittest.TestCase):
    def test_the_line(self):
        one = BG.global_ctx_tell("s3", [{"function": "_s3_make", "line": 7}])
        self.assertEqual(one, "_s3_make reads ctx without being given it: pass ctx in as an argument, since Chimera's "
                              "join calls build_s3(ctx) inside a function and the piece has no ctx outside it")
        many = BG.global_ctx_tell("s3", [{"function": f, "line": k} for k, f in enumerate(
            ["_s3_make_area_light", "_s3_make_spot_light", "_s3_make_spot_light.inner", "_s3_dummy_empty_at",
             "_s3_aim"])])
        self.assertTrue(many.startswith("_s3_make_area_light, _s3_make_spot_light, _s3_dummy_empty_at and more read "
                                        "ctx without being given it"))
        self.assertLessEqual(len(many), H.FAILURE_CHARS)
        self.assertIsNone(BG.global_ctx_tell("s3", []))

    def test_its_wording_is_ours_known_to_the_echo_check_and_not_chimeras(self):
        self.assertEqual(BG.GLOBAL_CTX_FORMS, (
            "ctx without being given it: pass ctx in as an argument, since Chimera's join calls",
            "(ctx) inside a function and the piece has no ctx outside it"))
        n = len(BG.geometry.TELL_FORMS)
        self.assertEqual(BG.TELL_FORMS[-n - 2:-n], BG.GLOBAL_CTX_FORMS)  # before the geometry's, which stay last
        line = BG.global_ctx_tell("s3", [{"function": "_s3_make", "line": 7}])
        for form in BG.GLOBAL_CTX_FORMS:
            self.assertIn(form, line)
            self.assertNotRegex(form, r"\d")  # no version
            self.assertEqual(H.echoed_note("# " + form + "\nimport bpy\n"), "failure_line", form)
        for k in range(1, 9):  # nothing of Chimera's Blender rule, for any step
            rule = texts.fill(texts.MODE_BLENDER, sid=f"s{k}")
            for form in BG.GLOBAL_CTX_FORMS:
                self.assertFalse(H.runs(form, H.NOTE_N) & H.runs(rule, H.NOTE_N), (k, form))
            self.assertIsNone(H.echoed_note(rule))
        # a piece that does what the line asks repeats none of it
        fixed = piece(OWN_HELPER, '    obj = _s3_make("chimera_lamp", ctx)\n    ctx["objects"]["lamp"] = obj\n')
        self.assertEqual(BG.global_ctx(fixed), [])
        self.assertIsNone(H.echoed_note(fixed))


class ReasonTests(unittest.TestCase):
    def test_hard_in_task_but_on_to_the_joined_run(self):
        self.assertEqual(BG.JOINED_SHOWS, ("global_ctx",))
        self.assertEqual(BG._hard(["global_ctx"]), [])  # the gate goes on to Chimera's join, whose crash it shows
        self.assertEqual(BG._hard(["global_ctx", "aim_mismatch"]), ["aim_mismatch"])
        self.assertNotIn("global_ctx", BG.SOFT_GATE)
        for used in (False, True):
            self.assertFalse(T.soft(["global_ctx"], used))
            self.assertFalse(T.soft(["global_ctx", "ctx_channel"], used))
        # where it is found: the joined script's fault, a try that passed every alone check got that far
        self.assertEqual(T._blender_stage(["global_ctx"]), "joined")
        self.assertEqual(T._blender_stage(["aim_mismatch", "dead_output_key", "global_ctx"]), "alone")
        self.assertEqual(T._blender_stage(["global_ctx", "joined_strict:5.2.2"]), "joined")
        # told whatever else fails, so it is a fault in common for heard; and the report counts it
        c = {"reasons": ["alone_strict:5.2.2"], "crash": {"error": "ValueError: bad"},
             "gate": {"global_ctx": [{"function": "_s3_make", "line": 7}]}}
        self.assertIn("global_ctx", T.fault_keys(c))
        self.assertIn("global_ctx", RP.NEW_GATES)
        self.assertIn("code_syntax", RP.NEW_GATES)


if __name__ == "__main__":
    unittest.main()

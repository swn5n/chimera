"""runner/blender_run.py and runner/score.py: which script runs, the sandbox profile, the scoring helpers. Two tests
run real Blender (sandboxed) and need CHIMERA_BIN; they skip without it."""
import ast
import contextlib
import copy
import io
import os
import types
import unittest

from tests import _paths  # noqa: F401
from tests import contract_fixtures as F
from runner import blender_run as br
from runner import mock_ollama, score
from tools import blenders

MARK = F.MARK

# s2 uses s1, whose SETTINGS_s1["output"] saves and renders: the dependency's render must not end the run first
RENDER_PLAN = copy.deepcopy(F.BLENDER_PLAN)
RENDER_PLAN["steps"][1]["depends_on"] = ["s1"]



def block(body, lang="python"):
    return f"```{lang}\n{body}\n```"


BPY6 = "\n".join([MARK, "import bpy"] + [f"x{i} = {i}" for i in range(6)])
PY6 = "\n".join([MARK, "import json"] + [f"y{i} = {i}" for i in range(6)])
# A today's-style reply whose own script crashes in Blender 4.1 and newer (Mesh.use_auto_smooth was removed)
CRASHING_TODAY_REPLY = "Here is the table.\n\n" + block("\n".join([
    MARK, "import bpy", 'mesh = bpy.data.meshes.new("chimera_table")', 'obj = bpy.data.objects.new("chimera_table", mesh)',
    "bpy.context.scene.collection.objects.link(obj)", "obj.location = (1, 1, 0.55)", "mesh.use_auto_smooth = True",
    'print("table done")']))


class PickScriptTests(unittest.TestCase):
    def test_like_chimeras_pick_script(self):
        self.assertEqual(br.pick_script(block(BPY6))[0:2], ("run_blender", BPY6))
        short = block("import bpy\nprint(1)")
        self.assertEqual(br.pick_script(short), ("", "", ""))  # under six code lines: a snippet
        two = block(BPY6) + "\n\n" + block(BPY6.replace("x", "z"))
        kind, script, why = br.pick_script(two)
        self.assertEqual((kind, script), ("run_blender", ""))
        self.assertIn("2 Blender scripts of similar size", why)
        big = block(BPY6 + "\n" + "\n".join(f"w{i} = {i}" for i in range(20)))
        self.assertEqual(br.pick_script(big + "\n" + block(BPY6))[1], br.dedent(BPY6 + "\n" + "\n".join(f"w{i} = {i}" for i in range(20))))
        self.assertIn("2 Python files", br.pick_script(block(PY6) + "\n" + block(PY6), ("code",))[2])
        self.assertEqual(br.pick_script(block(PY6), ("writing",)), ("", "", ""))  # plain Python only in code plans
        self.assertEqual(br.pick_script(block("import flask\n" + PY6), ("code",))[2], "it would open a window or start a server")
        self.assertEqual(br.count_scripts(two + "\n" + block(PY6)), {"blender": 2, "python": 1})

    def test_script_for_step(self):
        plan = F.BLENDER_PLAN
        kind, script, notes = br.script_for_step(plan, 2, {"s2": F.S2}, F.S3)
        self.assertEqual(kind, "joined")
        self.assertIn("build_s2(ctx)\n    build_s3(ctx)", script)
        today = mock_ollama.today_script("lamp")
        kind, script, _ = br.script_for_step(plan, 2, {"s2": F.S2}, today)
        self.assertEqual(kind, "after_deps")
        self.assertLess(script.index("def build_s2"), script.index("chimera_lamp"))
        self.assertEqual(br.script_for_step(plan, 0, {}, today)[0], "alone")
        self.assertEqual(br.script_for_step(plan, 2, {"s2": None}, today)[0], "alone")  # a failed dependency
        self.assertEqual(br.script_for_step(plan, 0, {}, "no code")[0], "none")

    def test_a_piece_that_is_not_joined_still_gets_its_build_called(self):
        # Before Oct 30 a piece with no main guard ran "alone" as a script that only defined functions: its build
        # never ran and the untouched factory scene passed strict (Gemma 4: 7 of its 29 W2-W4 passes).
        plan = F.BLENDER_PLAN
        unguarded = F.S2.replace('\n\nif __name__ == "__main__":\n    build_s2({"scene": bpy.context.scene, '
                                 '"collection": bpy.context.scene.collection, "objects": {}})', "")
        self.assertNotIn("__main__", unguarded)
        kind, script, notes = br.script_for_step(plan, 1, {}, unguarded)
        self.assertEqual(kind, "alone")
        self.assertTrue(script.rstrip().endswith("build_s2(ctx)"), script[-300:])
        self.assertTrue(any("build_s2(ctx) called as joining calls it (nothing in the script calls it)" in n
                            for n in notes), notes)
        ast.parse(script)
        old = br.script_for_step(plan, 1, {}, unguarded, call_build=False)
        self.assertEqual(old[0], "alone")
        self.assertNotIn("\nbuild_s2(ctx)", old[1])  # how it ran before: nothing called it
        # a piece whose guard calls its build already runs it: left as it is
        no_settings = F.S2.replace('SETTINGS_s2 = {"top_size": 0.6, "height": 0.55, "leg": 0.04}',
                                   'S = {"top_size": 0.6, "height": 0.55, "leg": 0.04}').replace("s = SETTINGS_s2", "s = S")
        kind, script, notes = br.script_for_step(plan, 1, {}, no_settings)
        self.assertEqual(kind, "alone")
        self.assertIn('if __name__ == "__main__":\n    build_s2({', script)
        self.assertFalse(any("called as joining" in n for n in notes), notes)
        # after its dependencies: its own guard would give build_s3 an empty ctx, so it gets theirs (the joined
        # dependencies' guard leaves ctx at module level), and the guard is blanked
        s3_no_settings = F.S3.replace("SETTINGS_s3 = {", "_s3_settings = {").replace("s = SETTINGS_s3", "s = _s3_settings")
        self.assertNotIn("SETTINGS_s3", s3_no_settings)
        kind, script, notes = br.script_for_step(plan, 2, {"s2": F.S2}, s3_no_settings)
        self.assertEqual(kind, "after_deps")
        own = script.split("# ---- the reply's own script ----")[1]
        self.assertNotIn("__main__", own)
        self.assertIn('ctx = _wm_deps_ctx if isinstance(globals().get("_wm_deps_ctx"), dict) and isinstance('
                      '_wm_deps_ctx.get("objects"), dict) and "collection" in _wm_deps_ctx else {', own)
        self.assertIn('_wm_deps_ctx = globals().get("ctx")', script.split("# ---- the reply's own script ----")[0])
        self.assertTrue(own.rstrip().endswith("build_s3(ctx)"))
        self.assertTrue(any("with the dependencies' ctx" in n for n in notes), notes)
        ast.parse(script)
        # a today's-style script (no build function) runs as it is, alone and after its dependencies
        today = mock_ollama.today_script("lamp")
        self.assertEqual(br.script_for_step(plan, 0, {}, today)[1], br.reply_script(today))
        self.assertTrue(br.script_for_step(plan, 2, {"s2": F.S2}, today)[1].rstrip().endswith(
            br.reply_script(today).rstrip()))
        # top-level code that calls the build itself (through main()) isn't called twice
        calls_main = unguarded.replace("    ctx[\"objects\"][\"table\"] = top\n",
                                       "    ctx[\"objects\"][\"table\"] = top\n\n\ndef main():\n    build_s2({\"scene\": "
                                       "bpy.context.scene, \"collection\": bpy.context.scene.collection, \"objects\": {}})"
                                       "\n\n\nmain()\n")
        self.assertEqual(br.with_build_call(br.reply_script(calls_main), "s2"), (br.reply_script(calls_main), []))
        self.assertEqual(br.with_build_call("def broken(:\n", "s1"), ("def broken(:\n", []))

    def test_what_counts_as_the_script_running_its_build(self):
        # The review's edge cases (Oct 30): a build the script reaches some other way isn't called a second time
        # (that builds everything twice, .001 names); one that never runs is.
        body = "import bpy\n\n\ndef build_s1(ctx):\n    ctx['objects']['x'] = bpy.data.objects.new('chimera_x', None)\n"
        fresh = "{'scene': bpy.context.scene, 'collection': bpy.context.scene.collection, 'objects': {}}"
        runs_it = {
            "a method": body + f"\n\nclass R:\n    def go(self):\n        build_s1({fresh})\n\n\nR().go()\n",
            "globals()": body + f"\n\nglobals()['build_s1']({fresh})\n",
            "a loop over it": body + f"\n\nfor f in (build_s1,):\n    f({fresh})\n",
            "a decorator": "import bpy\n\n\ndef run(f):\n    f({'scene': bpy.context.scene, 'objects': {}})\n    return f\n\n\n"
                           "@run\ndef build_s1(ctx):\n    pass\n",
            "its guard": body + f"\n\nif __name__ == '__main__':\n    build_s1({fresh})\n",
            # a handler can fire under -b (frame_set, view_layer.update: the final check's run in real Blender)
            "a handler": body + "\n\nbpy.app.handlers.frame_change_post.append(lambda s, d: build_s1({}))\n",
            "a list of its own": body + f"\n\nhandlers = []\nhandlers.append(build_s1)\nfor h in handlers:\n    h({fresh})\n",
        }
        for what, src in runs_it.items():
            with self.subTest(what):
                self.assertEqual(br.with_build_call(src, "s1"), (src, []))
        never = {
            "a timer": body + "\n\nbpy.app.timers.register(lambda: build_s1({}))\n",
            "a timer, imported": body.replace("import bpy", "import bpy\nfrom bpy.app import timers") +
                                 "\n\ntimers.register(lambda: build_s1({}))\n",
            "an unused function": body + f"\n\ndef main():\n    build_s1({fresh})\n",
        }
        for what, src in never.items():
            with self.subTest(what):
                out, called = br.with_build_call(src, "s1")
                self.assertEqual(called, ["build_s1"])
                self.assertTrue(out.rstrip().endswith("build_s1(ctx)"))
        # several builds and none is this step's: each is called, in order, as joining calls every piece's
        two = body + "\n\ndef build_s2(ctx):\n    pass\n"
        out, called = br.with_build_call(two, "s3")
        self.assertEqual(called, ["build_s1", "build_s2"])
        self.assertTrue(out.rstrip().endswith("build_s1(ctx)\nbuild_s2(ctx)"))
        self.assertEqual(br.with_build_call(two, "s2")[1], ["build_s2"])
        twice = body + "\n\ndef build_s1(ctx):\n    pass\n"  # defined twice: called once
        self.assertEqual(br.with_build_call(twice, "s2")[1], ["build_s1"])
        # one of them already runs: the script wires them itself
        wired = two + f"\n\nbuild_s1({fresh})\n"
        self.assertEqual(br.with_build_call(wired, "s3"), (wired, []))
        # after the dependencies, the reply's own module-level ctx can't stand in for theirs
        out, _ = br.with_build_call(body + "\nctx = bpy.context\n", "s1", after_deps=True, ctx_name=br.DEPS_CTX)
        self.assertIn("ctx = _wm_deps_ctx if", out)

    def test_a_script_that_only_defines_things_has_nothing_to_run(self):
        # qwen3:8b, w3-13 under today's prompt: the reply's script defined a helper and never called it, and the
        # untouched scene passed strict and counted as repaired
        helper = block("\n".join([MARK, "import bpy", "", "", "def make_ring(radius=1.0):",
                                   "    mesh = bpy.data.meshes.new('chimera_ring')", "    obj = bpy.data.objects.new('chimera_ring', mesh)",
                                   "    bpy.context.scene.collection.objects.link(obj)", "    obj.scale = (radius, radius, 1)",
                                   "    return obj", "", "", "RADIUS = 2.0"]))
        kind, script, notes = br.script_for_step(F.BLENDER_PLAN, 0, {}, helper)
        self.assertEqual((kind, script), ("none", ""))
        self.assertTrue(any("only defines things" in n for n in notes), notes)
        self.assertEqual(br.script_for_step(F.BLENDER_PLAN, 0, {}, helper, call_build=False)[0], "alone")
        self.assertEqual(br.script_for_step(F.BLENDER_PLAN, 0, {}, helper.replace("RADIUS = 2.0", "make_ring(2.0)"))[0],
                         "alone")
        self.assertFalse(br.inert(ast.parse("import bpy\nx = bpy.data.objects.new('a', None)\n")))
        self.assertFalse(br.inert(ast.parse("import bpy\n\n@bpy.app.handlers.persistent\ndef f(s):\n    pass\n")))
        self.assertTrue(br.inert(ast.parse('"""doc"""\nimport bpy\nA = {"a": 1}\na, b = 1, 2\n\n\nclass K:\n    pass\n')))
        # a settings-only script does something (the review's gpt-oss w2-08, qwen3.8:27b w2-16)
        self.assertFalse(br.inert(ast.parse("import bpy\nbpy.context.scene.render.engine = 'CYCLES'\n")))
        self.assertTrue(br.inert(ast.parse("import bpy\nS = bpy.context.scene\n")))  # a name bound, nothing done
        # a lambda's body and a guarded import don't run anything; a class body does
        self.assertTrue(br.inert(ast.parse("import bpy\nmake = lambda: bpy.ops.mesh.primitive_cube_add()\nN = 3\n")))
        self.assertTrue(br.inert(ast.parse("try:\n    import numpy as np\nexcept ImportError:\n    np = None\n")))
        self.assertFalse(br.inert(ast.parse("import bpy\n\n\nclass K:\n    o = bpy.data.objects.new('k', None)\n")))
        self.assertFalse(br.inert(ast.parse("def f(x=print('hi')):\n    pass\n")))
        self.assertFalse(br.inert(ast.parse("import bpy\nd = {}\nd['k'] = 1\n")))

    def test_dependencies_that_do_not_join_share_one_ctx(self):
        # w4l-04 (Oct 30 review): contract-style dependencies that don't join ran through their own guards, each on
        # an empty ctx, and the reply's build got an empty one too, while the note said it had theirs
        s2_broken = F.S2.replace("```handoff", "```handoff\nprovides: x\nuses: none\nassumed: none\n```\n\n```handoff")
        kind, script, notes = br.script_for_step(F.BLENDER_PLAN, 2, {"s2": s2_broken}, F.S3.replace(
            "SETTINGS_s3 = {", "_s3_settings = {").replace("s = SETTINGS_s3", "s = _s3_settings"))
        self.assertEqual(kind, "after_deps")
        deps, own = script.split("# ---- the reply's own script ----")
        self.assertNotIn("__main__", deps)  # the dependency's guard left out, its build called on the shared ctx
        self.assertIn('ctx = _wm_deps_ctx if isinstance(globals().get("_wm_deps_ctx"), dict) and', deps)
        self.assertIn("\nbuild_s2(ctx)\n_wm_deps_ctx = ctx\n", deps)
        self.assertIn("s2's build_s2(ctx) called on the dependencies' shared ctx", notes)
        self.assertTrue(own.rstrip().endswith("build_s3(ctx)"))
        self.assertTrue(any("with the dependencies' ctx" in n for n in notes), notes)
        # a dependency that rebinds ctx itself doesn't lose what the others registered (the final check's case)
        plan3 = copy.deepcopy(F.BLENDER_PLAN)
        plan3["steps"][2]["depends_on"] = ["s1", "s2"]
        s2_rebinds = s2_broken.replace("\n\nif __name__", "\n\nctx = bpy.context\n\nif __name__")
        kind, script, notes = br.script_for_step(plan3, 2, {"s1": F.S1.replace("```handoff", "```handoff\nprovides: y\n"
                                                                                "uses: none\nassumed: none\n```\n\n```handoff"),
                                                             "s2": s2_rebinds}, F.S3.replace("SETTINGS_s3 = {", "_s3 = {")
                                                 .replace("s = SETTINGS_s3", "s = _s3"))
        self.assertEqual(kind, "after_deps")
        deps = script.split("# ---- the reply's own script ----")[0]
        self.assertEqual(deps.count("_wm_deps_ctx = ctx\n"), 2)
        self.assertLess(deps.index("ctx = bpy.context"), deps.rindex("ctx = _wm_deps_ctx if"))
        # today's-format dependencies leave no ctx: the reply runs as it would alone, its guard kept
        today = mock_ollama.today_script("table")
        kind, script, notes = br.script_for_step(F.BLENDER_PLAN, 2, {"s2": today}, F.S3.replace(
            "SETTINGS_s3 = {", "_s3_settings = {").replace("s = SETTINGS_s3", "s = _s3_settings"))
        self.assertEqual(kind, "after_deps")
        self.assertNotIn(br.DEPS_CTX, script)
        self.assertIn('if __name__ == "__main__":\n    build_s3({', script)
        self.assertFalse(any("called as joining" in n for n in notes), notes)

    def test_after_deps_skips_the_dependencies_render(self):
        # Chimera's check stops at the first render: the joined dependency's _chimera_output render (s1's
        # SETTINGS_s1["output"]) ran before the reply's own script, so a crashing reply passed. It's skipped now.
        kind, script, notes = br.script_for_step(RENDER_PLAN, 1, {"s1": F.S1}, CRASHING_TODAY_REPLY)
        self.assertEqual(kind, "after_deps")
        deps, own = script.split("# ---- the reply's own script ----")
        self.assertIn("def _chimera_output", deps)
        self.assertIn("_chimera_output([SETTINGS_s1])", deps)  # the save still happens
        self.assertNotIn("bpy.ops.render.render(", deps)
        self.assertIn("mesh.use_auto_smooth = True", own)
        self.assertTrue(any("1 render, quit or exit call(s) skipped" in n for n in notes), notes)
        ast.parse(script)
        # a plain dependency script (today's format): its own render and exit are skipped the same way
        plain = block("\n".join([MARK, "import bpy, sys"] + [f"x{i} = {i}" for i in range(6)] +
                                 ["bpy.context.scene.render.filepath = '//p.png'", "bpy.ops.render.render(write_still=True)",
                                  "sys.exit(0)"]))
        kind, script, notes = br.script_for_step(RENDER_PLAN, 1, {"s1": plain}, CRASHING_TODAY_REPLY)
        self.assertEqual(kind, "after_deps")
        deps = script.split("# ---- the reply's own script ----")[0]
        self.assertNotIn("render.render(", deps)
        self.assertNotIn("sys.exit(", deps)
        self.assertIn("render.filepath", deps)
        self.assertTrue(any("2 render, quit or exit call(s) skipped" in n for n in notes), notes)

    def test_skip_run_enders(self):
        src = ("import bpy, os, sys\n"
               "name = 'café'; bpy.ops.render.render(\n    write_still=True)\n"
               "def f():\n    sys.exit(bpy.ops.render.render(animation=True))\n"
               "if bpy.ops.render.render() == {'FINISHED'}:\n    print('rendered')\n"
               "bpy.ops.wm.quit_blender()\nquit()\nos._exit(1)\nbpy.ops.wm.save_as_mainfile(filepath='x.blend')\n")
        out, n = br.skip_run_enders(src)
        self.assertEqual(n, 6)  # the nested render inside sys.exit counts once
        ast.parse(out)
        # an operator call becomes its own return value, an exit call None
        self.assertIn("name = 'café'; {'FINISHED'}\n", out)
        self.assertIn("    None\n", out)
        self.assertIn("if {'FINISHED'} == {'FINISHED'}:", out)
        self.assertIn("\n{'FINISHED'}\nNone\nNone\n", out)  # quit_blender, quit(), os._exit
        self.assertIn("save_as_mainfile", out)  # a save doesn't end the run: kept
        for gone in ("render.render", "quit_blender", "quit()", "_exit", "sys.exit"):
            self.assertNotIn(gone, out)
        self.assertEqual(br.skip_run_enders("def broken(:\n"), ("def broken(:\n", 0))
        self.assertEqual(br.skip_run_enders("print(1)\n"), ("print(1)\n", 0))

    def test_skip_run_enders_keeps_checks_on_the_render_working(self):
        # The verifier's cases: a dependency that checks its render's result must carry on after the skipped render
        src = ("import bpy\n"
               "r = bpy.ops.render.render(write_still=True)\n"
               "assert r == {'FINISHED'}\n"
               "if bpy.ops.render.render(write_still=True) != {'FINISHED'}:\n    raise RuntimeError('render failed')\n"
               "print('after the render')\n")
        out, n = br.skip_run_enders(src)
        self.assertEqual(n, 2)
        ns = {}
        with contextlib.redirect_stdout(io.StringIO()) as printed:  # runs to the end: no AssertionError
            exec(compile(out.replace("import bpy\n", ""), "dep.py", "exec"), ns)
        self.assertEqual(printed.getvalue(), "after the render\n")
        self.assertEqual(ns["r"], {"FINISHED"})
        # raise SystemExit, bare or called, with or without from, becomes pass
        out, n = br.skip_run_enders("import bpy\nx = 1; raise SystemExit(0)\nif x:\n    raise SystemExit\n"
                                    "try:\n    pass\nexcept Exception as e:\n    raise SystemExit('bye') from e\n"
                                    "raise SystemExit(\n    bpy.ops.render.render())\nprint('end')\n")
        self.assertEqual(n, 4)  # the render inside the last raise counts once, with it
        ast.parse(out)
        self.assertNotIn("SystemExit", out)
        self.assertIn("x = 1; pass\n", out)
        self.assertIn("if x:\n    pass\n", out)
        self.assertIn("\npass\nprint('end')", out)
        self.assertEqual(br.skip_run_enders("raise ValueError('x')\n"), ("raise ValueError('x')\n", 0))
        # a render through a name imported from bpy.ops
        out, n = br.skip_run_enders("from bpy.ops import render\nfrom bpy.ops import wm as W\nimport bpy.ops as O\n"
                                    "render.render(write_still=True)\nW.quit_blender()\nO.render.opengl()\n"
                                    "render.filepath = 'x'\n")
        self.assertEqual(n, 3)
        self.assertEqual(out.count("{'FINISHED'}"), 3)
        self.assertIn("render.filepath = 'x'", out)

    def test_probe_script_and_counted_strict(self):
        s = br.probe_script("import bpy\nprint('hi')\n", "/run/scene_probe.py")
        ast.parse(s)
        self.assertLess(s.index("print('hi')"), s.index("_chimera_probe(globals())"))
        self.assertLess(s.index("_chimera_probe(globals())"), s.index("exec(compile(open('/run/scene_probe.py')"))
        self.assertIn("_budget=%d" % br.TOOLS_PROBE_BUDGET, s)
        out = "\n".join(["hello", "Blender 5.2.2 LTS (hash d13f752e3b9c built 2026-09-15 01:49:19)",
                         'CHIMERA_PROBE {"x": "Error: in a name"}', 'chimera-probe: {"objects": []}',
                         "wm-probe: probe failed: KeyError: 'x'", "Blender quit"])
        self.assertEqual(br.own_output(out), "hello\nBlender 5.2.2 LTS (hash d13f752e3b9c built 2026-09-15 01:49:19)\nBlender quit")
        self.assertEqual(br.blender_version(out), "5.2.2")
        self.assertEqual(br.blender_version("Blender 5.0.1 (hash a3db93c5b259 built 2025-12-16 01:51:40)"), "5.0.1")
        self.assertIsNone(br.blender_version("print Blender 9.9.9 here"))
        ok = {"strict": True}
        self.assertTrue(br.counted_strict(ok, {"strict_full": True, "version_ok": True}))
        self.assertTrue(br.counted_strict(ok, {"strict_full": True, "version_ok": None}))
        self.assertFalse(br.counted_strict(ok, {"strict_full": False, "version_ok": True}))  # an Error: line before the tail
        self.assertFalse(br.counted_strict(ok, {"strict_full": True, "version_ok": False}))  # ran in another Blender
        self.assertFalse(br.counted_strict({"strict": False}, {"strict_full": True}))
        self.assertFalse(br.counted_strict(ok, None))

    def test_sandbox_profile_and_render_stop(self):
        prof = br.sandbox_profile("/private/tmp/run", "/Applications/Blender 3.app/Contents/MacOS/Blender")
        for line in ("(deny network*)", '(allow file-write* (subpath "/private/tmp/run")', "(deny process-fork)",
                     '(subpath "/Applications/Blender 3.app")', '(deny file-read* (subpath "/Users")'):
            self.assertIn(line, prof)
        ast.parse(br.stop_at_render("/private/tmp/run/scene_probe.py"))
        self.assertEqual(br.parse_probe('x\nCHIMERA_PROBE {"a": 1}\nCHIMERA_PROBE {"a": 2}\n'), {"a": 2})
        self.assertIsNone(br.parse_probe("CHIMERA_PROBE {cut"))


class ScoreHelperTests(unittest.TestCase):
    def test_word_groups_patterns_and_provides(self):
        self.assertEqual(score.groups_hit("The Camera", [["camera", "cam"], ["flame"]]), [(["camera", "cam"], True), (["flame"], False)])
        from contract.validate import validate_piece
        p = validate_piece(F.S1, "blender", sid="s1")
        out = score.expect_checks(F.S1, p, {"must_match": ["build_s1"], "must_not_match": [r"bpy\.ops\.render"],
                                            "assumed_mentions": [["z = 0", "floor"]]})
        self.assertEqual({k: v["ok"] for k, v in out.items()}, {"must_match": True, "must_not_match": True, "assumed_mentions": True})
        self.assertEqual(score.provided_names('chimera_floor as ctx["objects"]["floor"]; material chimera_floor_mat'),
                         ["chimera_floor", "floor", "chimera_floor_mat"])
        pr = score.provides_probe(p.handoff, {"names": ["chimera_floor"], "ctx_keys": ["floor"]})
        self.assertEqual(pr["missing"], ["chimera_floor_mat"])
        self.assertIsNone(score.provides_probe(p.handoff, {}))
        self.assertEqual(score.changed_lines("a\nb\nc", "a\nB\nc"), 2)  # the eval's convention: removed plus added
        self.assertEqual(score.changed_lines("a\nb", "a\nb\nc"), 1)
        # each changed line once: a replaced line is one line, a 2-line hunk rewritten as 3 is 3
        self.assertEqual(score.lines_changed("a\nb\nc", "a\nB\nc"), 1)
        self.assertEqual(score.lines_changed("a\nb", "a\nb\nc"), 1)
        self.assertEqual(score.lines_changed("a\nb\nc\nd", "a\nB\nC\nX\nd"), 3)
        self.assertEqual(score.lines_changed("a\nb\nc", "a\nc"), 1)
        self.assertEqual(score.lines_changed("a\nb", "a\nb"), 0)


def _rec(mode="blender", run="joined", check=None, probe=None, runaway=False, part="w2", **blender):
    """A raw.jsonl record as step_eval writes it, built by hand (TEST FIXTURE)."""
    b = {"run": run, "notes": [], "assertions_n": 0}
    b.update(blender)
    if check is not None:
        b["check"], b["probe"] = check, probe
    sc = {"contract": {"contract_ok": True, "ok": True, "errors": [], "warns": []}, "runaway": runaway,
          "cut_off": False, "expect": {}}
    if mode == "blender":
        sc["blender"] = b
    return {"id": "c", "part": part, "mode": mode, "sample": 0, "error": None, "stats": {"eval_count": 10},
            "score": sc}


def _ck(strict=True, outcome="passed"):
    return {v: {"strict": strict, "outcome": outcome} for v in score.VERSIONS}


def _pr(full=True, **extra):
    return {v: dict({"strict_full": full, "version_ok": True}, **extra) for v in score.VERSIONS}


class AggregateTests(unittest.TestCase):
    def test_samples_with_no_script_count_as_fails(self):
        # the review's case: one joined sample with a strict pass in both versions, two with no script (one of them a
        # runaway): the rates are over all three, not over the one Blender ran on
        recs = [_rec(check=_ck(), probe=_pr()), _rec(run="none"), _rec(run="none", runaway=True)]
        a = score.aggregate(recs)["all"]
        self.assertEqual((a["n"], a["blender_n"], a["blender_checked"]), (3, 3, 1))
        self.assertEqual((a["strict_5.2.2"], a["strict_5.0.1"], a["strict_both"]), (33.3, 33.3, 33.3))
        self.assertEqual(a["crash_5.2.2"], 0.0)
        self.assertEqual(a["unchecked"], {"no_script": 1, "runaway": 1})
        self.assertEqual((a["no_script"], a["runaway"], a["runaway_n"], a["cut_off"]), (33.3, 33.3, 1, 0.0))
        self.assertEqual(a["joined"], 33.3)

    def test_counted_strict_needs_the_whole_output_and_no_runaway(self):
        recs = [_rec(check=_ck(), probe=_pr(full=False, bad_lines=["Error: early"])),  # clean tail, Error: before it
                _rec(check=_ck(), probe=_pr(), runaway=True),  # its script passed, but the reply ran away
                _rec(check=_ck(False, "failed"), probe=_pr(False)), _rec(check=_ck(), probe=_pr())]
        a = score.aggregate(recs)["all"]
        self.assertEqual((a["strict_5.2.2"], a["strict_tail_5.2.2"], a["crash_5.2.2"]), (25.0, 50.0, 25.0))
        self.assertEqual([score.verdict(r, "5.2.2") for r in recs], ["not strict", "runaway", "failed", "pass"])
        md = score.render_md({"model": "m", "prompt": "p", "eval_version": "1", "started": "t", "samples": 1,
                              "prose_samples": 1, "reply_cap": 6144}, score.aggregate(recs), recs)
        self.assertIn("the direct run printed Error: early", md)
        self.assertIn("runaway in content: cut at", md)
        self.assertIn("reply cap of 6144 tokens, thinking not counted", md)

    def test_crash_rate_over_checked_samples_and_over_all(self):
        # the verifier's case: a crash, a pass and two samples with no script. Over every sample the crash rate is
        # 25%; over the two Blender checked, 50% (the plan's "definite crashes at most 10%" is this one)
        recs = [_rec(check=_ck(False, "failed"), probe=_pr(False)), _rec(check=_ck(), probe=_pr()),
                _rec(run="none"), _rec(run="none")]
        a = score.aggregate(recs)["all"]
        self.assertEqual((a["blender_n"], a["blender_checked"]), (4, 2))
        self.assertEqual((a["crash_5.2.2"], a["crash_checked_5.2.2"], a["crash_checked_5.0.1"]), (25.0, 50.0, 50.0))
        md = score.render_md({"model": "m", "prompt": "p", "eval_version": "1", "started": "t", "samples": 1,
                              "prose_samples": 1}, score.aggregate(recs), recs)
        self.assertIn("crash 5.2.2 (checked) | crash 5.2.2 (all)", md)
        self.assertIn("| 50% | 25% |", md)
        self.assertIn("over the 2 samples Blender checked", md)
        self.assertNotIn("crash-free", score.__doc__)

    def test_form_ok_next_to_contract_kept(self):
        near = _rec()
        near["score"]["contract"].update(form_ok=False, warns=["handoff_unfenced"])
        exact = _rec()
        exact["score"]["contract"]["form_ok"] = True
        a = score.aggregate([near, exact])["all"]
        self.assertEqual((a["contract_ok"], a["form_ok"]), (100.0, 50.0))
        self.assertIsNone(score.aggregate([_rec()])["all"]["form_ok"])  # a record from before form_ok was kept
        md = score.render_md({"model": "m", "prompt": "p", "eval_version": "1", "started": "t", "samples": 1,
                              "prose_samples": 1}, score.aggregate([near, exact]), [near, exact])
        self.assertIn("| contract kept | form ok |", md)
        self.assertIn("ok, near miss", md)
        # score_step records it from the validator: a near-miss handoff keeps the contract but not the form
        from contract.validate import validate_piece
        unfenced = F.S1.replace("```handoff\n", "handoff\n").rsplit("```", 1)[0].rstrip() + "\n"
        p = validate_piece(unfenced, "blender", sid="s1")
        self.assertTrue(p.contract_ok and not p.form_ok, [i.code for i in p.issues])
        case = types.SimpleNamespace(mode="blender", sid="s1", deps=[], lone=False, step=F.BLENDER_PLAN["steps"][0],
                                     expect={}, repair=None, plan=F.BLENDER_PLAN, index=0, outputs={}, goal="")
        sc = score.score_step(case, "contract", unfenced, {"stats": {"done_reason": "stop"}}, blender=None)
        self.assertEqual((sc["contract"]["contract_ok"], sc["contract"]["form_ok"]), (True, False))
        sc = score.score_step(case, "contract", F.S1, {"stats": {"done_reason": "stop"}}, blender=None)
        self.assertEqual((sc["contract"]["contract_ok"], sc["contract"]["form_ok"]), (True, True))

    def test_runaways_split_by_where_they_were_cut(self):
        th, co = _rec(run="none", runaway=True), _rec(run="none", runaway=True)
        th["score"]["runaway_in"], co["score"]["runaway_in"] = "thinking", "content"
        a = score.aggregate([th, co, _rec(check=_ck(), probe=_pr())])["all"]
        self.assertEqual((a["runaway_n"], a["runaway_thinking_n"], a["runaway_content_n"]), (2, 1, 1))
        self.assertEqual(a["strict_5.2.2"], 33.3)  # both count as fails
        md = score.render_md({"model": "m", "prompt": "p", "eval_version": "1", "started": "t", "samples": 1,
                              "prose_samples": 1, "reply_cap": 6144, "max_reply_tokens": 16384},
                             score.aggregate([th, co]), [th, co])
        self.assertIn("100% (1 thinking, 1 content)", md)
        self.assertIn("runaway in thinking: cut at", md)
        self.assertIn("16384 tokens with thinking", md)

    def test_no_blender_gives_no_rates_and_prose_has_none(self):
        recs = [_rec(run="alone", not_run=True), _rec(run="none"), _rec(mode="section")]
        a = score.aggregate(recs)["all"]
        self.assertIsNone(a.get("strict_5.2.2"))
        self.assertEqual((a["blender_not_run"], a["unchecked"]["no_script"]), (1, 1))
        self.assertNotIn("blender_n", score.aggregate([_rec(mode="section")])["all"])

    def test_assertions_count_samples_with_no_scene(self):
        ok = _rec(check=_ck(), probe=_pr(assert_fails=[]), assertions_n=2)
        bad = _rec(check=_ck(), probe=_pr(assert_fails=["no camera"]), assertions_n=2)
        none = _rec(run="none", assertions_n=2)
        self.assertEqual(score.aggregate([ok, bad, none])["all"]["assertions_5.2.2"], 33.3)

    def test_repair_not_fixed_without_a_script_or_after_a_runaway(self):
        case = types.SimpleNamespace(case={"crash": {"version": "5.2.2", "crashes_in": ["5.2.2", "5.0.1"]},
                                           "fix": {"changed_lines": 2}},
                                     repair={"piece": block(BPY6)})
        fixed_reply = block(BPY6.replace("x3 = 3", "x3 = 33"))
        brec = {"check": _ck(), "probe": _pr(), "strict": {v: True for v in score.VERSIONS}}
        r = score.repair_score(case, fixed_reply, brec)
        self.assertEqual((r["fixed"], r["fixed_all"], r["changed"], r["lines_changed"]), (True, True, 2, 1))
        self.assertEqual(r["changed_share"], round(1 / 8, 3))  # one line of eight, not two
        self.assertEqual(score.repair_score(case, fixed_reply, brec, runaway=True)["fixed"], False)
        r = score.repair_score(case, "no code at all", {"run": "none", "notes": []})
        self.assertEqual((r["fixed"], r["fixed_all"], r["changed_share"]), (False, False, None))
        self.assertNotIn("fixed", score.repair_score(case, fixed_reply, {"run": "alone", "not_run": True}))


def _real():
    chimera = os.environ.get("CHIMERA_BIN", "")
    ok = chimera and os.path.exists(chimera) and all(not blenders.check_path(p) for p in blenders.VERSIONS.values())
    return chimera if ok else None


@unittest.skipUnless(_real(), "needs CHIMERA_BIN and Blender 5.2.2 and 5.0.1")
class RealBlenderTests(unittest.TestCase):
    """About 5 s: the fixture plan joined, through Chimera's check and the sandboxed probe in both versions."""

    @classmethod
    def setUpClass(cls):
        cls.b = br.Blender(_real(), work=os.environ.get("WM_SCRATCH"))

    def test_joined_fixture_checks_and_probes(self):
        kind, script, _ = br.script_for_step(F.BLENDER_PLAN, 2, {"s2": F.S2}, F.S3)
        ck = self.b.check(script)
        self.assertEqual({v: r["strict"] for v, r in ck.items()}, {"5.2.2": True, "5.0.1": True})
        for r in ck.values():
            self.assertNotIn("chimera-probe:", r["output_tail"])  # no probe in the check: its tail is the script's own
        pr = self.b.probe(script)
        for v, r in pr.items():
            self.assertTrue(r["strict_full"], (v, r["output_tail"]))
            self.assertTrue(r["sandboxed"])
            self.assertEqual((r["blender"], r["version_ok"]), (v, True))
            self.assertIn("chimera_table", {o["name"] for o in r["probe"]["objects"]})
            self.assertIn("table", r["ctx_keys"])  # the tools probe, out of band, sees ctx at module level
            self.assertIn("chimera_table", r["names"])
            self.assertTrue(br.counted_strict(ck[v], r))

    def test_pieces_that_are_not_joined_really_build(self):
        # The build that's now called runs for real: alone, and after the dependency with its ctx (no stand-in)
        unguarded = F.S2.split('\n\nif __name__ == "__main__":')[0] + "\n```\n"
        kind, script, _ = br.script_for_step(F.BLENDER_PLAN, 1, {}, unguarded)
        self.assertEqual(kind, "alone")
        for v, r in self.b.probe(script).items():
            self.assertTrue(r["strict_full"], (v, r["output_tail"]))
            self.assertIn("chimera_table", r["names"])
            self.assertIn("table", r["ctx_keys"])
        broken_s2 = F.S2_BROKEN.split('\n\nif __name__ == "__main__":')[0] + "\n```\n"
        ck = self.b.check(br.script_for_step(F.BLENDER_PLAN, 1, {}, broken_s2)[1])
        self.assertEqual({v: r["outcome"] for v, r in ck.items()}, {"5.2.2": "failed", "5.0.1": "failed"})
        s3 = F.S3.replace("SETTINGS_s3 = {", "_s3_settings = {").replace("s = SETTINGS_s3", "s = _s3_settings")
        kind, script, _ = br.script_for_step(F.BLENDER_PLAN, 2, {"s2": F.S2}, s3)
        self.assertEqual(kind, "after_deps")
        for v, r in self.b.probe(script).items():
            self.assertTrue(r["strict_full"], (v, r["output_tail"]))
            self.assertFalse(r["stand_in"], r["output_tail"])  # it found s2's table in the dependencies' ctx
            self.assertEqual(sorted(r["ctx_keys"]), ["lamp", "table"])
        # two dependencies that don't join, one rebinding ctx itself: the reply still finds both (real Blender)
        plan3 = copy.deepcopy(F.BLENDER_PLAN)
        plan3["steps"][2]["depends_on"] = ["s1", "s2"]
        two = "```handoff\nprovides: y\nuses: none\nassumed: none\n```\n\n```handoff"
        s1_two = F.S1.replace("```handoff", two)
        s2_rebinds = F.S2.replace("```handoff", two).replace("\n\nif __name__", "\n\nctx = bpy.context\n\nif __name__")
        kind, script, _ = br.script_for_step(plan3, 2, {"s1": s1_two, "s2": s2_rebinds}, s3)
        self.assertEqual(kind, "after_deps")
        for v, r in self.b.probe(script).items():
            self.assertTrue(r["strict_full"], (v, r["output_tail"]))
            self.assertFalse(r["stand_in"], r["output_tail"])
            self.assertTrue({"table", "lamp"} <= set(r["ctx_keys"]), r["ctx_keys"])
            self.assertIn("chimera_floor", r["names"])
        # a dependency that doesn't join (two handoff blocks) still builds on the shared ctx the reply gets
        s2_two = F.S2.replace("```handoff", "```handoff\nprovides: x\nuses: none\nassumed: none\n```\n\n```handoff")
        kind, script, _ = br.script_for_step(F.BLENDER_PLAN, 2, {"s2": s2_two}, s3)
        self.assertEqual(kind, "after_deps")
        for v, r in self.b.probe(script).items():
            self.assertTrue(r["strict_full"], (v, r["output_tail"]))
            self.assertFalse(r["stand_in"], r["output_tail"])
            self.assertEqual(sorted(r["ctx_keys"]), ["lamp", "table"])

    def test_error_lines_stay_visible(self):
        # An "Error:" line followed by about 500 characters of output, in a scene whose tools-probe line is about
        # 1,100 characters long: with the probe appended to the check, the check's 1,500-character tail held only
        # the probe and the last ~400 characters, so it passed strictly. Out of band, the check itself catches it.
        many = ("import bpy\nfor i in range(80):\n    o = bpy.data.objects.new('chimera_probe_filler_%03d' % i, None)\n"
                "    bpy.context.scene.collection.objects.link(o)\n")
        near = many + "print('Error: simulated report from an operator')\n" + "print('ordinary line ' + 'x' * 40)\n" * 10
        ck, pr = self.b.check(near), self.b.probe(near)
        self.assertEqual({v: r["strict"] for v, r in ck.items()}, {"5.2.2": False, "5.0.1": False})
        self.assertTrue(all(not r["strict_full"] for r in pr.values()))
        # Further back than the check's tail: only the direct run's whole output sees it, and it counts
        far = many + "print('Error: simulated report from an operator')\n" + "print('ordinary line ' + 'x' * 60)\n" * 40
        ck, pr = self.b.check(far), self.b.probe(far)
        for v in ck:
            self.assertTrue(ck[v]["strict"], ck[v]["output_tail"])
            self.assertFalse(pr[v]["strict_full"])
            self.assertIn("Error: simulated report from an operator", pr[v]["bad_lines"])
            self.assertFalse(br.counted_strict(ck[v], pr[v]))

    def test_a_render_keeps_the_version_and_the_duplicates(self):
        src = (MARK + "\nimport bpy\nfor n in ('chimera_x', 'chimera_x'):\n"
               "    bpy.context.scene.collection.objects.link(bpy.data.objects.new(n, None))\n"
               "bpy.context.scene.render.filepath = '//r.png'\nbpy.ops.render.render(write_still=True)\n")
        for v, r in self.b.probe(src).items():
            self.assertTrue(r["stopped_at_render"])
            self.assertEqual((r["blender"], r["version_ok"]), (v, True))  # from the eval probe: the header is lost
            self.assertEqual(r["dupes"], ["chimera_x.001"])  # the tools probe never runs at a render; the eval's did
            self.assertTrue(r["strict_full"])

    def test_after_deps_reply_that_crashes_fails(self):
        kind, script, _ = br.script_for_step(RENDER_PLAN, 1, {"s1": F.S1}, CRASHING_TODAY_REPLY)
        self.assertEqual(kind, "after_deps")
        for v, r in self.b.check(script).items():
            self.assertEqual(r["outcome"], "failed", (v, r["summary"]))
            self.assertIn("use_auto_smooth", r["error"] or "")

    def test_after_deps_dependency_that_checks_its_render_passes_a_good_reply(self):
        # Before Oct 30 the skipped render became None, so `assert result == {'FINISHED'}` failed a correct reply
        dep = "The floor.\n\n" + block("\n".join([
            MARK, "import bpy", "bpy.ops.mesh.primitive_plane_add(size=4)", "floor = bpy.context.active_object",
            'floor.name = "chimera_floor"', "bpy.context.scene.render.filepath = '//floor.png'",
            "result = bpy.ops.render.render(write_still=True)", "assert result == {'FINISHED'}, result",
            'print("floor done")']))
        good = CRASHING_TODAY_REPLY.replace("mesh.use_auto_smooth = True", "obj.scale = (0.3, 0.3, 0.02)")
        kind, script, notes = br.script_for_step(RENDER_PLAN, 1, {"s1": dep}, good)
        self.assertEqual(kind, "after_deps")
        self.assertTrue(any("1 render, quit or exit call(s) skipped" in n for n in notes), notes)
        ck, pr = self.b.check(script), self.b.probe(script)
        for v in ck:
            self.assertTrue(br.counted_strict(ck[v], pr[v]), (v, ck[v]["summary"], pr[v]["output_tail"]))

    def test_sandbox_keeps_writes_and_network_out(self):
        self.b.probe_src = "print('probe ran')"
        bad = ("import bpy, os, socket\n"
               "for what, fn in (('write', lambda: open(os.path.expanduser('~/../../wm_probe_escape.txt'), 'w')),\n"
               "                 ('net', lambda: socket.create_connection(('1.1.1.1', 80), timeout=3))):\n"
               "    try:\n        fn()\n        print('OPEN', what)\n"
               "    except OSError as e:\n        print('blocked', what, type(e).__name__)\n")
        r = self.b._probe_one(bad, blenders.VERSIONS["5.2.2"])
        self.assertIn("blocked net", r["output_tail"])
        self.assertNotIn("OPEN", r["output_tail"])


if __name__ == "__main__":
    unittest.main()

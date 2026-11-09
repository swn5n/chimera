"""The scene probe's epilogue, run against a fake bpy, and its parser. One class runs real Blender (sandboxed, through
datagen/pysandbox.run_tool) and skips without Blender 5.2.2 and 5.0.1."""
import contextlib
import io
import json
import os
import sys
import types
import unittest

from tests import _paths  # noqa: F401
from tests import contract_fixtures as F
from contract.join import alone_script, join
from contract.validate import validate_piece
from datagen import pysandbox
from tools import blenders
from tools import scene_probe as sp

# The line the epilogue printed before Nov 4 for test_lists_the_scene_and_ctx's scene, whose ctx has no "values"
# dict: a ctx made by an old guard must still print exactly this (measured with the old epilogue).
OLD_LINE = ('chimera-probe: {"v":1,"blender":"5.2.2","scene":"Scene","engine":"BLENDER_EEVEE","world":"World",'
            '"objects":[["chimera_table","MESH","chimera_table_mesh",1],["chimera_loose","EMPTY",null,0],'
            '["Camera","CAMERA","Camera",1]],"materials":["Material"],"collections":["Collection"],'
            '"ctx":{"name":"ctx","keys":["table"],"collection":"chimera_project"}}')


class Named:
    def __init__(self, name, **kw):
        self.name = name
        self.bl_rna = object()
        self.__dict__.update(kw)


def fake_bpy(objects, materials=("Material",), collections=("Collection",), in_scene=None, world="World"):
    """Just enough of bpy for the probe: bpy.app.version, bpy.data lists, bpy.context.scene."""
    objs = [Named(n, type=t, data=Named(d) if d else None) for n, t, d in objects]
    scene_objs = [o for o in objs if in_scene is None or o.name in in_scene]
    scene = Named("Scene", objects=scene_objs, render=types.SimpleNamespace(engine="BLENDER_EEVEE"),
                  world=Named(world) if world else None)
    bpy = types.ModuleType("bpy")
    bpy.app = types.SimpleNamespace(version=(5, 2, 2))
    bpy.data = types.SimpleNamespace(objects=objs, materials=[Named(m) for m in materials],
                                     collections=[Named(c) for c in collections])
    bpy.context = types.SimpleNamespace(scene=scene)
    return bpy, scene


def run_probe(bpy, g=None, budget=sp.BUDGET):
    """Run the epilogue as it runs at the end of a script; returns (stdout, the globals)."""
    g = dict(g or {})
    old = sys.modules.get("bpy")
    sys.modules["bpy"] = bpy
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            exec(compile(sp.append("x = 1", budget), "script.py", "exec"), g)  # noqa: S102
    finally:
        if old is None:
            sys.modules.pop("bpy", None)
        else:
            sys.modules["bpy"] = old
    return out.getvalue(), g


class ProbeTests(unittest.TestCase):
    def test_lists_the_scene_and_ctx(self):
        bpy, scene = fake_bpy([("chimera_table", "MESH", "chimera_table_mesh"), ("Camera", "CAMERA", "Camera"),
                               ("chimera_loose", "EMPTY", None)], in_scene={"chimera_table", "Camera"})
        table = bpy.data.objects[0]
        ctx = {"scene": scene, "collection": Named("chimera_project"), "objects": {"table": table}}
        out, g = run_probe(bpy, {"ctx": ctx})
        self.assertEqual(len([l for l in out.splitlines() if l.startswith(sp.PREFIX)]), 1)
        self.assertNotIn("_chimera_probe", g)  # it cleans up after itself
        self.assertEqual(g["x"], 1)
        p = sp.parse(out)
        self.assertEqual(p["blender"], "5.2.2")
        self.assertEqual(p["engine"], "BLENDER_EEVEE")
        self.assertEqual(p["world"], "World")
        objs = {o["name"]: o for o in p["objects"]}
        self.assertEqual(objs["chimera_table"], {"name": "chimera_table", "type": "MESH", "data": "chimera_table_mesh",
                                                 "in_scene": True})
        self.assertFalse(objs["chimera_loose"]["in_scene"])
        self.assertIsNone(objs["chimera_loose"]["data"])
        self.assertEqual(p["ctx"], {"name": "ctx", "keys": ["table"], "collection": "chimera_project"})
        self.assertNotIn("cut", p)

    def test_a_ctx_with_no_values_prints_what_it_printed_before(self):
        bpy, scene = fake_bpy([("chimera_table", "MESH", "chimera_table_mesh"), ("Camera", "CAMERA", "Camera"),
                               ("chimera_loose", "EMPTY", None)], in_scene={"chimera_table", "Camera"})
        reg = {"table": bpy.data.objects[0]}
        for what, extra in (("no values", {}), ("values None", {"values": None}), ("values a list", {"values": ["a"]})):
            with self.subTest(what):
                ctx = dict({"scene": scene, "collection": Named("chimera_project"), "objects": reg}, **extra)
                out, _ = run_probe(bpy, {"ctx": ctx})
                self.assertEqual([l for l in out.splitlines() if l.startswith(sp.PREFIX)], [OLD_LINE])
                self.assertNotIn("values", sp.parse(out)["ctx"])
                self.assertNotIn('ctx["values"]', sp.summary(sp.parse(out)))

    def test_lists_ctx_values_keys(self):
        # ctx["values"] (contract question 1, decided Nov 4): its keys, never its numbers
        bpy, scene = fake_bpy([("chimera_sofa", "MESH", "chimera_sofa")])
        ctx = {"scene": scene, "collection": Named("Collection"), "objects": {"sofa": bpy.data.objects[0]},
               "values": {"sofa_width": 2.2}}
        out, _ = run_probe(bpy, {"ctx": ctx})
        p = sp.parse(out)
        self.assertEqual(p["ctx"]["values"], ["sofa_width"])
        self.assertEqual(p["ctx"]["keys"], ["sofa"])
        self.assertIn('ctx["values"] keys: sofa_width', sp.summary(p))
        self.assertIn('ctx["objects"] keys: sofa; ctx["values"] keys: sofa_width', sp.summary(p))
        ctx["values"] = {"sofa_depth": 0.9173, 7: "x", "b" * 80: 1}  # sorted, as text, long keys cut like names
        out = run_probe(bpy, {"ctx": ctx})[0]
        self.assertEqual(sp.parse(out)["ctx"]["values"], ["7", "b" * 61 + "...", "sofa_depth"])
        self.assertNotIn("0.9173", out)
        ctx["values"] = {}
        p = sp.parse(run_probe(bpy, {"ctx": ctx})[0])
        self.assertEqual(p["ctx"]["values"], [])
        self.assertIn('ctx["values"] keys: none', sp.summary(p))
        # a ctx found by its shape gets its values listed too
        out, _ = run_probe(bpy, {"state": {"scene": scene, "objects": {}, "values": {"seat_height": 0.45}}})
        self.assertEqual(sp.parse(out)["ctx"]["values"], ["seat_height"])

    def test_many_values_are_cut_to_the_budget(self):
        bpy, scene = fake_bpy([("chimera_sofa", "MESH", "chimera_sofa")])
        vals = {"value_number_%03d" % i: i for i in range(400)}
        out, _ = run_probe(bpy, {"ctx": {"scene": scene, "objects": {}, "values": vals}})
        line = [l for l in out.splitlines() if l.startswith(sp.PREFIX)][0]
        self.assertLessEqual(len(line), sp.BUDGET)
        p = sp.parse(out)
        self.assertEqual(p["cut"]["values"], 400 - len(p["ctx"]["values"]))
        self.assertGreater(p["cut"]["values"], 0)
        self.assertEqual([o["name"] for o in p["objects"]], ["chimera_sofa"])  # the short lists are left alone
        self.assertIn("cut: %d values" % p["cut"]["values"], sp.summary(p))

    def test_finds_a_ctx_by_shape(self):
        bpy, scene = fake_bpy([("Cube", "MESH", "Cube")])
        out, _ = run_probe(bpy, {"state": {"scene": scene, "objects": {"cube": bpy.data.objects[0]}}})
        self.assertEqual(sp.parse(out)["ctx"]["name"], "state")
        out, _ = run_probe(bpy, {})
        self.assertNotIn("ctx", sp.parse(out))

    def test_big_scenes_are_cut_to_the_budget(self):
        objs = [("rock_%03d" % i, "MESH", "rock_mesh_%03d" % i) for i in range(500)] + [("chimera_hero", "MESH", "hero")]
        bpy, scene = fake_bpy(objs, materials=["mat_%02d" % i for i in range(80)])
        reg = {"rock_keep": bpy.data.objects[123]}
        out, _ = run_probe(bpy, {"ctx": {"scene": scene, "objects": reg}})
        line = [l for l in out.splitlines() if l.startswith(sp.PREFIX)][0]
        self.assertLessEqual(len(line), sp.BUDGET)
        p = sp.parse(out)
        names = [o["name"] for o in p["objects"]]
        self.assertIn("chimera_hero", names)  # chimera_ names and ctx-registered objects are kept first
        self.assertIn("rock_123", names)
        self.assertEqual(p["cut"]["objects"], 501 - len(names))
        self.assertGreater(p["cut"]["materials"], 0)

    def test_never_breaks_the_script(self):
        bpy = types.ModuleType("bpy")
        bpy.app = types.SimpleNamespace(version=(5, 0, 1))  # no data, no context
        out, g = run_probe(bpy)
        p = sp.parse(out)
        self.assertIn("probe_failed", p)
        self.assertNotIn("Error:", out)  # a strict check must not read the probe's own failure as Blender's
        self.assertNotIn("Traceback", out)

    def test_parse(self):
        self.assertIsNone(sp.parse(""))
        self.assertIsNone(sp.parse("Blender quit\n"))
        self.assertIsNone(sp.parse('…be: {"v":1,"objects":[["a"'))  # cut off by the output's 1,500-character tail
        two = 'chimera-probe: {"v":1,"objects":[]}\nchimera-probe: {"v":1,"objects":[["Cube.001","MESH","Cube",1]],' \
              '"materials":["Material.002"],"collections":[]}\nBlender quit\n'
        p = sp.parse(two)
        self.assertEqual(p["objects"][0]["name"], "Cube.001")  # the last line wins
        self.assertEqual(p["dupes"], ["Cube.001", "Material.002"])
        self.assertEqual(sp.without_probe(two), "Blender quit")

    def test_append_keeps_the_script(self):
        src = "import bpy\nif __name__ == '__main__':\n    print('hi')"
        out = sp.append(src)
        self.assertTrue(out.startswith(src + "\n"))
        compile(out, "script.py", "exec")
        self.assertIn("_budget=500", sp.append(src, 500))

    def test_summary(self):
        p = sp.parse('chimera-probe: ' + json.dumps({"v": 1, "engine": "CYCLES", "world": None,
                                                     "objects": [["chimera_a", "MESH", "m", 0]], "materials": [],
                                                     "collections": [], "ctx": {"name": "ctx", "keys": ["a"]}}))
        s = sp.summary(p)
        self.assertIn("chimera_a (mesh) not in scene", s)
        self.assertIn('ctx["objects"] keys: a', s)
        self.assertIn("no probe", sp.summary(None))


HAVE_BLENDER = all(not blenders.check_path(p) for p in blenders.VERSIONS.values())


@unittest.skipUnless(HAVE_BLENDER and pysandbox.can_sandbox(), "needs Blender 5.2.2, 5.0.1 and sandbox-exec")
class RealBlenderTests(unittest.TestCase):
    """About 10 s: tests/contract_fixtures.py's values pair (s1 hands the sofa's sizes on through ctx["values"], s2
    builds with them) with the epilogue appended, in real Blender, sandboxed as the data generator runs a tool."""

    def probe(self, script, binary):
        r = pysandbox.run_tool({"script.py": sp.append(script)}, binary,
                               ["-b", "--factory-startup", "--python-exit-code", "1", "--python", "script.py"],
                               timeout=180, work=os.environ.get("WM_SCRATCH"))
        self.assertEqual(r["exit"], 0, r["output"][-1500:])
        self.assertTrue(r["sandboxed"])
        return sp.parse(r["output"]), r["output"]

    def test_the_values_pair_lists_its_values_keys(self):
        j = join(F.VALUES_PLAN, F.VALUES_OUTPUTS)
        self.assertFalse(j.fallback, j.reasons)
        s2 = validate_piece(F.VALUES_S2, "blender", sid="s2")
        alone = alone_script(s2)  # s2 with no s1: an empty ctx["values"], so both stand-ins
        for v, binary in blenders.VERSIONS.items():
            with self.subTest(v):
                p, out = self.probe(j.script, binary)
                self.assertEqual(p["blender"], v)
                self.assertEqual(p["ctx"]["values"], ["sofa_depth", "sofa_width"])
                self.assertEqual(p["ctx"]["keys"], ["sofa"])
                self.assertIn("sofa: 2.2 x 0.9", out)
                self.assertNotIn("chimera: stand-in", out)
                self.assertIn('ctx["values"] keys: sofa_depth, sofa_width', sp.summary(p))
                p, out = self.probe(alone, binary)
                self.assertEqual(p["ctx"]["values"], [])
                self.assertEqual(p["ctx"]["keys"], ["sofa"])
                self.assertIn("chimera: stand-in sofa_width", out)
                self.assertIn("sofa: 2.0 x 0.8", out)


if __name__ == "__main__":
    unittest.main()

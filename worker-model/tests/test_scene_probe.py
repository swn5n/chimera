"""The scene probe's epilogue, run against a fake bpy, and its parser."""
import contextlib
import io
import json
import sys
import types
import unittest

from tests import _paths  # noqa: F401
from tools import scene_probe as sp


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


if __name__ == "__main__":
    unittest.main()

"""The lint against two small hand-made dumps (no Blender needed), plus the real dumps when present."""
import json
import os
import shutil
import sys
import tempfile
import unittest

from tests import _paths  # noqa: F401
from tools import blenders, rna_dump, rna_lint


def P(t, **kw):
    return dict({"type": t}, **kw)


def cls(base, props=None, funcs=(), py=()):
    return {"base": base, "props": props or {}, "funcs": list(funcs), "py": list(py)}


def sock(*names):
    return [[n, n, "NodeSocketFloat"] for n in names]


def make_dump(version, extra_mesh_prop=None, raycast=False):
    mesh_props = {"vertices": P("COLLECTION", fixed="MeshVertex")}
    if extra_mesh_prop:
        mesh_props[extra_mesh_prop] = P("BOOLEAN")
    classes = {
        "bpy_struct": cls(None, py=["keyframe_insert", "get", "id_data"]),
        "ID": cls("bpy_struct", {"name": P("STRING"), "rna_type": P("POINTER", fixed="Struct")}, py=["bl_rna"]),
        "Object": cls("ID", {"data": P("POINTER", fixed="ID"), "location": P("FLOAT"), "hide_render": P("BOOLEAN"),
                             "rotation_euler": P("FLOAT"),
                             "modifiers": P("COLLECTION", fixed="Modifier", srna="ObjectModifiers")}),
        "ObjectModifiers": dict(cls("bpy_struct", funcs=["new", "remove"]), fparams={"new": ["name", "type"]}),
        "Mesh": dict(cls("ID", mesh_props, py=["from_pydata", "shade_smooth"]),
                     fparams={"from_pydata": ["vertices", "edges", "faces", "shade_flat"]}),
        "MeshVertex": cls("bpy_struct", {"co": P("FLOAT")}),
        "Light": cls("ID", {"energy": P("FLOAT"), "type": P("ENUM", items=["POINT", "AREA"])}),
        "AreaLight": cls("Light", {"shape": P("ENUM", items=["SQUARE", "DISK"]), "size": P("FLOAT")}),
        "Material": cls("ID", {"node_tree": P("POINTER", fixed="NodeTree")}),
        "Modifier": cls("bpy_struct", {"name": P("STRING"), "type": P("ENUM", items=["BEVEL", "SUBSURF"], ro=True)}),
        "BevelModifier": cls("Modifier", {"width": P("FLOAT"), "segments": P("INT"),
                                          "offset_type": P("ENUM", items=["OFFSET", "WIDTH"])}),
        "SubsurfModifier": cls("Modifier", {"levels": P("INT")}),
        "NodesModifier": cls("Modifier", {"node_group": P("POINTER", fixed="NodeTree"),
                                          "properties": P("POINTER", fixed="NodesModifierProperties", ro=True)}),
        "NodesModifierProperties": cls("bpy_struct", {"rna_type": P("POINTER", fixed="Struct")}),
        "Scene": cls("ID", {"render": P("POINTER", fixed="RenderSettings"),
                            "objects": P("COLLECTION", fixed="Object", srna="SceneObjects")}),
        "SceneObjects": cls("bpy_struct"),
        "RenderSettings": cls("bpy_struct", {"engine": P("ENUM", items=["BLENDER_EEVEE"]),
                                             "resolution_x": P("INT")}),
        "BlendData": cls("bpy_struct", {"objects": P("COLLECTION", fixed="Object", srna="BlendDataObjects"),
                                        "meshes": P("COLLECTION", fixed="Mesh", srna="BlendDataMeshes"),
                                        "lights": P("COLLECTION", fixed="Light", srna="BlendDataLights"),
                                        "materials": P("COLLECTION", fixed="Material", srna="BlendDataMaterials"),
                                        "node_groups": P("COLLECTION", fixed="NodeTree", srna="BlendDataNodeTrees")}),
        "BlendDataObjects": dict(cls("bpy_struct", funcs=["new"]), fparams={"new": ["name", "object_data"]}),
        "BlendDataMeshes": cls("bpy_struct", funcs=["new"]),
        "BlendDataLights": cls("bpy_struct", funcs=["new"]),
        "BlendDataMaterials": cls("bpy_struct", funcs=["new"]),
        "BlendDataNodeTrees": cls("bpy_struct", funcs=["new"]),
        "NodeTree": cls("ID", {"nodes": P("COLLECTION", fixed="Node", srna="Nodes"),
                               "links": P("COLLECTION", fixed="NodeLink", srna="NodeLinks")}),
        "GeometryNodeTree": cls("NodeTree"),
        "Nodes": cls("bpy_struct", funcs=["new", "remove"]),
        "Node": cls("bpy_struct", {"name": P("STRING"), "location": P("FLOAT"),
                                   "inputs": P("COLLECTION", fixed="NodeSocket"),
                                   "outputs": P("COLLECTION", fixed="NodeSocket")}),
        "NodeSocket": cls("bpy_struct", {"name": P("STRING")}),
        "NodeSocketFloat": cls("NodeSocket", {"default_value": P("FLOAT")}),
        "ShaderNodeBsdfPrincipled": cls("Node"),
        "ShaderNodeTexNoise": cls("Node", {"noise_dimensions": P("ENUM", items=["3D", "4D"])}),
        "ShaderNodeGroup": cls("Node", {"node_tree": P("POINTER", fixed="NodeTree")}),
        "GeometryNodeCaptureAttribute": cls("Node", {"capture_items": P("COLLECTION", fixed="NodeSocket")}),
        "Operator": cls("bpy_struct"),
    }
    nodes = {"ShaderNodeTree": {
        "ShaderNodeBsdfPrincipled": {"label": "Principled BSDF", "inputs": sock("Base Color", "Transmission Weight"),
                                     "outputs": sock("BSDF"), "dynamic": False},
        "ShaderNodeTexNoise": {"label": "Noise Texture", "inputs": sock("Vector", "Scale"),
                               "outputs": sock("Fac", "Color"), "dynamic": False},
        "ShaderNodeGroup": {"label": "Group", "inputs": [], "outputs": [], "dynamic": False}},
        "GeometryNodeTree": {"GeometryNodeCaptureAttribute": {"label": "Capture Attribute", "inputs": sock("Geometry"),
                                                              "outputs": sock("Geometry"), "dynamic": True}}}
    if raycast:  # the newer version: also a class the older one doesn't have
        classes["EeveeOnlyThing"] = cls("bpy_struct", {"size": P("FLOAT")})
        classes["Scene"]["props"]["eevee_only"] = P("POINTER", fixed="EeveeOnlyThing")
        nodes["ShaderNodeTree"]["ShaderNodeRaycast"] = {"label": "Raycast", "inputs": sock("Position"),
                                                        "outputs": sock("Is Hit"), "dynamic": False}
        classes["ShaderNodeRaycast"] = cls("Node")
    return {
        "blender": version, "version_string": version, "classes": classes, "nodes": nodes,
        "default_trees": {"material": [["Principled BSDF", "ShaderNodeBsdfPrincipled"]]},
        "types": {"modifier": {"BEVEL": "BevelModifier", "SUBSURF": "SubsurfModifier", "NODES": "NodesModifier"},
                  "light": {"POINT": None, "AREA": "AreaLight"}},
        "dynamic_enums": {"RenderSettings.engine": ["BLENDER_EEVEE", "BLENDER_WORKBENCH", "CYCLES"]},
        "live_enums": {"BevelModifier.offset_type": ["OFFSET", "WIDTH"], "AreaLight.shape": ["SQUARE", "DISK"]},
        "modules": {"mathutils": ["Vector", "Matrix", "noise"], "mathutils.noise": ["noise", "random"],
                    "bpy_extras": ["anim_utils", "object_utils"],
                    "bpy_extras.anim_utils": ["action_get_channelbag_for_slot"],
                    "bmesh": ["new", "ops", "types"], "bmesh.ops": ["create_cube"], "bmesh.types": ["BMesh"],
                    "bmesh.types.BMesh": ["verts", "faces", "to_mesh", "free"],
                    "bpy.ops": ["object", "mesh"], "bpy.types": list(classes),
                    "bpy.types.bpy_prop_collection": ["find", "foreach_set", "get", "keys", "values"]},
        "ops": {"object": ["shade_smooth"], "mesh": ["primitive_cube_add"]},
        "op_props": {"object.shade_smooth": ["keep_sharp_edges"], "mesh.primitive_cube_add": ["size", "location"]},
    }


HEAD = "import bpy\nimport mathutils\n"


class LintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="wm-lint-")
        for d in (make_dump("5.2.2", raycast=True), make_dump("5.0.1", extra_mesh_prop="use_old_thing")):
            with open(os.path.join(cls.tmp, d["blender"] + ".json"), "w") as f:
                json.dump(d, f)
        cls.facts = rna_lint.Facts.load(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def lint(self, body, head=HEAD):
        return rna_lint.Linter(self.facts).lint(head + body)

    def names(self, body, level="error", head=HEAD):
        return [(x["kind"], x["name"]) for x in self.lint(body, head) if x["level"] == level]

    def test_versions_newest_first(self):
        self.assertEqual(self.facts.versions, ["5.2.2", "5.0.1"])

    def test_the_known_traps(self):
        src = ("obj = bpy.context.active_object\n"
               "obj.data.use_auto_smooth = True\n"
               "obj.rotation_euler = (mathutils.radians(180), 0, 0)\n"
               "mat = bpy.data.materials.new('m')\n"
               "bsdf = mat.node_tree.nodes['Principled BSDF']\n"
               "bsdf.inputs['Transmission'].default_value = 1.0\n"
               "noise = mat.node_tree.nodes.new('ShaderNodeTexNoise')\n"
               "noise.noise_scale = 5\n"
               "noise.inputs['Scale'].default_value = 5\n"
               "mod = obj.modifiers.new(name='b', type='BEVEL')\n"
               "mod.offset = 0.1\n"
               "mod.width = 0.1\n"
               "bpy.context.scene.render.use_viewport = True\n"
               "bpy.context.scene.render.engine = 'BLENDER_EEVEE_NEXT'\n"
               "bpy.context.scene.render.engine = 'CYCLES'\n"
               "m2 = mat.node_tree.nodes.new('ShaderNodeTexMusgrave')\n")
        got = self.names(src)
        for want in [("attr", "use_auto_smooth"), ("module", "mathutils.radians"), ("socket", "Transmission"),
                     ("attr", "noise_scale"), ("attr", "offset"), ("attr", "use_viewport"),
                     ("enum", "BLENDER_EEVEE_NEXT"), ("node_type", "ShaderNodeTexMusgrave")]:
            self.assertIn(want, got)
        self.assertEqual(len(got), 8, got)  # nothing else: Scale, width and CYCLES are fine
        msg = [x["message"] for x in self.lint(src) if x["name"] == "Transmission"][0]
        self.assertIn("Transmission Weight", msg)  # says what does exist

    def test_one_version_only_is_a_warning(self):
        src = ("me = bpy.data.meshes.new('m')\nme.use_old_thing = True\n"
               "n = bpy.data.materials.new('m').node_tree.nodes.new('ShaderNodeRaycast')\n")
        warns = self.names(src, "warn")
        self.assertEqual(warns, [("attr", "use_old_thing"), ("node_type", "ShaderNodeRaycast")])
        self.assertEqual(self.names(src), [])
        self.assertIn("only in 5.0.1", self.lint(src)[0]["message"])

    def test_untyped_names_are_left_alone(self):
        src = ("def f(obj):\n    obj.data.use_auto_smooth = True\n"
               "a, b = something()\n"
               "a.use_auto_smooth = 1\n"
               "x = bpy.data.objects.new('o', None)\n"
               "x = make_it()\n"
               "x.use_auto_smooth = 1\n"  # x is bound twice, once to something unknown
               "node = mat_tree.nodes['My own name']\n"
               "node.whatever = 1\n")
        self.assertEqual(self.names(src), [])

    def test_scopes_keep_their_own_types(self):
        src = ("obj = bpy.data.objects.new('o', None)\n"
               "def helper(obj):\n    obj.anything = 1\n"
               "def build(ctx):\n    obj = bpy.data.meshes.new('m')\n    obj.vertices\n    obj.nope = 1\n"
               "obj.nope2 = 1\n")
        self.assertEqual(self.names(src), [("attr", "nope"), ("attr", "nope2")])

    def test_contract_ctx_and_loops(self):
        src = ("def build_s1(ctx):\n"
               "    ctx['scene'].render.resolution_x = 10\n"
               "    ctx['scene'].render.nope = 1\n"
               "    for o in ctx['scene'].objects:\n        o.hide_render = True\n        o.hidden = True\n")
        self.assertEqual(self.names(src), [("attr", "nope"), ("attr", "hidden")])

    def test_registered_properties_and_union_types(self):
        src = ("bpy.types.Object.my_settings = bpy.props.PointerProperty(type=X)\n"
               "o = bpy.data.objects.new('o', None)\n"
               "o.my_settings.value = 1\n"
               "o.data.energy = 10\n"       # obj.data is any ID: a Light has energy
               "o.data.vertices\n")
        self.assertEqual(self.names(src), [])

    def test_sockets_of_groups_dynamic_nodes_and_script_made_sockets(self):
        src = ("t = bpy.data.materials.new('m').node_tree\n"
               "g = t.nodes.new('ShaderNodeGroup')\n"
               "g.inputs['Anything'].default_value = 1\n"
               "c = t.nodes.new('GeometryNodeCaptureAttribute')\n"
               "c.outputs['Whatever']\n")
        self.assertEqual(self.names(src), [])
        # An untyped node: only a name no node has at all, and only when the script makes no sockets itself.
        self.assertEqual(self.names("n = get_node()\nn.inputs['Nonsense Name']\nn.inputs['Scale']\n"),
                         [("socket", "Nonsense Name")])
        self.assertEqual(self.names("tree.interface.new_socket(name='Nonsense Name', in_out='INPUT')\n"
                                    "n = get_node()\nn.inputs['Nonsense Name']\n"), [])

    def test_modifier_light_and_enum_values(self):
        src = ("o = bpy.data.objects.new('o', None)\n"
               "o.modifiers.new('x', 'SMOOTH_BY_ANGLE')\n"
               "b = o.modifiers.new('b', 'BEVEL')\nb.offset_type = 'DEPTH'\nb.offset_type = 'WIDTH'\n"
               "l = bpy.data.lights.new('l', type='AREA')\nl.shape = 'ROUND'\nl.size = 2\n"
               "n = bpy.data.materials.new('m').node_tree.nodes.new('ShaderNodeTexNoise')\n"
               "n.noise_dimensions = '9D'\n")  # no live measurement of this enum: not checked
        self.assertEqual(self.names(src), [("enum", "SMOOTH_BY_ANGLE"), ("enum", "DEPTH"), ("enum", "ROUND")])

    def test_modules_ops_and_imports(self):
        src = ("import bmesh\nfrom mathutils import Vector, radians\nfrom bpy.types import Operator, Nope\n"
               "bm = bmesh.new()\nbmesh.ops.create_cube(bm)\nbmesh.ops.create_cone(bm)\nbm.to_mesh(m)\nbm.verts_nope\n"
               "mathutils.noise.random()\n"
               "bpy.ops.object.shade_smooth(keep_sharp_edges=True)\n"
               "bpy.ops.object.shade_auto_smooth()\n"
               "bpy.ops.mesh.primitive_cube_add(size=2, segments=3)\n"
               "bpy.ops.nope.thing()\n")
        got = self.names(src, head="import bpy\nimport mathutils\n")
        self.assertEqual(got, [("module", "mathutils.radians"), ("class", "Nope"), ("module", "bmesh.ops.create_cone"),
                               ("module", "bmesh.types.BMesh.verts_nope"), ("op", "bpy.ops.object.shade_auto_smooth"),
                               ("op_arg", "bpy.ops.mesh.primitive_cube_add(segments=)"), ("module", "bpy.ops.nope")])

    def test_submodules_and_their_names(self):
        src = ("import bpy_extras\nfrom bpy_extras import anim_utils, object_utils, nope_utils\n"
               "from bpy_extras.anim_utils import action_get_channelbag_for_slot, action_nope\n"
               "anim_utils.action_get_channelbag_for_slot(None, None)\nanim_utils.fcurves_nope\n"
               "bpy_extras.anim_utils.action_get_channelbag_for_slot\n")
        self.assertEqual(self.names(src), [("module", "bpy_extras.nope_utils"), ("module", "bpy_extras.anim_utils.action_nope"),
                                           ("module", "bpy_extras.anim_utils.fcurves_nope")])

    def test_run_time_structs_are_not_attribute_checked(self):
        # 5.2.2's mod.properties is a struct made for the modifier's node group (inputs, outputs, panels)
        src = ("o = bpy.data.objects.new('o', None)\nmod = o.modifiers.new('n', 'NODES')\n"
               "mod.properties.inputs.Socket_1.value = 2.0\nmod.properties.outputs\nmod.nope = 1\n")
        self.assertEqual(self.names(src), [("attr", "nope")])

    def test_a_class_in_one_version_only_says_so(self):
        got = [x for x in self.lint("bpy.context.scene.eevee_only.size = 1\nbpy.context.scene.eevee_only.nope = 1\n")
               if x["name"] in ("size", "nope")]
        self.assertEqual([(x["level"], x["name"]) for x in got], [("warn", "nope")])
        self.assertIn("in Blender 5.2.2 (Blender 5.0.1 has no EeveeOnlyThing)", got[0]["message"])

    def test_collection_attributes(self):
        src = ("o = bpy.data.objects.new('o', None)\n"
               "bpy.data.objects.all\n"                   # no such helper
               "bpy.context.scene.objects.link(o)\n"      # 2.7x API: SceneObjects has no link
               "bpy.data.objects.get('x')\n"
               "bpy.data.objects.foreach_set('location', [])\n"
               "o.modifiers.new('b', 'BEVEL')\n"
               "o.modifiers.remove(o.modifiers[0])\n")
        self.assertEqual(self.names(src), [("attr", "all"), ("attr", "link")])

    def test_method_keywords(self):
        src = ("me = bpy.data.meshes.new('m')\n"
               "me.from_pydata(verts=[], edges=[], faces=[])\n"
               "me.from_pydata(vertices=[], edges=[], faces=[])\n"
               "o = bpy.data.objects.new(name='o', data=me)\n"
               "o = bpy.data.objects.new(name='o', object_data=me)\n"
               "o.modifiers.new(name='b', type='BEVEL')\n"
               "o.modifiers.remove(modifier=None)\n"       # no parameter facts for remove: not checked
               "me.shade_smooth(anything=1)\n")           # nor for shade_smooth
        self.assertEqual(self.names(src), [("arg", "from_pydata(verts=)"), ("arg", "new(data=)")])

    def test_syntax_error(self):
        got = self.lint("def broken(:\n")
        self.assertEqual([x["kind"] for x in got], ["syntax"])

    def test_no_dumps(self):
        with self.assertRaises(ValueError):
            rna_lint.Facts.load(os.path.join(self.tmp, "nothing-here"))


REAL = all(os.path.exists(os.path.join(rna_lint.RNA_DIR, v + ".json")) for v in ("5.2.2", "5.0.1"))


@unittest.skipUnless(REAL, "no real dumps in data/rna (python3 tools/rna_dump.py dump)")
class RealDumpTests(unittest.TestCase):
    """The Oct 29 crashes against Blender's own facts."""

    @classmethod
    def setUpClass(cls):
        cls.linter = rna_lint.Linter(rna_lint.Facts.load())

    def test_oct_29_traps_flagged(self):
        src = (HEAD + "scene = bpy.context.scene\n"
               "obj = bpy.context.active_object\n"
               "obj.data.use_auto_smooth = True\n"
               "obj.rotation_euler = (mathutils.radians(180), 0, 0)\n"
               "mat = bpy.data.materials.new('m')\n"
               "bsdf = mat.node_tree.nodes['Principled BSDF']\n"
               "bsdf.inputs['Transmission'].default_value = 1\n"
               "bsdf.inputs['Specular'].default_value = 1\n"
               "noise = mat.node_tree.nodes.new('ShaderNodeTexNoise')\n"
               "noise.noise_scale = 5\n"
               "scene.render.use_viewport = True\n"
               "bev = obj.modifiers.new('b', type='BEVEL')\n"
               "bev.offset = 0.1\nbev.depth = 0.1\n")
        got = {x["name"] for x in self.linter.lint(src) if x["level"] == "error"}
        self.assertEqual(got, {"use_auto_smooth", "mathutils.radians", "Transmission", "Specular", "noise_scale",
                               "use_viewport", "offset", "depth"})

    def test_fixed_copy_is_clean(self):
        src = (HEAD + "from math import radians\nscene = bpy.context.scene\n"
               "scene.render.engine = 'CYCLES'\nscene.cycles.samples = 32\nscene.view_settings.view_transform = 'AgX'\n"
               "obj = bpy.context.active_object\nobj.data.shade_smooth()\n"
               "obj.rotation_euler = (radians(180), 0, 0)\n"
               "mat = bpy.data.materials.new('m')\nbsdf = mat.node_tree.nodes['Principled BSDF']\n"
               "bsdf.inputs['Transmission Weight'].default_value = 1\n"
               "bsdf.inputs['Specular IOR Level'].default_value = 0.5\n"
               "noise = mat.node_tree.nodes.new('ShaderNodeTexNoise')\nnoise.inputs['Scale'].default_value = 5\n"
               "mat.node_tree.links.new(noise.outputs['Color'], bsdf.inputs['Base Color'])\n"
               "bev = obj.modifiers.new('b', type='BEVEL')\nbev.width = 0.1\nbev.segments = 3\n"
               "bpy.ops.object.shade_auto_smooth(angle=0.5)\n"
               "img = bpy.data.images.new('i', 4, 4)\nimg.colorspace_settings.name = 'Non-Color'\n")
        self.assertEqual([x for x in self.linter.lint(src) if x["level"] == "error"], [])


    def test_the_evals_own_passing_scripts_are_clean(self):
        """Every script the eval verified in both Blenders (W1 references, W2 right code, W3 fixes, W4 Blender
        references): no error, and the only warning is a real version difference."""
        import evalset
        es = evalset.load()
        scripts = {c["id"]: evalset.code(c["reference"]) for c in es.cases("w1")}
        scripts.update({c["id"]: evalset.code(c.get("setup")) + "\n" + evalset.code(c["right"]) for c in es.cases("w2")})
        for c in es.cases("w3"):
            fix = evalset.code(c["fix"]["reference"])
            scripts[c["id"]] = (evalset.python_blocks(fix) or [fix])[0]
        for c in es.cases("w4f"):
            if c["mode"] == "blender" and c.get("reference"):
                scripts[c["id"]] = evalset.python_blocks(evalset.code(c["reference"]))[0]
        self.assertEqual(len(scripts), 64)
        found = {k: self.linter.lint(src) for k, src in scripts.items()}
        self.assertEqual({k: [x["message"] for x in v if x["level"] == "error"] for k, v in found.items()
                          if any(x["level"] == "error" for x in v)}, {})
        warns = sorted((k, x["name"]) for k, v in found.items() for x in v if x["level"] == "warn")
        self.assertEqual(warns, [("w3-19", "properties")])  # mod.properties is 5.2's, behind hasattr()

    def test_python_packages_list_every_submodule(self):
        """from bpy_extras import anim_utils: the dump lists each package's submodules, imported yet or not."""
        facts = rna_lint.Facts.load()
        for v, binary in blenders.VERSIONS.items():
            if v not in facts.versions:
                continue
            res = os.path.join(os.path.dirname(os.path.dirname(binary)), "Resources", ".".join(v.split(".")[:2]),
                               "scripts", "modules")
            for pkg in ("bpy_extras", "bpy/utils"):
                d = os.path.join(res, pkg)
                if not os.path.isdir(d):
                    self.skipTest(f"no {d}")
                files = {n[:-3] for n in os.listdir(d) if n.endswith(".py") and n != "__init__.py"}
                files |= {n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n)) and n != "__pycache__"}
                have = facts.module(pkg.replace("/", "."), v)
                self.assertEqual(files - have, set(), (v, pkg))
                for sub in files:
                    self.assertIsNotNone(facts.module(pkg.replace("/", ".") + "." + sub, v), (v, pkg, sub))
        self.assertIn("action_get_channelbag_for_slot", facts.module("bpy_extras.anim_utils", "5.2.2"))


class DumpRunnerTests(unittest.TestCase):
    """rna_dump.dump_one with a fake Blender that writes a dump for whatever version it says it is."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wm-dump-")
        self.fake = os.path.join(self.tmp, "Blender")
        with open(self.fake, "w") as f:
            f.write(f"#!{sys.executable}\nimport json, os, sys\nout = sys.argv[sys.argv.index('--') + 1]\n"
                    "json.dump({'blender': '9.9.9', 'version_string': '9.9.9', 'classes': {}, 'nodes': {},"
                    " 'ops': {}, 'cwd': os.getcwd(), 'tmpdir': os.environ.get('TMPDIR')}, open(out, 'w'))\n")
        os.chmod(self.fake, 0o755)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_version_named_file(self):
        r = rna_dump.dump_one("9.9.9", self.fake, os.path.join(self.tmp, "rna"))
        self.assertNotIn("error", r)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "rna", "9.9.9.json")))
        self.assertEqual(os.listdir(os.path.join(self.tmp, "rna")), ["9.9.9.json"])  # no temp file left

    def test_blender_runs_in_a_fresh_folder_under_the_scratch_root(self):
        scratch = os.path.join(self.tmp, "scratch")
        old = os.environ.get("WM_SCRATCH")
        os.environ["WM_SCRATCH"] = scratch
        try:
            r = rna_dump.dump_one("9.9.9", self.fake, os.path.join(self.tmp, "rna"))
        finally:
            if old is None:
                os.environ.pop("WM_SCRATCH")
            else:
                os.environ["WM_SCRATCH"] = old
        with open(r["path"]) as f:
            d = json.load(f)
        self.assertEqual(os.path.realpath(os.path.dirname(d["cwd"])), os.path.realpath(scratch))
        self.assertEqual(os.path.realpath(d["tmpdir"]), os.path.realpath(d["cwd"]))
        self.assertFalse(os.path.exists(d["cwd"]), "the run folder is removed")
        self.assertEqual(os.listdir(scratch), [])

    def test_wrong_version_is_refused(self):
        r = rna_dump.dump_one("5.2.2", self.fake, os.path.join(self.tmp, "rna"))
        self.assertIn("is Blender 9.9.9", r["error"])
        self.assertEqual(os.listdir(os.path.join(self.tmp, "rna")), [])


if __name__ == "__main__":
    unittest.main()

"""The lint against two small hand-made dumps (no Blender needed), plus the real dumps when present (their socket
availability once data/rna is remade) and the dump script itself in real Blender 5.2.2 and 5.0.1, sandboxed (about
a second each)."""
import json
import os
import shutil
import sys
import tempfile
import unittest

from tests import _paths  # noqa: F401
from datagen import pysandbox
from tools import blenders, rna_dump, rna_lint


def P(t, **kw):
    return dict({"type": t}, **kw)


def cls(base, props=None, funcs=(), py=()):
    return {"base": base, "props": props or {}, "funcs": list(funcs), "py": list(py)}


def sock(*names, off=()):
    """Sockets as a dump has them: [name, identifier, type, available]; off: the names unavailable on a fresh node."""
    return [[n, n, "NodeSocketFloat", n not in off] for n in names]


def old_dump(d):
    """d as a dump from before the availability field: three-field sockets, no reveal."""
    d = json.loads(json.dumps(d))
    for tree in d["nodes"].values():
        for n in tree.values():
            n.pop("reveal", None)
            for side in rna_lint.SIDES:
                n[side] = [s[:3] for s in n[side]]
    return d


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
    # As Blender 5.2.2 and 5.0.1 make them: the shaders' Weight is unavailable whatever is set, Subsurface IOR and the
    # Noise's W only until a setting (reveal); Mix has an A per data type, one available; Object Info's As Instance is
    # unavailable in a compositor tree only; Render Layers' passes come from the view layer.
    nodes = {"ShaderNodeTree": {
        "ShaderNodeBsdfPrincipled": {"label": "Principled BSDF",
                                     "inputs": sock("Base Color", "Transmission Weight", "Weight", "Subsurface IOR",
                                                    off=("Weight", "Subsurface IOR")),
                                     "outputs": sock("BSDF"), "dynamic": False,
                                     "reveal": {"inputs": {"Subsurface IOR": ["subsurface_method=RANDOM_WALK_SKIN"]},
                                                "outputs": {}}},
        "ShaderNodeEmission": {"label": "Emission", "inputs": sock("Color", "Strength", "Weight", off=("Weight",)),
                               "outputs": sock("Emission"), "dynamic": False, "reveal": {"inputs": {}, "outputs": {}}},
        "ShaderNodeTexNoise": {"label": "Noise Texture", "inputs": sock("Vector", "W", "Scale", off=("W",)),
                               "outputs": sock("Fac", "Color"), "dynamic": False,
                               "reveal": {"inputs": {"W": ["noise_dimensions=1D", "noise_dimensions=4D"]},
                                          "outputs": {}}},
        "ShaderNodeMix": {"label": "Mix", "inputs": [["A", "A_Float", "NodeSocketFloat", True],
                                                     ["A", "A_Color", "NodeSocketColor", False]],
                          "outputs": sock("Result"), "dynamic": False, "reveal": {"inputs": {}, "outputs": {}}},
        "ShaderNodeGroup": {"label": "Group", "inputs": [], "outputs": [], "dynamic": False}},
        "GeometryNodeTree": {"GeometryNodeCaptureAttribute": {"label": "Capture Attribute", "inputs": sock("Geometry"),
                                                              "outputs": sock("Geometry"), "dynamic": True},
                             "GeometryNodeObjectInfo": {"label": "Object Info", "inputs": sock("Object", "As Instance"),
                                                        "outputs": sock("Geometry"), "dynamic": False,
                                                        "reveal": {"inputs": {}, "outputs": {}}}},
        "CompositorNodeTree": {
            "GeometryNodeObjectInfo": {"label": "Object Info", "inputs": sock("Object", "As Instance", off=("As Instance",)),
                                       "outputs": sock("Geometry", off=("Geometry",)), "dynamic": False,
                                       "reveal": {"inputs": {}, "outputs": {}}},
            "CompositorNodeRLayers": {"label": "Render Layers", "inputs": [], "outputs": sock("Image", "Mist", off=("Mist",)),
                                      "dynamic": False, "reveal": {"inputs": {}, "outputs": {}}}}}
    nodes = dict(sorted(nodes.items()))  # the tree types in the order the dump writes them (sort_keys)
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
MARK = "# test fixture, never training data\n"  # tests/contract_fixtures.MARK: Claude-written script text


class LintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="wm-lint-")
        for d in (make_dump("5.2.2", raycast=True), make_dump("5.0.1", extra_mesh_prop="use_old_thing")):
            with open(os.path.join(cls.tmp, d["blender"] + ".json"), "w") as f:
                json.dump(d, f)
        cls.facts = rna_lint.Facts.load(cls.tmp)
        cls.old_tmp = os.path.join(cls.tmp, "old")
        os.makedirs(cls.old_tmp)
        for name in os.listdir(cls.tmp):
            if name.endswith(".json"):
                with open(os.path.join(cls.tmp, name)) as f, open(os.path.join(cls.old_tmp, name), "w") as g:
                    json.dump(old_dump(json.load(f)), g)
        cls.old_facts = rna_lint.Facts.load(cls.old_tmp)

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

    def test_an_input_never_available_is_an_error(self):
        """inputs['Weight'] on a Principled BSDF raises KeyError in 5.2.2 and 5.0.1: the node has the socket, but no
        setting makes it available, and a lookup skips an unavailable socket."""
        src = (MARK + "t = bpy.data.materials.new('m').node_tree\n"
               "bsdf = t.nodes['Principled BSDF']\nbsdf.inputs['Weight'].default_value = 1\n"
               "e = t.nodes.new('ShaderNodeEmission')\ne.inputs.get('Weight')\n")
        got = [(x["level"], x["kind"], x["name"], x["message"]) for x in self.lint(src)]
        self.assertEqual(got, [
            ("error", "socket", "Weight", "input 'Weight' on ShaderNodeBsdfPrincipled is never available to a script "
                                          "(inputs['Weight'] raises KeyError)"),
            ("error", "socket", "Weight", "input 'Weight' on ShaderNodeEmission is never available to a script "
                                          "(inputs['Weight'] raises KeyError)")])

    def test_inputs_a_setting_reveals_are_left_alone(self):
        """Noise's W (noise_dimensions 1D or 4D) and Subsurface IOR (subsurface_method RANDOM_WALK_SKIN) are
        unavailable on a fresh node too, but legal once the script sets them: the lint can't follow settings."""
        src = (MARK + "t = bpy.data.materials.new('m').node_tree\n"
               "n = t.nodes.new('ShaderNodeTexNoise')\nn.noise_dimensions = '4D'\nn.inputs['W'].default_value = 1\n"
               "b = t.nodes['Principled BSDF']\nb.inputs['Subsurface IOR'].default_value = 1.4\n"
               "m = t.nodes.new('ShaderNodeMix')\nm.inputs['A']\nm.inputs['A_Color']\n")
        self.assertEqual(self.lint(src), [])

    def test_outputs_are_never_flagged_for_availability(self):
        # 5.0.1's Render Layers passes are unavailable until the view layer has them, which the node can't show
        src = (MARK + "t = bpy.data.node_groups.new('c', 'CompositorNodeTree')\n"
               "rl = t.nodes.new('CompositorNodeRLayers')\nrl.outputs['Mist']\nrl.outputs['Image']\nrl.outputs['Nope']\n")
        self.assertEqual(self.names(src), [("socket", "Nope")])
        self.assertIn("no output 'Nope' on CompositorNodeRLayers", self.lint(src)[0]["message"])

    def test_near_never_offers_what_a_script_cant_reach(self):
        src = MARK + "b = bpy.data.materials.new('m').node_tree.nodes['Principled BSDF']\nb.inputs['Weigth']\n"
        msg = [x["message"] for x in self.lint(src)]
        self.assertEqual(len(msg), 1)
        self.assertNotIn("'Weight'", msg[0])
        old = rna_lint.Linter(self.old_facts).lint(HEAD + src)  # today's dumps offered it
        self.assertIn("(has: 'Weight')", old[0]["message"])

    def test_an_old_dump_gives_no_new_error(self):
        """Three-field sockets (dumps made before availability): every socket counts, so Weight is fine there and the
        lint says exactly what it said before."""
        src = (MARK + "t = bpy.data.materials.new('m').node_tree\nb = t.nodes['Principled BSDF']\n"
               "b.inputs['Weight'].default_value = 1\nb.inputs['Transmission'] = 1\n"
               "n = get_node()\nn.inputs['Weight']\n")
        got = [(x["kind"], x["name"]) for x in rna_lint.Linter(self.old_facts).lint(HEAD + src) if x["level"] == "error"]
        self.assertEqual(got, [("socket", "Transmission")])
        self.assertTrue(all(rna_lint.usable(n, side, sk) for d in self.old_facts.dumps.values()
                            for t in d["nodes"].values() for n in t.values() for side in rna_lint.SIDES for sk in n[side]))

    def test_a_socket_available_in_another_tree_type_counts(self):
        """5.2.2's compositor makes Object Info with As Instance unavailable; a geometry tree has it. The dump's
        first entry is the compositor's (sorted keys), so Facts.node merges the two."""
        src = (MARK + "g = bpy.data.node_groups.new('g', 'GeometryNodeTree')\n"
               "oi = g.nodes.new('GeometryNodeObjectInfo')\noi.inputs['As Instance'].default_value = True\n")
        self.assertEqual(self.lint(src), [])
        info = self.facts.node("GeometryNodeObjectInfo", "5.2.2")
        self.assertEqual([s[3] for s in info["inputs"]], [True, True])
        raw = self.facts.dumps["5.2.2"]["nodes"]["CompositorNodeTree"]["GeometryNodeObjectInfo"]
        self.assertEqual([s[3] for s in raw["inputs"]], [True, False])  # the dump itself is left as it is
        self.assertIs(self.facts.node("ShaderNodeTexNoise", "5.2.2"),
                      self.facts.dumps["5.2.2"]["nodes"]["ShaderNodeTree"]["ShaderNodeTexNoise"])

    def test_an_untyped_node_and_a_name_no_script_can_reach(self):
        # In the fixture Weight is only on the shaders; the real dumps have it usable on Blur Attribute and others.
        got = [x["message"] for x in self.lint(MARK + "n = get_node()\nn.inputs['Weight']\nn.inputs['Scale']\n")]
        self.assertEqual(got, ["no node type has an input 'Weight' a script can use in Blender 5.2.2 or 5.0.1"])
        self.assertIn("Weight", self.facts.sockets_seen["inputs"])
        self.assertNotIn("Weight", self.facts.sockets_all["inputs"])

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


class GuardedAccessTests(unittest.TestCase):
    """After the fourth smoke (Nov 5): an attribute read that can't run unless its name is there is no finding
    (rna_lint.guards): behind hasattr or a getattr with a falsy default on the same expression, after an early exit
    when it is missing, or in a branch no version reaches. The fourth smoke's n-blender-0000-01 r2 s3 c5 ran clean in
    both Blenders and was dropped for `elif hasattr(act, "fcurves") and act.fcurves:` alone. A try is no guard. The
    hand-made dumps are LintTests' (Mesh has vertices in both, use_old_thing in the older only). The rule is the data
    generator's only (decided Nov 6): a Linter made with guards=True, as datagen's are; the default lints as before
    Nov 5 (test_the_rule_is_data_generation_only)."""

    setUpClass = classmethod(LintTests.setUpClass.__func__)
    tearDownClass = classmethod(LintTests.tearDownClass.__func__)
    names = LintTests.names
    ME = "me = bpy.data.meshes.new('m')\nother = bpy.data.meshes.new('o')\n"

    def lint(self, body, head=HEAD):
        return rna_lint.Linter(self.facts, guards=True).lint(head + body)

    def test_the_rule_is_data_generation_only(self):
        """Decided Nov 6: the default Linter, the eval's (runner/score.py, step_eval.py, task_eval.py, freeze.py's
        verify), rna_dump's lint command and lint_source() have no guarded-read rule, so a guarded read is the
        finding it was before Nov 5, every one of this class's guarded cases; datagen's linters pass guards=True."""
        guarded = ["if hasattr(me, 'bogus'):\n    me.bogus = 1\n",
                   "if getattr(me, 'bogus', None):\n    me.bogus = 1\n",
                   "def f():\n    if not hasattr(me, 'bogus'):\n        return\n    me.bogus = 1\n",
                   "if hasattr(me, 'nothing_has_it'):\n    other.use_auto_smooth = True\n"]
        for body in guarded:
            src = HEAD + self.ME + body
            plain = [(x["kind"], x["name"]) for x in rna_lint.Linter(self.facts).lint(src) if x["level"] == "error"]
            self.assertTrue(plain, body)
            self.assertEqual(plain, [(x["kind"], x["name"]) for x in rna_lint.lint_source(src, self.facts)
                                     if x["level"] == "error"], body)
            self.assertEqual(self.names(self.ME + body), [], body)
        self.assertFalse(rna_lint.Linter(self.facts).use_guards)
        self.assertTrue(rna_lint.Linter(self.facts, guards=True).use_guards)

    def test_behind_hasattr_or_getattr(self):
        guarded = [
            "if hasattr(me, 'bogus'):\n    me.bogus = 1\n",
            "if hasattr(me, 'bogus') and me.bogus:\n    for v in me.bogus:\n        pass\n",
            "while hasattr(me, 'bogus'):\n    me.bogus = 1\n",
            "x = me.bogus if hasattr(me, 'bogus') else None\n",
            "x = [me.bogus for _ in range(2) if hasattr(me, 'bogus')]\n",
            "x = not hasattr(me, 'bogus') or me.bogus\n",
            "if getattr(me, 'bogus', None):\n    me.bogus = 1\n",
            "if getattr(me, 'bogus', []):\n    me.bogus = 1\n",
            "assert hasattr(me, 'use_old_thing')\nme.use_old_thing = 1\n",  # an assert on a name some version has
            "def f():\n    if not hasattr(me, 'use_old_thing'):\n        raise RuntimeError('old')\n"
            "    me.use_old_thing = 1\n",
            "def f():\n    if not hasattr(me, 'bogus'):\n        return\n    me.bogus = 1\n",
            "for k in range(3):\n    if not hasattr(me, 'bogus'):\n        continue\n    me.bogus = k\n",
            "if hasattr(bpy.context.scene.render, 'bogus'):\n    bpy.context.scene.render.bogus = 1\n",
        ]
        for body in guarded:
            self.assertEqual(self.names(self.ME + body), [], body)
            self.assertEqual(self.names(self.ME + body, "warn"), [], body)
        self.assertEqual(self.names(self.ME + "me.bogus = 1\n"), [("attr", "bogus")])  # unguarded, as before

    def test_a_branch_no_version_reaches(self):
        """A body behind a name no version has never runs. The else (or elif) behind a hasattr whose name every
        version has does, when the receiver is None (the independent checks, Nov 6: `cam = scene.camera; if
        hasattr(cam, "data"): ... else: <the fallback>` runs its else on a scene with no camera), so it is checked."""
        self.assertEqual(self.names(self.ME + "if hasattr(me, 'nothing_has_it'):\n    other.use_auto_smooth = True\n"),
                         [])
        for body in ("if hasattr(me, 'vertices'):\n    pass\nelse:\n    me.use_auto_smooth = True\n",
                     "if hasattr(me, 'vertices'):\n    pass\nelif other.use_auto_smooth:\n    pass\n",
                     "if not hasattr(me, 'vertices'):\n    other.use_auto_smooth = True\n",
                     "me = bpy.data.meshes.get('m')\nif hasattr(me, 'vertices'):\n    pass\n"
                     "else:\n    other.use_auto_smooth = True\n"):
            self.assertEqual(self.names(self.ME + body), [("attr", "use_auto_smooth")], body)
        # a test some version passes: the branch may run, so it is checked (use_old_thing is the older's only)
        self.assertEqual(self.names(self.ME + "if hasattr(me, 'use_old_thing'):\n    pass\n"
                                              "else:\n    me.use_auto_smooth = True\n"), [("attr", "use_auto_smooth")])

    def test_what_the_independent_checks_found_is_no_guard(self):
        """Nov 6. A hasattr or getattr on bpy.ops or one of its groups is always true (any name answers, and the
        operator fails only when it is called), so it guards nothing; and an assert, or a raise when the name is
        missing, on a name no version has is a certain crash in every version, so its finding stays (the fix the
        teacher hears hangs on it). The same on a name some version has stays a guard
        (test_behind_hasattr_or_getattr)."""
        cases = {
            "if hasattr(bpy.ops.object, 'bogus_op'):\n    bpy.ops.object.bogus_op()\n":
                [("op", "bpy.ops.object.bogus_op")],
            "if getattr(bpy.ops.object, 'bogus_op', None):\n    bpy.ops.object.bogus_op()\n":
                [("op", "bpy.ops.object.bogus_op")],
            "if hasattr(bpy.ops, 'bogus_group'):\n    bpy.ops.bogus_group.thing()\n":
                [("module", "bpy.ops.bogus_group")],
            "ops = bpy.ops.object\nif hasattr(ops, 'bogus_op'):\n    bpy.ops.object.bogus_op()\n":
                [("op", "bpy.ops.object.bogus_op")],
            "assert hasattr(me, 'bogus')\nme.bogus = 1\n": [("attr", "bogus")],
            "def f():\n    if not hasattr(me, 'bogus'):\n        raise RuntimeError('no')\n    me.bogus = 1\n":
                [("attr", "bogus")],
            "def f():\n    if hasattr(me, 'bogus'):\n        pass\n    else:\n        raise RuntimeError('no')\n"
            "    me.bogus = 1\n": [("attr", "bogus")],
            "assert hasattr(me, 'bogus')\nother.use_auto_smooth = 1\n": [("attr", "use_auto_smooth")],
        }
        for body, want in cases.items():
            self.assertEqual(self.names(self.ME + body), want, body)
        # the second checks (Nov 6): the same certain crash in an if's other branch, a branch before an else that
        # raises, an assert's and, and a raising if's test that leads past the raise
        for body in ("if not hasattr(me, 'bogus'):\n    raise RuntimeError('no')\nelse:\n    me.bogus = 1\n",
                     "if hasattr(me, 'bogus'):\n    me.bogus = 1\nelse:\n    raise RuntimeError('no')\n",
                     "assert hasattr(me, 'bogus') and me.bogus >= 0\n",
                     "if not hasattr(me, 'bogus') or not me.bogus:\n    raise RuntimeError('no')\n",
                     "if hasattr(me, 'bogus') and me.bogus:\n    pass\nelse:\n    raise RuntimeError('no')\n"):
            self.assertEqual(self.names(self.ME + body), [("attr", "bogus")], body)
        # on a name some version has they stay guards, and an if that raises nowhere guards as before
        for body in ("if not hasattr(me, 'use_old_thing'):\n    raise RuntimeError('no')\nelse:\n"
                     "    me.use_old_thing = 1\n",
                     "assert hasattr(me, 'use_old_thing') and me.use_old_thing\n",
                     "if hasattr(me, 'bogus') and me.bogus:\n    pass\n",
                     "if not hasattr(me, 'bogus') or not me.bogus:\n    print('no')\n"):
            self.assertEqual(self.names(self.ME + body), [], body)
        # the plain call is a finding as before, and an early return on a missing name stays a guard
        self.assertEqual(self.names(self.ME + "bpy.ops.object.bogus_op()\n"), [("op", "bpy.ops.object.bogus_op")])
        self.assertEqual(self.names(self.ME + "def f():\n    if not hasattr(me, 'bogus'):\n        return\n"
                                              "    me.bogus = 1\n"), [])

    def test_what_is_no_guard(self):
        """Still findings: a try, another receiver (one the lint can't type, so its branch may run: an other Mesh
        without the name is a branch no version reaches, test_a_branch_no_version_reaches), a getattr with a truthy
        default, a guard the receiver was bound again after, a function defined under a guard (it runs later), an
        early exit that doesn't leave, a missing name that is an else's own test; each beside the guard it lacks."""
        self.assertEqual(self.names(self.ME + "if hasattr(me, 'bogus'):\n    me.bogus = 1\n"), [])  # the guard
        for body in ("try:\n    me.bogus = 1\nexcept AttributeError:\n    pass\n",
                     "thing = make_it()\nif hasattr(thing, 'bogus'):\n    me.bogus = 1\n",
                     "if getattr(me, 'bogus', 1):\n    me.bogus = 1\n",
                     "if hasattr(me, 'bogus'):\n    me = bpy.data.meshes.new('n')\n    me.bogus = 1\n",
                     "if hasattr(me, 'bogus'):\n    def f():\n        return me.bogus\n",
                     "if not hasattr(me, 'bogus'):\n    print('no')\nme.bogus = 1\n",
                     "if hasattr(me, 'bogus') or me.bogus:\n    pass\n",
                     "if hasattr(me, 'vertices') and me.bogus:\n    pass\n",
                     "if hasattr(me, 'bogus'):\n    pass\nelse:\n    me.bogus = 1\n"):
            self.assertEqual(self.names(self.ME + body), [("attr", "bogus")], body)

    def test_the_fourth_smokes_try(self):
        """n-blender-0000-01 r2 s3 c5's interpolation block (its shape, with the fixture's names): the channelbag
        path first, the old one behind hasattr in an elif, the whole in a try. Before Nov 5 its two act.fcurves were
        lint errors; the same read without the guard still is."""
        dump_classes = {"Action": cls("ID", {"layers": P("COLLECTION", fixed="ActionLayer")}),
                        "ActionLayer": cls("bpy_struct", {"strips": P("COLLECTION", fixed="ActionStrip")}),
                        "ActionStrip": cls("bpy_struct")}
        tmp = tempfile.mkdtemp(prefix="wm-lint-guard-")
        try:
            for v in ("5.2.2", "5.0.1"):
                d = make_dump(v)
                d["classes"].update(dump_classes)
                d["classes"]["BlendData"]["props"]["actions"] = P("COLLECTION", fixed="Action", srna="BlendDataActions")
                d["classes"]["BlendDataActions"] = cls("bpy_struct", funcs=["new"])
                with open(os.path.join(tmp, v + ".json"), "w") as f:
                    json.dump(d, f)
            linter = rna_lint.Linter(rna_lint.Facts.load(tmp), guards=True)
            src = HEAD + MARK + (
                "def build_s3(ctx):\n"
                "    act = bpy.data.actions.new('orbit')\n"
                "    try:\n"
                "        if act is not None:\n"
                "            if hasattr(act, 'layers') and act.layers:\n"
                "                for _layer in act.layers:\n"
                "                    for _strip in _layer.strips:\n"
                "                        pass\n"
                "            elif hasattr(act, 'fcurves') and act.fcurves:\n"
                "                for _fc in act.fcurves:\n"
                "                    pass\n"
                "    except Exception:\n"
                "        pass\n")
            self.assertEqual([x for x in linter.lint(src) if x["level"] == "error"], [])
            bare = src.replace("elif hasattr(act, 'fcurves') and act.fcurves:", "elif act.fcurves:")
            self.assertEqual([(x["kind"], x["name"]) for x in linter.lint(bare) if x["level"] == "error"],
                             [("attr", "fcurves"), ("attr", "fcurves")])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_guards_reads_the_tree_only(self):
        """guards() alone: the facts each read stands under, as (receiver, name, exists)."""
        import ast
        tree = ast.parse("if not hasattr(a.b, 'c'):\n    x = a.b.d\nelse:\n    y = a.b.c\n")
        got = {}
        g = rna_lint.guards(tree)
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr in ("c", "d") and isinstance(n.ctx, ast.Load) and \
                    n.lineno > 1:
                got[n.attr] = [(ast.unparse(x), name, ex, hard) for x, name, ex, hard in g.get(id(n), [])]
        self.assertEqual(got, {"d": [("a.b", "c", False, False)], "c": [("a.b", "c", True, False)]})
        # after an assert, or a branch that raises where it doesn't hold, a fact is hard (Linter._guarded)
        tree = ast.parse("assert hasattr(a, 'c')\nx = a.c\nif not hasattr(b, 'e'):\n    raise RuntimeError()\n"
                         "y = b.e\nif not hasattr(d, 'f'):\n    return_ = 1\nz = d.f\n")
        g = rna_lint.guards(tree)
        got = {n.attr: [(ast.unparse(x), name, ex, hard) for x, name, ex, hard in g.get(id(n), [])]
               for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in ("c", "e", "f")}
        self.assertEqual(got, {"c": [("a", "c", True, True)], "e": [("a", "c", True, True), ("b", "e", True, True)],
                               "f": [("a", "c", True, True), ("b", "e", True, True)]})


REAL = all(os.path.exists(os.path.join(rna_lint.RNA_DIR, v + ".json")) for v in ("5.2.2", "5.0.1"))


@unittest.skipUnless(REAL, "no real dumps in data/rna (python3 tools/rna_dump.py dump)")
class RealDumpTests(unittest.TestCase):
    """The Oct 29 crashes against Blender's own facts."""

    @classmethod
    def setUpClass(cls):
        cls.linter = rna_lint.Linter(rna_lint.Facts.load())
        cls.guarded = rna_lint.Linter(cls.linter.f, guards=True)  # the data generator's (GuardedAccessTests)

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

    def test_a_probe_on_bpy_ops_guards_nothing(self):
        """The independent checks (Nov 6): in 5.2.2 and 5.0.1 hasattr(bpy.ops.wm, "svg_import") and
        hasattr(bpy.ops.import_scene, "obj") are true though neither operator exists (a call raises "could not be
        found"), so the old import idiom behind them is still the lint's finding, as is an Action's fcurves behind an
        assert (no version has it: a certain crash)."""
        src = (HEAD + "import os\n\ndef build(p):\n    if os.path.exists(p):\n"
               "        if hasattr(bpy.ops.wm, 'svg_import'):\n            bpy.ops.wm.svg_import(filepath=p)\n"
               "        else:\n            bpy.ops.import_curve.svg(filepath=p)\n"
               "    if hasattr(bpy.ops.import_scene, 'obj'):\n        bpy.ops.import_scene.obj(filepath=p)\n"
               "    else:\n        bpy.ops.wm.obj_import(filepath=p)\n"
               "    if getattr(bpy.ops.wm, 'svg_import', None):\n        bpy.ops.wm.svg_import(filepath=p)\n"
               "    act = bpy.data.actions.new('a')\n    assert hasattr(act, 'fcurves')\n"
               "    for fc in act.fcurves:\n        pass\n")
        for linter in (self.guarded, self.linter):  # the data generator's, and the default with no guard rule
            got = sorted((x["kind"], x["name"]) for x in linter.lint(src) if x["level"] == "error")
            self.assertEqual(got, [("attr", "fcurves"), ("op", "bpy.ops.import_scene.obj"),
                                   ("op", "bpy.ops.wm.svg_import"), ("op", "bpy.ops.wm.svg_import")])


    def test_a_probe_on_bpy_context_reaches_its_branch(self):
        """The second checks (Nov 6): bpy.context's members (active_object, object, edit_object, selected_objects)
        are filled in at run time, no RNA property of Context, and hasattr(bpy.context, "active_object") is true in
        5.2.2 and 5.0.1, so its branch runs: what is in it, or after an early exit when it is missing, is still the
        lint's finding (EEVEE's use_bloom, a mesh's use_auto_smooth). A view_layer probe was one already."""
        head = HEAD + "scene = bpy.context.scene\nme = bpy.data.meshes.new('m')\n"
        for body, name in (("if hasattr(bpy.context, 'active_object') and bpy.context.active_object:\n"
                            "    scene.eevee.use_bloom = True\n", "use_bloom"),
                           ("def build():\n    if not hasattr(bpy.context, 'selected_objects'):\n        return\n"
                            "    me.use_auto_smooth = True\n", "use_auto_smooth"),
                           ("if getattr(bpy.context, 'object', None):\n    me.use_auto_smooth = True\n",
                            "use_auto_smooth"),
                           ("x = me.use_auto_smooth if hasattr(bpy.context, 'edit_object') else None\n",
                            "use_auto_smooth"),
                           ("if hasattr(bpy.context, 'view_layer'):\n    scene.eevee.use_bloom = True\n", "use_bloom")):
            for linter in (self.guarded, self.linter):
                got = [x["name"] for x in linter.lint(head + body) if x["level"] == "error"]
                self.assertEqual(got, [name], body)

    def test_the_evals_own_passing_scripts_are_clean(self):
        """Every script the eval verified in both Blenders (W1 references, W2 right code, W3 fixes, W4 Blender
        references): no error, and the only warning is a real version difference (w3-19's mod.properties, 5.2's
        only), as before Nov 5: the default Linter, the eval's, has no guarded-read rule (decided Nov 6). The data
        generator's (guards=True) leaves that warning out too, since it is behind hasattr(), which can't crash in
        either version."""
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
        self.assertIn("hasattr(", scripts["w3-19"])
        guarded = {k: self.guarded.lint(src) for k, src in scripts.items()}
        self.assertEqual([(k, x["name"]) for k, v in guarded.items() for x in v], [])  # guarded (rna_lint.guards)

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


def _never(d):
    """[(idname, input name)] a dump says no setting or pair makes available, in any tree type it is made in."""
    out = set()
    for tree in d["nodes"].values():
        for idname, n in tree.items():
            have = {s[0] for s in n["inputs"] if s[3]}
            out |= {(idname, s[0]) for s in n["inputs"] if s[0] not in have and s[0] not in n["reveal"]["inputs"]}
    ok = {(i, s[0]) for t in d["nodes"].values() for i, n in t.items() for s in n["inputs"] if s[3]}
    return sorted(out - ok)


SHADERS_WITH_WEIGHT = 22  # in 5.2.2 and 5.0.1: Principled, Emission, Glass, Diffuse, the volumes, ...
NEW_REAL = REAL and all(len(s) == 4 for v in ("5.2.2", "5.0.1")
                        for s in rna_lint.Facts.load().node("ShaderNodeBsdfPrincipled", v)["inputs"]) if REAL else False


@unittest.skipUnless(NEW_REAL, "data/rna has no socket availability yet (python3 tools/rna_dump.py dump)")
class RealAvailabilityTests(unittest.TestCase):
    """What the dumps say about sockets a script can't reach, against Blender's own behaviour (measured Nov 4 in
    5.2.2 and 5.0.1, sandboxed)."""

    @classmethod
    def setUpClass(cls):
        cls.facts = rna_lint.Facts.load()
        cls.linter = rna_lint.Linter(cls.facts)

    def test_only_the_shaders_weight_is_never_available(self):
        for v in ("5.2.2", "5.0.1"):
            never = _never(self.facts.dumps[v])
            self.assertEqual({name for _, name in never}, {"Weight"}, v)
            self.assertEqual(len(never), SHADERS_WITH_WEIGHT, v)
            self.assertTrue(all(i.startswith("ShaderNode") for i, _ in never), v)

    def test_what_the_lint_says(self):
        src = (HEAD + MARK + "mat = bpy.data.materials.new('m')\nt = mat.node_tree\n"
               "bsdf = t.nodes['Principled BSDF']\nbsdf.inputs['Weight'].default_value = 1\n"
               "bsdf.inputs['Subsurface IOR'].default_value = 1.4\n"
               "e = t.nodes.new('ShaderNodeEmission')\ne.inputs['Strength'].default_value = 2\n"
               "n = t.nodes.new('ShaderNodeTexNoise')\nn.inputs['W'].default_value = 1\n"
               "r = t.nodes.new('ShaderNodeMapRange')\nr.inputs['Steps'].default_value = 4\n"
               "g = bpy.data.node_groups.new('g', 'GeometryNodeTree')\n"
               "ml = g.nodes.new('GeometryNodeMeshLine')\nml.inputs['Resolution'].default_value = 0.1\n"
               "oi = g.nodes.new('GeometryNodeObjectInfo')\noi.inputs['As Instance'].default_value = True\n"
               "b = g.nodes.new('GeometryNodeBlurAttribute')\nb.inputs['Weight']\n")
        got = [(x["line"], x["level"], x["message"]) for x in self.linter.lint(src)]
        self.assertEqual(got, [(7, "error", "input 'Weight' on ShaderNodeBsdfPrincipled is never available to a "
                                            "script (inputs['Weight'] raises KeyError) (has: 'Coat Weight', "
                                            "'Sheen Weight')")])

    def test_pairs_reveal_what_no_single_setting_does(self):
        for v in ("5.2.2", "5.0.1"):
            ml = self.facts.node("GeometryNodeMeshLine", v)
            self.assertEqual(ml["reveal"]["inputs"]["Resolution"], ["mode=END_POINTS&count_mode=RESOLUTION"], v)
        # 5.2.2's Compare has no Angle or C at all until its settings make them (a warning, as before)
        cmp_ = self.facts.node("FunctionNodeCompare", "5.0.1")["reveal"]["inputs"]
        self.assertEqual((cmp_["Angle"], cmp_["C"]), (["data_type=VECTOR&mode=DIRECTION"],
                                                      ["data_type=VECTOR&mode=DOT_PRODUCT"]))


HAVE_BLENDER = all(not blenders.check_path(p) for p in blenders.VERSIONS.values())
# main.py: the dump script as tools/rna_dump.py runs it (its argv after "--" names the output), then what it found.
DUMP_AND_SAY = """# test fixture, never training data
import json, runpy
runpy.run_path("rna_dump_blender.py")
d = json.load(open("out.json"))
nodes = [(i, n) for t in d["nodes"].values() for i, n in t.items()]
ok = {(i, s[0]) for i, n in nodes for s in n["inputs"] if s[3]}
never = sorted({(i, s[0]) for i, n in nodes for s in n["inputs"]
                if not s[3] and s[0] not in n["reveal"]["inputs"]} - ok)
pairs = sorted((i, x) for i, n in nodes for x, v in n["reveal"]["inputs"].items() if all("&" in y for y in v))
four = all(len(s) == 4 for _, n in nodes for side in ("inputs", "outputs") for s in n[side])
noise = d["nodes"]["ShaderNodeTree"]["ShaderNodeTexNoise"]["reveal"]["inputs"]["W"]
print("CHIMERA-TEST " + json.dumps({"never": never, "pairs": pairs, "four": four, "noise_w": noise,
                                    "seconds": d["seconds"], "blender": d["blender"]}))
"""


@unittest.skipUnless(HAVE_BLENDER and pysandbox.can_sandbox(), "needs Blender 5.2.2 and 5.0.1 and sandbox-exec")
class RealBlenderDumpTests(unittest.TestCase):
    """tools/rna_dump_blender.py in real Blender, under datagen.pysandbox's profile (about a second each)."""

    def test_the_dump_records_availability_and_what_reveals_it(self):
        with open(rna_dump.BLENDER_SCRIPT, encoding="utf-8") as f:
            script = f.read()
        for v, binary in blenders.VERSIONS.items():
            r = pysandbox.run_tool({"main.py": DUMP_AND_SAY, "rna_dump_blender.py": script}, binary,
                                   ["-b", "--factory-startup", "--python-exit-code", "1", "--python", "main.py",
                                    "--", "out.json"], timeout=120)
            self.assertEqual((r["exit"], r["sandboxed"]), (0, True), r["output"][-2000:])
            said = [l for l in r["output"].splitlines() if l.startswith("CHIMERA-TEST ")]
            got = json.loads(said[-1][len("CHIMERA-TEST "):])
            self.assertEqual(got["blender"], v)
            self.assertTrue(got["four"])
            self.assertEqual({name for _, name in got["never"]}, {"Weight"}, v)
            self.assertEqual(len(got["never"]), SHADERS_WITH_WEIGHT, v)
            self.assertIn(["GeometryNodeMeshLine", "Resolution"], got["pairs"], v)
            self.assertEqual(got["noise_w"], ["noise_dimensions=1D", "noise_dimensions=4D"], v)
            self.assertLess(got["seconds"], 30, v)


class UsableTests(unittest.TestCase):
    """rna_lint.usable, the one rule the lint and the teacher's facts (datagen.hints) share."""

    INFO = {"inputs": [["Weight", "Weight", "NodeSocketFloat", False], ["W", "W", "NodeSocketFloat", False],
                       ["A", "A_Float", "NodeSocketFloat", True], ["A", "A_Color", "NodeSocketColor", False],
                       ["Scale", "Scale", "NodeSocketFloat", True]],
            "outputs": [["Mist", "Mist", "NodeSocketFloat", False]],
            "reveal": {"inputs": {"W": ["noise_dimensions=4D"]}, "outputs": {}}}

    def test_the_rule(self):
        got = {s[1]: rna_lint.usable(self.INFO, "inputs", s) for s in self.INFO["inputs"]}
        self.assertEqual(got, {"Weight": False, "W": True, "A_Float": True, "A_Color": True, "Scale": True})
        self.assertTrue(rna_lint.usable(self.INFO, "outputs", self.INFO["outputs"][0]))
        self.assertTrue(rna_lint.usable({}, "inputs", ["Weight", "Weight", "NodeSocketFloat"]))  # an old dump
        self.assertFalse(rna_lint.usable({}, "inputs", ["Weight", "Weight", "NodeSocketFloat", False]))


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

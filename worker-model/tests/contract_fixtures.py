"""TEST FIXTURES ONLY, NEVER TRAINING DATA: hand-made plans and pieces for the contract prototype's tests.

Written by Claude to test contract/ (Anthropic's terms bar training on Claude outputs). Every fixture piece's
code starts with the comment below, so a leak into a training file is easy to find:
"""
from contract.goport import clean_plan

MARK = "# test fixture, never training data"

BLENDER_PLAN = clean_plan({
    "title": "Reading corner",
    "kind": "blender",
    "summary": "A small reading corner built by a Blender script: a floor, a side table and a lamp on the table. "
               "It saves the scene and renders a preview. " + MARK,
    "steps": [
        {"id": "s1", "title": "Floor and material", "kind": "blender",
         "instructions": "Make a 4 x 4 m floor plane chimera_floor with a matte brown material chimera_floor_mat. "
                         "Register it as ctx['objects']['floor']. Save the scene to reading_corner.blend and render "
                         "a small preview reading_corner.png.", "depends_on": []},
        {"id": "s2", "title": "Side table", "kind": "blender",
         "instructions": "Build a side table chimera_table from boxes: a 0.6 x 0.6 m top at 0.55 m and four legs. "
                         "Register the top as ctx['objects']['table'].", "depends_on": []},
        {"id": "s3", "title": "Lamp on the table", "kind": "blender",
         "instructions": "Put a lamp on s2's table: a base, a cone shade and a point light chimera_lamp_light inside "
                         "the shade.", "depends_on": ["s2"]},
    ]})

S1 = '''The floor, with its material.

```python
''' + MARK + '''
import bpy

SETTINGS_s1 = {
    "size": 4.0,
    "color": (0.35, 0.22, 0.12, 1.0),
    "output": {"blend": "reading_corner.blend", "render": "reading_corner.png", "resolution": [64, 48]},
}


def build_s1(ctx):
    s = SETTINGS_s1
    h = s["size"] / 2
    mesh = bpy.data.meshes.new("chimera_floor")
    mesh.from_pydata([(-h, -h, 0), (h, -h, 0), (h, h, 0), (-h, h, 0)], [], [(0, 1, 2, 3)])
    floor = bpy.data.objects.new("chimera_floor", mesh)
    ctx["collection"].objects.link(floor)
    mat = bpy.data.materials.new("chimera_floor_mat")
    mat.diffuse_color = s["color"]
    floor.data.materials.append(mat)
    ctx["objects"]["floor"] = floor


if __name__ == "__main__":
    build_s1({"scene": bpy.context.scene, "collection": bpy.context.scene.collection, "objects": {}})
```

```handoff
provides: chimera_floor as ctx["objects"]["floor"]; material chimera_floor_mat
uses: none
assumed: the floor lies at z = 0
```
'''

S2_CODE = MARK + '''
import bpy
from mathutils import Vector

SETTINGS_s2 = {"top_size": 0.6, "height": 0.55, "leg": 0.04}


def _s2_box(ctx, name, size, location):
    """A box mesh object of the given size, linked into the project's collection."""
    mesh = bpy.data.meshes.new(name)
    x, y, z = (v / 2 for v in size)
    verts = [(sx * x, sy * y, sz * z) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh.from_pydata(verts, [], faces)
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    ctx["collection"].objects.link(obj)
    return obj


def build_s2(ctx):
    s = SETTINGS_s2
    t = s["top_size"]
    top = _s2_box(ctx, "chimera_table", (t, t, 0.03), Vector((1.0, 1.0, s["height"])))
    for i, (dx, dy) in enumerate([(-1, -1), (1, -1), (-1, 1), (1, 1)]):
        off = t / 2 - 0.05
        leg = _s2_box(ctx, "chimera_table_leg_%d" % i, (s["leg"], s["leg"], s["height"]),
                      Vector((dx * off, dy * off, -s["height"] / 2)))
        leg.parent = top
    ctx["objects"]["table"] = top


if __name__ == "__main__":
    build_s2({"scene": bpy.context.scene, "collection": bpy.context.scene.collection, "objects": {}})
'''

S2 = "```python\n" + S2_CODE + '''```

```handoff
provides: chimera_table (the top) as ctx["objects"]["table"], legs chimera_table_leg_0 to 3 parented to it
uses: none
assumed: the table stands at x = 1, y = 1
```
'''

S3_CODE = MARK + '''
import bpy
import bmesh

SETTINGS_s3 = {"shade_color": (0.9, 0.8, 0.6, 1.0), "power": 40.0}


def _s3_cone(ctx, name, r1, r2, depth, location):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=r1, radius2=r2, depth=depth)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    ctx["collection"].objects.link(obj)
    return obj


def build_s3(ctx):
    s = SETTINGS_s3
    table = ctx["objects"].get("table")
    if table is None:
        print("chimera: stand-in", "table")
        table = bpy.data.objects.new("chimera_table_standin", None)
        table.location = (1.0, 1.0, 0.55)
        ctx["collection"].objects.link(table)
    x, y, z = table.location
    _s3_cone(ctx, "chimera_lamp_base", 0.06, 0.05, 0.3, (x, y, z + 0.165))
    shade = _s3_cone(ctx, "chimera_lamp_shade", 0.16, 0.09, 0.18, (x, y, z + 0.36))
    mat = bpy.data.materials.new("chimera_lamp_shade_mat")
    mat.diffuse_color = s["shade_color"]
    shade.data.materials.append(mat)
    light_data = bpy.data.lights.new("chimera_lamp_light", type="POINT")
    light_data.energy = s["power"]
    light = bpy.data.objects.new("chimera_lamp_light", light_data)
    light.location = (x, y, z + 0.33)
    ctx["collection"].objects.link(light)
    ctx["objects"]["lamp"] = shade


if __name__ == "__main__":
    build_s3({"scene": bpy.context.scene, "collection": bpy.context.scene.collection, "objects": {}})
'''

S3 = "```python\n" + S3_CODE + '''```

```handoff
provides: chimera_lamp_shade as ctx["objects"]["lamp"], chimera_lamp_base, chimera_lamp_light
uses: s2's ctx["objects"]["table"]
assumed: none
```
'''

# Broken on purpose, each in a real Blender 5 way.
# s3: the Principled BSDF has no "Transmission" input since 4.0 (it's "Transmission Weight"): KeyError in build_s3.
BROKEN_LINE_S3 = '    mat.node_tree.nodes["Principled BSDF"].inputs["Transmission"].default_value = 0.3'
S3_BROKEN = S3.replace('    mat.diffuse_color = s["shade_color"]\n',
                       '    mat.diffuse_color = s["shade_color"]\n' + BROKEN_LINE_S3 + "\n")
# s2: Mesh.use_auto_smooth was removed in 4.1: AttributeError in the helper _s2_box.
BROKEN_LINE_S2 = "    mesh.use_auto_smooth = True"
S2_BROKEN = S2.replace("    mesh.from_pydata(verts, [], faces)\n",
                       "    mesh.from_pydata(verts, [], faces)\n" + BROKEN_LINE_S2 + "\n")

BLENDER_OUTPUTS = {"s1": S1, "s2": S2, "s3": S3}

# ---------------------------------------------------------------- other modes

SCRIPT_PLAN = clean_plan({
    "title": "Word counter",
    "kind": "code",
    "summary": "A small command-line tool that counts words in text read from standard input and prints the most "
               "common ones.",
    "steps": [
        {"id": "a", "title": "Counting", "kind": "code",
         "instructions": "Write count_words(text) -> dict of lower-case word counts.", "depends_on": []},
        {"id": "b", "title": "Report and entry point", "kind": "code",
         "instructions": "Write top_words(counts, n) and main(), which reads a fixed sample text and prints the top 3.",
         "depends_on": ["a"]},
    ]})

SCRIPT_A = '''```python
''' + MARK + '''
import re
from collections import Counter

WORD = r"[a-z']+"


def count_words(text):
    return dict(Counter(re.findall(WORD, text.lower())))
```

```handoff
provides: count_words(text) -> dict
uses: none
assumed: apostrophes are part of words
```
'''

SCRIPT_B = '''```python
''' + MARK + '''
from collections import Counter

SAMPLE = "the cat and the dog and the bird"


def top_words(counts, n):
    return Counter(counts).most_common(n)


def main():
    for word, k in top_words(count_words(SAMPLE), 3):
        print(word, k)


if __name__ == "__main__":
    main()
```

```handoff
provides: top_words(counts, n), main()
uses: s1's count_words()
assumed: a fixed sample text instead of standard input
```
'''

FILES_PLAN = clean_plan({
    "title": "Notes store",
    "kind": "code",
    "summary": "A tiny notes package: a store module and a CLI that uses it.",
    "steps": [
        {"id": "s1", "title": "Store", "kind": "code",
         "instructions": "Write notes/store.py with class Store (add(text), all()).", "depends_on": []},
        {"id": "s2", "title": "Store search", "kind": "code",
         "instructions": "Add search(store, word) to notes/store.py.", "depends_on": ["s1"]},
        {"id": "s3", "title": "CLI", "kind": "code",
         "instructions": "Write notes/cli.py with main() that adds two notes and prints search results.",
         "depends_on": ["s1", "s2"]},
    ]})

FILES_1 = '''File: notes/store.py
```python
''' + MARK + '''
class Store:
    def __init__(self):
        self.items = []

    def add(self, text):
        self.items.append(text)

    def all(self):
        return list(self.items)
```

```handoff
provides: notes/store.py: class Store with add(text), all()
uses: none
assumed: notes live in memory only
```
'''

FILES_2 = '''File: notes/store.py (part)
```python
''' + MARK + '''
import re


def search(store, word):
    return [t for t in store.all() if re.search(r"\\b%s\\b" % re.escape(word), t)]
```

```handoff
provides: notes/store.py: search(store, word)
uses: s1's Store.all()
assumed: none
```
'''

FILES_3 = '''File: notes/cli.py
```python
''' + MARK + '''
from notes.store import Store, search


def main():
    s = Store()
    s.add("buy milk")
    s.add("call the bank")
    print(search(s, "milk"))
```

```handoff
provides: notes/cli.py: main(); run with python -m notes.cli
uses: s1's Store, s2's search()
assumed: none
```
'''

SECTION_PLAN = clean_plan({
    "title": "Tea guide",
    "kind": "writing",
    "summary": "A short guide to green and black tea.",
    "steps": [
        {"id": "s1", "title": "Green tea", "kind": "writing", "instructions": "Two short paragraphs on green tea.",
         "depends_on": []},
        {"id": "s2", "title": "Black tea", "kind": "writing", "instructions": "Two short paragraphs on black tea.",
         "depends_on": []},
    ]})

SECTION_1 = '''## Green tea

Green tea is steamed or pan-fired soon after picking. (fixture text)

```handoff
provides: the section "Green tea"
uses: none
assumed: none
```
'''

SECTION_2 = '''## Black tea

Black tea is fully oxidised before it is dried. (fixture text)

```handoff
provides: the section "Black tea"
uses: none
assumed: the reader knows what oxidation is
```
'''

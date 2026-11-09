"""After the fourth smoke (Nov 5): what the build drops, told at the gate (blender_gate.build_facts), and the stand-in
marker and silent defaults (datagen/stand_ins.py), read from a Blender piece's code and verdict, no run.

build_facts: Chimera's validator warnings (provides_missing, uses_undeclared, handoff_long) and a dead output key are
gate reasons with tells (validator_warning:<code>, dead_output_key), soft only on a step a later step depends on, as
ctx_channel is; the keys a provides_missing message names (or the code, when the record cut it), a piece's own
stand-in told apart, the uses line's steps and dependencies, each long line's advice, a dead key's two forms (the step
asks for an output, or for none). handoff_long on a values-only step's provides line, whatever its form (decided Nov
6; a plain list of names only from Nov 5), is the user's open contract question: no reason, no tell, and nothing else
fails such a piece either (waived: the build drops it whatever a told batch does); no line any tell gives such a step
asks it to shorten that list.

marker_misused: a print of the marker for something that is no dependency's key the piece reads (the fourth smoke's
values steps with no dependency print "chimera: stand-in render_device (fallback to CPU)"; others mark a file, an
output folder, a node's input), never a key a variable gives, nor one the piece looks up (from ctx, bpy.data, another
step's SETTINGS, a helper or a loop) or one its dependencies hand on. silent_default: a read of a dependency's
ctx["values"] key with a default and no marker (the fourth smoke's only Blender example in valid reads every value
through def get(key): return ctx["values"].get(key, SETTINGS_s4[key])), never a key the piece writes itself, nor one
no dependency hands on when every dependency is there; covered by a marker with its key, or one in the same function.
The tells: short, their fixed wording refused by the echo check, none of Chimera's words but its own print call.

Every piece here is Claude-written test text and carries the fixture mark, never training data. Under a second.
"""
# test fixture, never training data
import unittest

from tests import _paths  # noqa: F401
from datagen import blender_gate as BG
from datagen import hints as H
from datagen import stand_ins as SI
from datagen import task as T
from runner import mock_ollama

MARK = mock_ollama.MARK


def code(body, sid="s2", settings='{"seat": 0.45}'):
    return f"{MARK}\nimport bpy\n\nSETTINGS_{sid} = {settings}\n\n\ndef build_{sid}(ctx):\n{body}"


# s1, a values step, as hydra:1.0's plans open: its sizes and colours handed on in ctx["values"], listed under provides
S1 = (f"```python\n{MARK}\nimport bpy\n\nSETTINGS_s1 = {{\"sofa_dim\": 2.2, \"sofa_tea\": (0, 0.5, 0.5)}}\n\n\n"
      "def build_s1(ctx):\n    for k, v in SETTINGS_s1.items():\n        ctx[\"values\"][k] = v\n```\n\n"
      "```handoff\nprovides: sofa_dim, sofa_tea\nuses: none\nassumed: none\n```\n")
# s2, a sofa registered for later steps
S2 = (f"```python\n{MARK}\nimport bpy\n\n\ndef build_s2(ctx):\n    ctx[\"objects\"][\"sofa\"] = None\n```\n\n"
      "```handoff\nprovides: chimera_sofa as ctx[\"objects\"][\"sofa\"]\nuses: none\nassumed: none\n```\n")


class MarkerTests(unittest.TestCase):

    def test_a_marker_on_a_step_with_no_dependency(self):
        """The fourth smoke's values steps: a GPU fallback marked as a stand-in, on a step nothing hands anything to."""
        body = ('    try:\n        bpy.context.scene.cycles.device = "GPU"\n    except Exception:\n'
                '        print("chimera: stand-in render_device (fallback to CPU)")\n')
        got = SI.check(code(body, "s1"), [], {}, sid="s1")
        self.assertEqual((got["marker"], got["silent"]), (["render_device"], []))
        # the same with the key as the print's second argument, the gpt-oss hyphen, or in an f-string with more after it
        for line in ('print("chimera: stand-in", "render_device")', 'print("chimera: stand‑in render_device")',
                     'print(f"chimera: stand-in render_device ({e})")'):
            self.assertEqual(SI.check(code("    e = 1\n    " + line + "\n", "s1"), [], {}, sid="s1")["marker"],
                             ["render_device"], line)
        # a step with no dependency has nothing to stand in for, even a name it looks up
        lookup = '    if "sofa" not in ctx["objects"]:\n        print("chimera: stand-in", "sofa")\n'
        self.assertEqual(SI.check(code(lookup, "s1"), [], {}, sid="s1")["marker"], ["sofa"])

    def test_a_dependencys_key_is_what_the_marker_is_for(self):
        reader = ('    sofa = ctx["objects"].get("sofa")\n    if sofa is None:\n'
                  '        print("chimera: stand-in", "sofa")\n')
        self.assertEqual(SI.check(code(reader, "s3"), ["s2"], {"s2": S2}, sid="s3")["marker"], [])
        self.assertEqual(SI.check(code(reader, "s3"), ["s2"], {}, sid="s3")["marker"], [])  # s2 dropped
        # looked up in bpy.data, a dependency's name with or without chimera_, the start of names it reads
        for body in ('    if bpy.data.objects.get("chimera_sofa") is None:\n        print("chimera: stand-in sofa")\n',
                     '    print("chimera: stand-in chimera_sofa")\n',
                     '    w = ctx["values"].get("room_length")\n    print("chimera: stand-in room dimensions")\n',
                     '    try:\n        c = SETTINGS_s1["world_color"]\n    except NameError:\n'
                     '        print("chimera: stand-in world_color")\n'):
            self.assertEqual(SI.check(code(body, "s3"), ["s2"], {"s2": S2}, sid="s3")["marker"], [], body)
        # a variable's key is the reader's own loop: never judged
        loop = ('    for key in SETTINGS_s3["needs"]:\n        if key not in ctx["objects"]:\n'
                '            print("chimera: stand-in", key)\n')
        self.assertEqual(SI.check(code(loop, "s3"), ["s2"], {"s2": S2}, sid="s3")["marker"], [])

    def test_a_marker_for_a_file_or_a_setting_on_a_step_with_dependencies(self):
        """The fourth smoke's HDRI, SVG, output folder and node-input markers: no dependency's key."""
        for line, key in (('print("chimera: stand-in", "hdri_path")', "hdri_path"),
                          ('print("chimera: stand-in output_dir")', "output_dir"),
                          ('print(f"chimera: stand-in input {name} not found on Principled BSDF")', "input")):
            body = '    name = SETTINGS_s3["hdri_path"]\n    ' + line + "\n"
            got = SI.check(code(body, "s3", '{"hdri_path": "//studio.exr"}'), ["s2"], {"s2": S2}, sid="s3")
            self.assertEqual(got["marker"], [key], line)
        # the piece's own SETTINGS key isn't a lookup of a dependency's name
        own = '    p = SETTINGS_s3.get("hdri_path")\n    print("chimera: stand-in hdri_path")\n'
        self.assertEqual(SI.check(code(own, "s3"), ["s2"], {"s2": S2}, sid="s3")["marker"], ["hdri_path"])


class SilentDefaultTests(unittest.TestCase):

    def test_the_valid_examples_helper(self):
        """n-blender-0000-01 r2 s4 c0's form: every value through a helper with SETTINGS_s4's default."""
        body = ('    def get(key):\n        return ctx["values"].get(key, SETTINGS_s4[key])\n\n'
                '    power = get("sofa_dim")\n    where = get("lamp_location")\n')
        got = SI.check(code(body, "s4", '{"sofa_dim": 2.0, "lamp_location": (0, 0, 3)}'), ["s1"], {"s1": S1},
                       sid="s4")
        self.assertEqual(got["silent"], [{"key": None, "line": 9, "function": "get"}])
        self.assertEqual(SI.tell(got), [SI.SILENT_HELPER_TELL.format(where="get()", marker=SI.MARKER_CALL)])
        # a helper that marks its stand-in is the contract's way
        marked = ('    def get(key):\n        if key not in ctx["values"]:\n'
                  '            print("chimera: stand-in", key)\n'
                  '        return ctx["values"].get(key, SETTINGS_s4[key])\n\n    power = get("sofa_dim")\n')
        self.assertEqual(SI.check(code(marked, "s4", '{"sofa_dim": 2.0}'), ["s1"], {"s1": S1}, sid="s4")["silent"],
                         [])
        # a helper called only with keys no dependency hands on (every dependency there) is the piece's own
        others = body.replace('get("sofa_dim")', 'get("lamp_power")')
        self.assertEqual(SI.check(code(others, "s4"), ["s1"], {"s1": S1}, sid="s4")["silent"], [])
        # a key that can't be read (built in a loop) is taken for a dependency's
        built = '    sides = [ctx["values"].get("sofa_" + k, 1.0) for k in ("dim", "tea")]\n'
        self.assertEqual(SI.check(code(built), ["s1"], {"s1": S1}, sid="s2")["silent"],
                         [{"key": None, "line": 8, "function": "build_s2"}])

    def test_literal_keys(self):
        forms = ('    w = ctx["values"].get("sofa_dim", 2.0)\n',
                 '    vals = ctx.get("values", {})\n    w = vals.get("sofa_dim", SETTINGS_s2["seat"])\n',
                 '    w = ctx["values"].get("sofa_dim") or 2.0\n',
                 '    v = ctx["values"]\n    w = v["sofa_dim"] if "sofa_dim" in v else 2.0\n')
        for body in forms:
            got = SI.check(code(body), ["s1"], {"s1": S1}, sid="s2")
            self.assertEqual([x["key"] for x in got["silent"]], ["sofa_dim"], body)
        line, = SI.tell(SI.check(code(forms[0]), ["s1"], {"s1": S1}, sid="s2"))
        self.assertEqual(line, '"sofa_dim" from ctx["values"]: read with a default and no stand-in line, though a '
                               'dependency hands it on; where the piece makes its own value for a missing key, add '
                               'print("chimera: stand-in", key)')
        # what isn't one: no default, a None default, a marker for the key or in the same function, a key the piece
        # writes itself, a key no dependency hands on with every dependency there, a step with no dependency
        for body, deps, earlier in (
                ('    w = ctx["values"].get("sofa_dim")\n    if w is None:\n'
                 '        print("chimera: stand-in", "sofa_dim")\n        w = 2.0\n', ["s1"], {"s1": S1}),
                ('    w = ctx["values"].get("sofa_dim", None)\n', ["s1"], {"s1": S1}),
                ('    if "sofa_dim" not in ctx["values"]:\n        print("chimera: stand-in", "sofa_dim")\n'
                 '    w = ctx["values"].get("sofa_dim", 2.0)\n', ["s1"], {"s1": S1}),
                ('    ctx["values"]["count"] = ctx["values"].get("count", 0) + 1\n', ["s1"], {"s1": S1}),
                ('    fps = ctx["values"].get("fps", 24)\n', ["s1"], {"s1": S1}),
                ('    w = ctx["values"].get("sofa_dim", 2.0)\n', [], {})):
            self.assertEqual(SI.check(code(body), deps, earlier, sid="s2")["silent"], [], body)
        # with a dependency dropped, any key the piece doesn't write may be the missing one's
        self.assertEqual([x["key"] for x in SI.check(code('    fps = ctx["values"].get("fps", 24)\n'), ["s1"], {},
                                                     sid="s2")["silent"]], ["fps"])

    def test_what_the_dependencies_hand_on(self):
        """Their provides lines' names, the ctx keys their code writes, and a dependency's SETTINGS keys when it
        writes ctx["values"] in a way whose keys can't be read (a loop over its SETTINGS)."""
        self.assertEqual(SI.dep_names([S1]), {"sofa_dim", "sofa_tea"})
        quiet = S1.replace("provides: sofa_dim, sofa_tea", "provides: none")
        self.assertEqual(SI.dep_names([quiet]), {"sofa_dim", "sofa_tea"})  # the loop: its SETTINGS keys
        self.assertEqual(SI.dep_names([S2]), {"chimera_sofa", "sofa"})
        self.assertEqual(SI.check("def (", ["s1"], {"s1": S1})["silent"], [])  # code that doesn't parse

    def test_the_tells_are_short_and_ours(self):
        keys = ["rotation_start_frame", "rotation_end_frame", "camera_focal_length", "fps"]
        found = {"marker": keys, "silent": [{"key": k, "line": 1, "function": None} for k in keys] +
                 [{"key": None, "line": 2, "function": "_s4_value"}]}
        lines = SI.tell(found)
        self.assertEqual(len(lines), 3)
        for line in lines:
            self.assertLessEqual(len(line), H.FAILURE_CHARS, line)
        self.assertTrue(lines[0].startswith('"rotation_start_frame" and more: '), lines[0])  # one key when long
        self.assertEqual(len(SI.TELL_FORMS), 4)  # the fourth, a missing file's (since the fifth smoke), told below
        for form in SI.TELL_FORMS[:3]:
            self.assertIn(form, " ".join(lines))
        for form in SI.TELL_FORMS:
            self.assertGreaterEqual(len(H._WORD.findall(form)), H.NOTE_N)
            self.assertNotIn("chimera: stand-in", form)  # Chimera's own call is a slot
            self.assertEqual(H.echoed_note("# " + form + "\n" + MARK), "failure_line", form)
        # a reply that marks its stand-in with Chimera's own call is no echo
        self.assertIsNone(H.echoed_note('    print("chimera: stand-in", key)\n    return SETTINGS_s4[key]\n' + MARK))


class AfterTheIndependentChecksTests(unittest.TestCase):
    """The independent checks of the round (Nov 6), on hand-made pieces that follow Chimera's rule: a marker printed by
    a stand-in helper the read hands its key to, by a %, + or .format string, or in the build_sN around (or calling)
    the helper or lambda that reads, covers the read; filler words before a key a variable gives are no key (11 of the
    first smoke's 258 Blender tries were read as marking "missing", "created", "object" or "setting"); chimera_ is
    stripped on both sides; a name bound to ctx["values"] is that function's; a loop over a literal list reads its
    strings as keys."""

    KEYS = '("sofa_dim", "sofa_tea")'
    READS = ('    w = vals.get("sofa_dim", SETTINGS_s2["sofa_dim"])\n'
             '    t = vals.get("sofa_tea", SETTINGS_s2["sofa_tea"])\n')
    SET2 = '{"sofa_dim": 2.2, "sofa_tea": (0, 0.5, 0.5)}'
    HELPER = ('\n\ndef _s2_stand_in(key):\n    print("chimera: stand-in", key)\n    return SETTINGS_s2[key]\n')

    def got(self, body, tail="", earlier=None):
        return SI.check(code(body, "s2", self.SET2) + tail, ["s1"], {"s1": S1} if earlier is None else earlier,
                        sid="s2")

    def test_a_marker_where_the_rule_puts_it_covers_the_read(self):
        loop = (f'    for key in {self.KEYS}:\n        if key not in ctx["values"]:\n'
                '            print("chimera: stand-in", key)\n')
        pieces = {
            "D": ('    vals = ctx["values"]\n    w = vals.get("sofa_dim") or _s2_stand_in("sofa_dim")\n'
                  '    t = vals.get("sofa_tea") or _s2_stand_in("sofa_tea")\n', self.HELPER),
            "E": ('    vals = ctx["values"]\n'
                  '    w = vals["sofa_dim"] if "sofa_dim" in vals else _s2_stand_in("sofa_dim")\n', self.HELPER),
            "E2": (f'    vals = ctx["values"]\n    for k in {self.KEYS}:\n        x = vals.get(k) or _s2_stand_in(k)\n',
                   self.HELPER),
            "A": (loop + '    w = _s2_value(ctx, "sofa_dim")\n    t = _s2_value(ctx, "sofa_tea")\n',
                  '\n\ndef _s2_value(ctx, key):\n    return ctx["values"].get(key, SETTINGS_s2[key])\n'),
            "B": ('    vals = ctx["values"]\n' + loop + '    get = lambda key: vals.get(key, SETTINGS_s2[key])\n'
                  f'    w, t = (get(k) for k in {self.KEYS})\n', ""),
            "C": ('    vals = ctx["values"]\n\n    def value(key):\n        return vals.get(key, SETTINGS_s2[key])\n'
                  '\n' + loop + '    w, t = value("sofa_dim"), value("sofa_tea")\n', "")}
        for form in ('print("chimera: stand-in %s" % key)', 'print("chimera: stand-in " + key)',
                     'print("chimera: stand-in {}".format(key))', 'print("chimera: stand-in for", key)',
                     'print(f"chimera: stand-in for missing value {key}")'):
            pieces[form] = (f'    vals = ctx["values"]\n    for key in {self.KEYS}:\n        if key not in vals:\n'
                            f'            {form}\n' + self.READS, "")
        for name, (body, tail) in pieces.items():
            found = self.got(body, tail)
            self.assertEqual((found["marker"], found["silent"]), ([], []), name)
        # the same reads with no marker at all are still silent defaults
        self.assertEqual([x["key"] for x in self.got('    vals = ctx["values"]\n' + self.READS)["silent"]],
                         ["sofa_dim", "sofa_tea"])
        bare = self.got('    w = _s2_value(ctx, "sofa_dim")\n',
                        '\n\ndef _s2_value(ctx, key):\n    return ctx["values"].get(key, SETTINGS_s2[key])\n')
        self.assertEqual(bare["silent"], [{"key": None, "line": 12, "function": "_s2_value"}])
        # a marker with a literal key (the fourth smoke's GPU fallback) covers no nested helper's read
        gpu = ('    vals = ctx["values"]\n\n    def get(key):\n        return vals.get(key, SETTINGS_s2[key])\n\n'
               '    w = get("sofa_dim")\n    print("chimera: stand-in render_device (fallback to CPU)")\n')
        self.assertEqual([(x["key"], x["function"]) for x in self.got(gpu)["silent"]], [(None, "get")])
        # a helper that prints the marker covers only the keys passed to it
        half = self.got('    vals = ctx["values"]\n    w = vals.get("sofa_dim") or _s2_stand_in("sofa_dim")\n'
                        '    t = vals.get("sofa_tea") or 1.0\n', self.HELPER)
        self.assertEqual([x["key"] for x in half["silent"]], ["sofa_tea"])

    def test_filler_words_are_no_key(self):
        """A key a variable gives after "for", "missing", "created", "object" and the like isn't judged; a word that
        is no filler still is (the fourth smoke's node-input marker), and so is a literal key after filler."""
        for line in ('print(f"chimera: stand-in for {k}")', 'print(f"chimera: stand-in for missing object \'{k}\'")',
                     'print(f"chimera: stand-in created for missing object \'{k}\'")',
                     'print(f"chimera: stand-in object created for missing key/name \'{k}\'")',
                     'print(f"chimera: stand-in missing object {k} - Wood not assigned")',
                     'print(f"chimera: stand-in for setting \'{k}\'")', 'print("chimera: stand-in for", k)'):
            body = f'    for k in ("sofa",):\n        if k not in ctx["objects"]:\n            {line}\n'
            for deps, earlier in ((["s2"], {"s2": S2}), (["s2"], {})):
                got = SI.check(code(body, "s3"), deps, earlier, sid="s3")
                self.assertEqual(got["marker"], [], (line, earlier))
                self.assertEqual([k for _, k, _ in SI.markers(SI._Reader(SI._parse(code(body, "s3"))))], [None], line)
        for line, key in (('print("chimera: stand-in created for missing \'Pulse_Curve\' object")', "Pulse_Curve"),
                          ('print("chimera: stand-in for", "sofa")', "sofa"),
                          ('print(f"chimera: stand-in input {name} not found on Principled BSDF")', "input"),
                          ('print(f"chimera: stand-in panel_array_group error: {e}")', "panel_array_group")):
            got = SI.markers(SI._Reader(SI._parse(code("    name = e = 1\n    " + line + "\n", "s3"))))
            self.assertEqual([k for _, k, _ in got], [key], line)

    def test_smaller_misreadings(self):
        # chimera_ on the looked-up side: the sofa found by its Blender name, the marker naming its ctx key
        body = ('    sofa = bpy.data.objects.get("chimera_sofa")\n    if sofa is None:\n'
                '        print("chimera: stand-in", "sofa")\n')
        self.assertEqual(SI.check(code(body, "s3"), ["s2"], {}, sid="s3")["marker"], [])
        # a helper's parameter named like build_s2's ctx["values"] alias is the helper's own dict
        finish = ('\n\ndef _s2_finish(mat, vals):\n    mat.roughness = vals.get("roughness", 0.5)\n'
                  '    mat.metallic = vals.get("metallic", 0.0)\n')
        aliased = ('    vals = ctx["values"]\n    for key in ("sofa_dim",):\n        if key not in vals:\n'
                   '            print("chimera: stand-in", key)\n    w = vals.get("sofa_dim", 2.2)\n'
                   '    _s2_finish(None, {"roughness": 0.8})\n')
        for earlier in ({"s1": S1}, {}):
            self.assertEqual(self.got(aliased, finish, earlier)["silent"], [], earlier)
        # the alias still reaches a nested function or lambda that reads it
        nested = '    vals = ctx["values"]\n    get = lambda key: vals.get(key, 1.0)\n    w = get("sofa_dim")\n'
        self.assertEqual(self.got(nested)["silent"], [{"key": None, "line": 9, "function": None}])
        # a loop over a literal list: keys no present dependency hands on are excused, as the same reads with
        # literal keys are; a dependency's keys in it are silent defaults, by name
        own = '    for k in ("seat_h", "leg_r"):\n        x = ctx["values"].get(k, SETTINGS_s2.get(k))\n'
        self.assertEqual(self.got(own)["silent"], [])
        theirs = own.replace('("seat_h", "leg_r")', '("seat_h", "sofa_dim")')
        self.assertEqual([x["key"] for x in self.got(theirs)["silent"]], ["sofa_dim"])
        self.assertEqual([x["key"] for x in self.got(own, earlier={})["silent"]], ["seat_h", "leg_r"])  # s1 dropped


class SecondChecksTests(unittest.TestCase):
    """The second checks (Nov 6), on hand-made pieces: a marker covers a values read in another function only when it
    is the values' own (a marker loop under a ctx["values"] test), and then also the keys it loops over wherever they
    are read; a marker with no key covers nothing; a helper's parameter every call fills with ctx["values"] is
    ctx["values"]; a key is handed to a stand-in helper only as the same name bound the same way; a stand-in helper may
    print its key through repr() or a .format keyword."""

    SET2 = AfterTheIndependentChecksTests.SET2
    KEYS = AfterTheIndependentChecksTests.KEYS
    HELPER = AfterTheIndependentChecksTests.HELPER
    OBJECTS = ('    for key in ("sofa",):\n        if key not in ctx["objects"]:\n'
               '            print("chimera: stand-in", key)\n')  # an object's marker loop, as stored pieces aim at one
    VALUES = (f'    for key in {KEYS}:\n        if key not in ctx["values"]:\n'
              '            print("chimera: stand-in", key)\n')
    VALUE = '\n\ndef _s2_value(ctx, key):\n    return ctx["values"].get(key, SETTINGS_s2[key])\n'

    def rows(self, body, tail="", earlier=None):
        found = SI.check(code(body, "s2", self.SET2) + tail, ["s1"], {"s1": S1} if earlier is None else earlier,
                         sid="s2")
        return [(x["key"], x["function"]) for x in found["silent"]]

    def test_an_objects_marker_loop_covers_no_values_read_elsewhere(self):
        nested = '\n    def get(key):\n        return ctx["values"].get(key, SETTINGS_s2[key])\n\n    w = get("sofa_dim")\n'
        top = '    w = _s2_value(ctx, "sofa_dim")\n'
        for earlier in ({"s1": S1}, {}):
            self.assertEqual(self.rows(self.OBJECTS + nested, earlier=earlier), [(None, "get")])
            self.assertEqual(self.rows(self.OBJECTS + top, self.VALUE, earlier), [(None, "_s2_value")])
            # a marker with no key around the read covers nothing either
            dash = '    if ctx["objects"].get("sofa") is None:\n        print("chimera: stand-in – sofa not found")\n'
            self.assertEqual(self.rows(dash + nested, earlier=earlier), [(None, "get")])
            # the values' own marker loop in build_s2 still covers them
            self.assertEqual(self.rows(self.VALUES + nested, earlier=earlier), [])
            self.assertEqual(self.rows(self.VALUES + top, self.VALUE, earlier), [])
            # and so does any marker with a variable's key in the read's own function, as in the round
            self.assertEqual(self.rows(self.OBJECTS + '    w = ctx["values"].get("sofa_dim", 2.2)\n',
                                       earlier=earlier), [])

    def test_a_marker_with_no_key_covers_nothing(self):
        read = '    w = ctx["values"].get("sofa_dim", 2.2)\n'
        for line in ('print("chimera: stand-in – sofa not found, aiming at a placeholder")',
                     'print("chimera: stand-in")', 'print("chimera: stand-in for missing object")'):
            self.assertEqual(self.rows(f'    if ctx["objects"].get("sofa") is None:\n        {line}\n' + read),
                             [("sofa_dim", "build_s2")], line)
        # a key the marker names, a literal or a variable's, still covers the read as before
        for line in ('print("chimera: stand-in", "sofa_dim")', 'print("chimera: stand-in", key)'):
            body = f'    for key in ("sofa_dim",):\n        if key not in ctx["values"]:\n            {line}\n' + read
            self.assertEqual(self.rows(body), [], line)

    def test_a_keyless_marker_on_a_step_with_no_dependency_is_misused(self):
        """A step with no dependency has nothing to stand in for: a marker with no key (the first smoke's GPU, DOF and
        SVG fallbacks, a dash before their words) is misused as a keyed one is, its tell quoting its own words; a
        variable's key there is still not judged, nor is a keyless marker on a step with a dependency."""
        gpu = ('    try:\n        bpy.context.scene.cycles.device = "GPU"\n    except Exception:\n'
               '        print("chimera: stand-in – GPU unavailable, falling back to CPU")\n')
        found = SI.check(code(gpu, "s1"), [], {}, sid="s1")
        self.assertEqual(found["marker"], ["GPU unavailable, falling back to CPU"])
        self.assertEqual(SI.tell(found), [SI.MARKER_TELL.format(quotes='"GPU unavailable, falling back to CPU"')])
        for line, want in (('print("chimera: stand-in")', "chimera: stand-in"),
                           ('print("chimera: stand-in (using SETTINGS_s1 defaults)")', "using SETTINGS_s1 defaults"),
                           ('print("chimera: stand-in", "")', "chimera: stand-in"),
                           ('print(f"chimera: stand-in {e}")', None)):
            body = "    e = 1\n    " + line + "\n"
            self.assertEqual(SI.check(code(body, "s1"), [], {}, sid="s1")["marker"], [want] if want else [], line)
        self.assertEqual(SI.check(code(gpu, "s3"), ["s2"], {"s2": S2}, sid="s3")["marker"], [])

    def test_keyless_lists_the_markers_with_no_key_for_the_report(self):
        """keyless, which report.after_audit counts on steps with a dependency (the one decision the second checks
        left): every marker with neither a literal key nor a variable's, its own words; none for a keyed marker or
        code that doesn't parse."""
        gpu = ('    try:\n        bpy.context.scene.cycles.device = "GPU"\n    except Exception:\n'
               '        print("chimera: stand-in – GPU unavailable, falling back to CPU")\n')
        self.assertEqual(SI.keyless(code(gpu + '    print("chimera: stand-in")\n', "s3")),
                         ["GPU unavailable, falling back to CPU", "chimera: stand-in"])
        for line in ('print("chimera: stand-in", "sofa_dim")', 'print("chimera: stand-in", key)',
                     'print(f"chimera: stand-in {key}")', 'print("chimera: stand-in sofa_dim")'):
            self.assertEqual(SI.keyless(code(f'    key = "sofa_dim"\n    {line}\n', "s3")), [], line)
        self.assertEqual(SI.keyless("def build_s3(ctx:\n"), [])

    def test_a_parameter_every_call_fills_with_the_values(self):
        helper = ('\n\ndef _s2_sizes(vals):\n    return vals.get("sofa_dim", 2.2), vals.get("sofa_tea", (0, 0.5, 0.5))\n')
        want = [("sofa_dim", "_s2_sizes"), ("sofa_tea", "_s2_sizes")]
        self.assertEqual(self.rows('    vals = ctx["values"]\n    w, t = _s2_sizes(vals)\n', helper), want)
        self.assertEqual(self.rows('    w, t = _s2_sizes(ctx["values"])\n', helper), want)
        self.assertEqual(self.rows('    w, t = _s2_sizes(vals=ctx.get("values", {}))\n', helper), want)
        # a call with another dict, or a parameter the helper binds again, isn't ctx["values"]
        self.assertEqual(self.rows('    w, t = _s2_sizes(ctx["values"])\n    _s2_sizes({"sofa_dim": 1.0})\n', helper),
                         [])
        again = helper.replace("(vals):\n", "(vals):\n    vals = dict(vals)\n")
        self.assertEqual(self.rows('    w, t = _s2_sizes(ctx["values"])\n', again), [])

    def test_a_key_handed_to_a_stand_in_helper_is_the_same_name(self):
        body = ('    vals = ctx["values"]\n    for k in ("sofa",):\n        if k not in ctx["objects"]:\n'
                '            ctx["objects"][k] = _s2_stand_in(k)\n'
                f'    for k in {self.KEYS}:\n        x = vals.get(k, SETTINGS_s2[k])\n')
        self.assertEqual(self.rows(body, self.HELPER), [("sofa_dim", "build_s2"), ("sofa_tea", "build_s2")])
        # in the loop that binds it, it is (the independent checks' E2)
        same = f'    vals = ctx["values"]\n    for k in {self.KEYS}:\n        x = vals.get(k) or _s2_stand_in(k)\n'
        self.assertEqual(self.rows(same, self.HELPER), [])

    def test_more_stand_in_idioms(self):
        # a sibling helper build_s2 calls loops over the keys under a ctx["values"] test; the reads go through another
        sibling = (f'\n\ndef _s2_report(ctx):\n    for key in {self.KEYS}:\n        if key not in ctx["values"]:\n'
                   '            print("chimera: stand-in", key)\n' + self.VALUE)
        body = '    _s2_report(ctx)\n    w = _s2_value(ctx, "sofa_dim")\n    t = _s2_value(ctx, "sofa_tea")\n'
        for earlier in ({"s1": S1}, {}):
            self.assertEqual(self.rows(body, sibling, earlier), [])
            self.assertEqual(self.rows(body + '    z = _s2_value(ctx, "sofa_len")\n', sibling, earlier),
                             [(None, "_s2_value")] if not earlier else [])
        # over SETTINGS_s2's keys, as hydra's values steps loop
        settings = sibling.replace(f"for key in {self.KEYS}:", "for key in SETTINGS_s2:")
        self.assertEqual(self.rows(body, settings), [])
        # a stand-in helper that prints its key through repr() or a .format keyword
        reads = ('    vals = ctx["values"]\n    w = vals.get("sofa_dim") or _s2_stand_in("sofa_dim")\n'
                 '    t = vals.get("sofa_tea") or _s2_stand_in("sofa_tea")\n')
        for line in ('print("chimera: stand-in", repr(key))', 'print("chimera: stand-in {key}".format(key=key))',
                     'print("chimera: stand-in {0}".format(key))', 'print("chimera: stand-in %s" % str(key))'):
            self.assertEqual(self.rows(reads, self.HELPER.replace('print("chimera: stand-in", key)', line)), [], line)
        self.assertEqual(self.rows(reads, self.HELPER.replace('print("chimera: stand-in", key)',
                                                              'print("chimera: stand-in {k}".format(k="sofa"))')),
                         [("sofa_dim", "build_s2"), ("sofa_tea", "build_s2")])


class MissingFileTests(unittest.TestCase):
    """After the fifth smoke (Nov 6): a misused marker for an input file the piece can't find (an SVG, an HDRI, a font,
    an SVG import that gave nothing; smoke5's blender-0008-00 s1 and s3, blender-0002-02 s1, in the shapes they were
    written) is told what to print instead (MARKER_FILE_TELL): a plain line of the piece's own naming the file. The
    reason is marker_misused as before, and a marker for anything else keeps MARKER_TELL."""

    FILES = {
        "svg_path": '    svg_path = SETTINGS_s1["svg_path"]\n    if not os.path.isfile(svg_path):\n'
                    '        print("chimera: stand-in", "svg_path")\n        return\n'
                    '    bpy.ops.import_curve.svg(filepath=svg_path)\n',
        "hdri_path": '    hdri_path = SETTINGS_s1["hdri_path"]\n    if os.path.isfile(hdri_path):\n'
                     '        img = bpy.data.images.load(hdri_path)\n    else:\n'
                     '        print("chimera: stand-in", "hdri_path")\n',
        "env_image": '    try:\n        img = bpy.data.images.load(SETTINGS_s1["hdri_path"])\n'
                     '    except Exception as e:\n        print("chimera: stand-in", "env_image")\n',
        "font_path": '    font_path = SETTINGS_s1["font_path"]\n    if os.path.isfile(font_path):\n'
                     '        cu.font = bpy.data.fonts.load(font_path)\n    else:\n'
                     '        print("chimera: stand-in font_path")\n',
        "acme.svg": '    def _s1_logo():\n        return bpy.ops.import_curve.svg(filepath="//acme.svg")\n'
                    '    if have:\n        pass\n    else:\n        print("chimera: stand-in", "acme.svg")\n',
        "imported_svg": '    before = set(bpy.data.objects)\n'
                        '    bpy.ops.import_curve.svg(filepath=SETTINGS_s1["svg"])\n'
                        '    new = [o for o in bpy.data.objects if o not in before]\n    if not new:\n'
                        '        print("chimera: stand-in", "imported_svg")\n'}
    OTHERS = {
        "render_device": '    try:\n        bpy.context.scene.cycles.device = "GPU"\n    except Exception:\n'
                         '        print("chimera: stand-in render_device (fallback to CPU)")\n',
        "font_name": '    font = bpy.data.fonts.get(SETTINGS_s1["font_name"])\n    if not font:\n'
                     '        print("chimera: stand-in font_name")\n',
        # a font loaded in a helper the step defines, before an unrelated marker: the helper's load isn't run there
        "collection": '    def _s1_font(p):\n        return bpy.data.fonts.load(p)\n'
                      '    coll = ctx.get("collection")\n    if coll is None:\n'
                      '        print("chimera: stand-in collection")\n'}

    def test_a_marker_for_a_missing_file_is_told_the_plain_print(self):
        for key, body in self.FILES.items():
            found = SI.check(code("    import os\n" + body, "s1"), [], {}, sid="s1")
            self.assertEqual((found["marker"], found["files"]), ([key], [key]), key)
            (line,) = SI.tell(found)
            self.assertEqual(line, SI.MARKER_FILE_TELL.format(quotes='"%s"' % key), key)
            self.assertIn("say so in a plain print instead, naming the file", line)
            self.assertLessEqual(len(line), H.FAILURE_CHARS)
            # the gate's reason is the same, and its tell is the file's
            facts = BG.build_facts(PLAN, 3, code("    import os\n" + body, "s4"), warned())
            self.assertEqual(facts["reasons"], ["marker_misused"], key)
            self.assertEqual(facts["tell"], [SI.MARKER_FILE_TELL.format(quotes='"%s"' % key)], key)
        for key, body in self.OTHERS.items():
            found = SI.check(code(body, "s1"), [], {}, sid="s1")
            self.assertEqual((found["marker"], found["files"]), ([key], []), key)
            self.assertEqual(SI.tell(found), [SI.MARKER_TELL.format(quotes='"%s"' % key)], key)

    def test_a_piece_with_both_gets_both_lines(self):
        body = self.FILES["svg_path"] + self.OTHERS["render_device"]
        found = SI.check(code("    import os\n" + body, "s1"), [], {}, sid="s1")
        self.assertEqual((found["marker"], found["files"]), (["svg_path", "render_device"], ["svg_path"]))
        self.assertEqual(SI.tell(found), [SI.MARKER_FILE_TELL.format(quotes='"svg_path"'),
                                          SI.MARKER_TELL.format(quotes='"render_device"')])
        # a dependency's key the piece looks up is no misuse, file test or not
        dep = ('    logo = ctx["objects"].get("Acme_Logo")\n    if logo is None or not os.path.exists("x.svg"):\n'
               '        print("chimera: stand-in", "Acme_Logo")\n')
        got = SI.check(code("    import os\n" + dep, "s3"), ["s1"], {}, sid="s3")
        self.assertEqual((got["marker"], got["files"]), ([], []))

    def test_an_output_or_another_test_after_a_load_is_no_input_file(self):
        """The checks of Nov 6: a GPU test after an HDRI's load in the same block (blender-0008-00 s3's shape), an
        output folder tested before the piece makes it, a video's name with its extension and a file opened for
        writing were read as missing input files, and told MARKER_FILE_TELL; only what the piece reads in is one."""
        hdri_gpu = (self.FILES["hdri_path"] + '    prefs = bpy.context.preferences.addons["cycles"].preferences\n'
                    '    if not any(d.type != "CPU" for d in prefs.devices):\n'
                    '        print("chimera: stand-in", "render_device")\n')
        found = SI.check(code("    import os\n" + hdri_gpu, "s3"), [], {}, sid="s3")
        self.assertEqual((found["marker"], found["files"]), (["hdri_path", "render_device"], ["hdri_path"]))
        self.assertEqual(SI.tell(found), [SI.MARKER_FILE_TELL.format(quotes='"hdri_path"'),
                                          SI.MARKER_TELL.format(quotes='"render_device"')])
        # ... while a test of what the load gave is the file's, through a name bound to it (mesh_objs from new_objs)
        gave = ('    before = set(bpy.data.objects)\n    bpy.ops.import_curve.svg(filepath=SETTINGS_s1["svg"])\n'
                '    new_objs = [o for o in bpy.data.objects if o not in before]\n'
                '    mesh_objs = [o for o in new_objs if o.type == "MESH"]\n    if len(mesh_objs) == 0:\n'
                '        print("chimera: stand-in", "no_mesh")\n')
        self.assertEqual(SI.check(code(gave, "s1"), [], {}, sid="s1")["files"], ["no_mesh"])
        outputs = ('    out_dir = bpy.path.abspath("//renders")\n    if not os.path.exists(out_dir):\n'
                   '        print("chimera: stand-in", "output_dir")\n        os.makedirs(out_dir)\n'
                   '    log = os.path.join(out_dir, "log.txt")\n    if not os.path.exists(log):\n'
                   '        print("chimera: stand-in", "log_file")\n    with open(log, "a") as f:\n'
                   '        f.write("start")\n'
                   '    ctx["scene"].render.filepath = "//renders/acme_turntable.mp4"\n'
                   '    if not ctx["scene"].render.filepath:\n'
                   '        print("chimera: stand-in", "acme_turntable.mp4")\n')
        for extra in ("", self.FILES["hdri_path"]):  # also in a piece that reads an HDRI in
            found = SI.check(code("    import os\n" + extra + outputs, "s5"), [], {}, sid="s5")
            want = (["hdri_path"] if extra else []) + ["output_dir", "log_file", "acme_turntable.mp4"]
            self.assertEqual((found["marker"], found["files"]), (want, want[:1] if extra else []), extra[:20])
            self.assertIn(SI.fitted(SI.MARKER_TELL, ["output_dir", "log_file", "acme_turntable.mp4"]),
                          SI.tell(found))
        # a path the piece reads with open() or a helper of its own is an input
        read = ('    def _s1_read(p):\n        with open(p) as f:\n            return f.read()\n'
                '    names = SETTINGS_s1["names_file"]\n    if not os.path.isfile(names):\n'
                '        print("chimera: stand-in", "names_file")\n    else:\n        text = _s1_read(names)\n')
        self.assertEqual(SI.check(code("    import os\n" + read, "s1"), [], {}, sid="s1")["files"], ["names_file"])

    def test_the_file_tell_is_ours_and_agrees_with_chimeras_rule(self):
        from contract import texts
        form = SI.TELL_FORMS[-1]
        self.assertTrue(SI.MARKER_FILE_TELL.endswith(form))
        self.assertIn(form, BG.TELL_FORMS)
        self.assertEqual(H.echoed_note("# " + form + "\n" + MARK), "failure_line")
        self.assertNotIn("chimera: stand-in", SI.MARKER_FILE_TELL)
        self.assertIn("missing dependency's ctx key", SI.MARKER_FILE_TELL)  # what Chimera's rule says it is for
        n, sh = H._shingles(form)
        chimeras = [v for v in vars(texts).values() if isinstance(v, str) and len(v) > 40]
        chimeras += [texts.fill(texts.MODE_BLENDER, sid="s%d" % k) for k in range(1, 9)]
        for text in chimeras:
            self.assertFalse(H.runs(text, n) & sh, text[:60])
        self.assertIsNone(H.echoed_note('    print("no SVG at", svg_path, "- using a built-in shape")\n' + MARK))


# A plan as hydra:1.0 opens a Blender task: a values step s1 (values_step: its title, and s2 depends on it), a sofa, a
# light that depends on the sofa only, and a render step that depends on nothing
PLAN = {"title": "Room " + MARK, "kind": "blender", "summary": MARK, "steps": [
    {"id": "s1", "title": "Define dimensions and colours", "kind": "blender", "depends_on": [],
     "instructions": "Sofa 2.2 m wide, teal. " + MARK},
    {"id": "s2", "title": "Sofa", "kind": "blender", "depends_on": ["s1"], "instructions": "Build the sofa. " + MARK},
    {"id": "s3", "title": "Lights", "kind": "blender", "depends_on": ["s2"], "instructions": "Light it. " + MARK},
    {"id": "s4", "title": "Render", "kind": "blender", "depends_on": [],
     "instructions": "Render the room to //room.png. " + MARK}]}
NAMES = ", ".join("value_%02d" % k for k in range(30))  # a plain list of 30 names, over Chimera's 300
NOTED = "chimera_sofa (2.2 x 0.9 x 0.8 m, teal), chimera_table (1.2 m walnut), " + "a long note " * 20


def warned(*issues, provides="none", uses="none", assumed="none"):
    """A verdict as Chimera's validator gives it, with these (code, message) warnings."""
    return {"ok": True, "form_ok": True, "issues": [{"level": "warn", "code": c, "message": m, "line": 0}
                                                     for c, m in issues],
            "handoff": {"provides": provides, "uses": uses, "assumed": assumed}}


def long_msg(line, value):
    return "the %s line has %d characters; the contract asks for one short line" % (line, len(value))


def warning_rows():
    """One warning_faults row for each of BUILD_TELL_FORMS' warning and long-line forms, in their order: the provides
    line's (its two runs), its own-stand-in form, both uses forms, then the long provides (noted), the long plain
    list on a step that isn't a values step, the long uses line and the long assumed line."""
    reg = 'registers ctx["values"] key(s) sofa_width, sofa_tea that provides doesn\'t list'
    own = 'registers ctx["objects"] key(s) sofa that provides doesn\'t list'
    own_code = 'if "sofa" not in ctx["objects"]:\n    ctx["objects"]["sofa"] = None\n'
    rows = BG.warning_faults(warned(("provides_missing", reg)), PLAN, 1, "")
    rows = rows + rows + BG.warning_faults(warned(("provides_missing", own)), PLAN, 2, own_code)
    rows += BG.warning_faults(warned(("uses_undeclared", "uses names s1, earlier steps it doesn't depend on (it "
                                                         "depends on s2)")), PLAN, 2, "")
    rows += BG.warning_faults(warned(("uses_undeclared", "uses names s1, earlier steps it doesn't depend on (it "
                                                         "depends on nothing)")), PLAN, 3, "")
    rows += BG.warning_faults(warned(("handoff_long", long_msg("provides", NOTED)), provides=NOTED), PLAN, 1, "")
    rows += BG.warning_faults(warned(("handoff_long", long_msg("provides", NAMES)), provides=NAMES), PLAN, 1, "")
    rows += BG.warning_faults(warned(("handoff_long", long_msg("uses", NOTED)), uses=NOTED), PLAN, 2, "")
    rows += BG.warning_faults(warned(("handoff_long", long_msg("assumed", NOTED)), assumed=NOTED), PLAN, 2, "")
    return rows


class BuildFactsTests(unittest.TestCase):

    def test_the_warnings_and_their_tells(self):
        rows = warning_rows()
        self.assertEqual([r["code"] for r in rows], ["provides_missing"] * 3 + ["uses_undeclared"] * 2 +
                         ["handoff_long"] * 4)
        self.assertEqual((rows[0]["channel"], rows[0]["keys"], rows[0]["own"]), ("values", ["sofa_width", "sofa_tea"],
                                                                                 False))
        self.assertEqual(rows[0]["tell"], 'ctx["values"] gets "sofa_width", "sofa_tea" from the piece, but its '
                                          'provides line doesn\'t name them: list under provides each key a later '
                                          'step reads, and leave out of ctx["values"] the ones none does')
        self.assertTrue(rows[2]["own"])  # the piece's own stand-in, registered where it found none
        self.assertTrue(rows[2]["tell"].startswith('"sofa" in ctx["objects"]: the piece registers its own stand-in'))
        self.assertEqual((rows[3]["steps"], rows[3]["deps"]), (["s1"], ["s2"]))
        self.assertTrue(rows[3]["tell"].endswith("(the uses line names s1; it depends on s2)"), rows[3]["tell"])
        self.assertEqual(rows[4]["deps"], [])
        self.assertIn("since this one depends on none", rows[4]["tell"])
        self.assertTrue(rows[5]["tell"].startswith("the provides line has %d characters, past the 300 Chimera warns "
                                                   "at: give only the exact names" % len(NOTED)), rows[5]["tell"])
        self.assertIn(BG.LONG_ADVICE["provides_list"], rows[6]["tell"])  # a plain list, but s2 is no values step
        self.assertIn(BG.LONG_ADVICE["uses"], rows[7]["tell"])
        self.assertIn(BG.LONG_ADVICE["assumed"], rows[8]["tell"])
        self.assertFalse(any(r["exempt"] for r in rows))
        for r in rows:
            self.assertLessEqual(len(r["tell"]), H.FAILURE_CHARS, r["tell"])
        # a message the record cut at 200 characters: the keys are worked out from the code
        cut = 'registers ctx["values"] key(s) ' + ", ".join("k%02d" % n for n in range(60))
        code = "".join('ctx["values"]["k%02d"] = 1\n' % n for n in range(60))
        row, = BG.warning_faults(warned(("provides_missing", cut[:200]), provides="k00, k01"), PLAN, 1, code)
        self.assertEqual(row["keys"][:2], ["k02", "k03"])
        self.assertEqual(len(row["keys"]), 58)  # k00 and k01 are listed (a substring test on provides, as Go's)
        # other warnings and errors are no build drop
        self.assertEqual(BG.warning_faults(warned(("handoff_wordy", "uses says ...")), PLAN, 1, ""), [])
        self.assertEqual(BG.warning_faults(None, PLAN, 1, ""), [])

    def test_a_values_steps_long_list_is_left_as_it_was(self):
        """The user's open contract question (handoffLineMax 300 against the 19-20 keys a values step names): no
        reason and no tell, and nothing else fails such a piece, whatever the line's form (decided Nov 6: from Nov 5
        only a plain list was, so the same keys behind a lead, grouped or with a note got the reason and its tell);
        the same line on any other step is told, and no tell a values step can get asks it to shorten its list."""
        v = warned(("handoff_long", long_msg("provides", NAMES)), provides=NAMES)
        row, = BG.warning_faults(v, PLAN, 0, "")
        self.assertEqual((row["exempt"], row["tell"], row["line"], row["chars"]), (True, None, "provides", len(NAMES)))
        dead = 'SETTINGS_s1 = {"sofa": 2.2, "render_path": "//room.png"}\n'
        marker = 'def build_s1(ctx):\n    print("chimera: stand-in render_device (fallback to CPU)")\n'
        f = BG.build_facts(PLAN, 0, dead + marker, v, {})
        self.assertEqual((f["reasons"], f["waived"]), ([], True))  # the build drops it for handoff_long whatever else
        self.assertEqual(f["dead_output"], ["render_path"])
        self.assertEqual(len(f["tell"]), 2)  # told only if something else fails it
        self.assertEqual(BG.build_facts(PLAN, 0, dead + marker, warned(), {})["reasons"],
                         ["dead_output_key", "marker_misused"])  # not waived without it
        # the same list on s2, which is no values step, is told, plain or not
        self.assertEqual(BG.build_facts(PLAN, 1, "", v, {})["reasons"], ["validator_warning:handoff_long"])
        noted = warned(("handoff_long", long_msg("provides", NOTED)), provides=NOTED)
        f = BG.build_facts(PLAN, 1, "", noted, {})
        self.assertEqual(f["reasons"], ["validator_warning:handoff_long"])
        self.assertIn(BG.LONG_ADVICE["provides"], f["tell"][0])
        # a values step's line in any other form is left as it was too, with what else the build drops it for:
        # behind a lead, grouped, with a note, sizes, or the stored kind of note (the independent checks' forms)
        keys = ["value_%02d" % k for k in range(30)]
        forms = {"lead": 'ctx["values"]: ' + ", ".join(keys),
                 "keys word": 'ctx["values"] keys ' + ", ".join(keys),
                 "grouped": "sizes: " + ", ".join(keys[:20]) + "; colours: " + ", ".join(keys[20:]),
                 "note": ", ".join(keys) + ' (all in ctx["values"]).',
                 "sizes": ", ".join("%s = 1.0" % k for k in keys), "noted": NOTED}
        for name, line in forms.items():
            with self.subTest(name):
                self.assertGreater(len(line), BG.HANDOFF_MAX)
                w = warned(("handoff_long", long_msg("provides", line)), provides=line)
                row, = BG.warning_faults(w, PLAN, 0, "")
                self.assertEqual((row["exempt"], row["tell"]), (True, None))
                f = BG.build_facts(PLAN, 0, dead + marker, w, {})
                self.assertEqual((f["reasons"], f["waived"]), ([], True))
                self.assertFalse(any(t in x for t in BG.LONG_ADVICE.values() for x in f["tell"]))
                f = BG.build_facts(PLAN, 1, "", w, {})  # not a values step: the reason and its tell
                self.assertEqual((f["reasons"], f["waived"]), (["validator_warning:handoff_long"], False))
                self.assertTrue(f["tell"][0].startswith("the provides line has %d characters" % len(line)))
        # no tell a values step's piece can get asks it to shorten its list or to register less: provides_missing
        # asks it to list its keys, which then is the exempt plain list
        reg = 'registers ctx["values"] key(s) %s that provides doesn\'t list' % NAMES
        f = BG.build_facts(PLAN, 0, "", warned(("provides_missing", reg)), {})
        self.assertEqual(f["reasons"], ["validator_warning:provides_missing"])
        self.assertIn("list under provides each key a later step reads", f["tell"][0])
        listed = warned(("handoff_long", long_msg("provides", NAMES)), provides=NAMES)
        self.assertEqual(BG.build_facts(PLAN, 0, "", listed, {})["reasons"], [])
        for t in BG.LONG_ADVICE.values():
            self.assertFalse(any(t in x for x in f["tell"]))
        # the plain lists: names, with a note in brackets, dotted, quoted, ctx's, "and"; not sizes or prose
        for line in (NAMES, "a, b (via ctx[\"collection\"]), c", 'ctx["values"]["a"], `b`, c.d and e', "a; b"):
            self.assertTrue(BG.plain_names(line), line)
        for line in (NOTED, "all sizes from SETTINGS_s1", "a, b c", ""):
            self.assertFalse(BG.plain_names(line), line)

    def test_dead_output_keys(self):
        code = 'SETTINGS_s%d = {"size": 1, "output_path": "//room.png"}\n'
        f = BG.build_facts(PLAN, 1, code % 2, warned(), {})
        self.assertEqual((f["reasons"], f["dead_output"]), (["dead_output_key"], ["output_path"]))
        self.assertEqual(f["tell"], [BG.dead_tell("s2", ["output_path"], asked=False)])
        self.assertTrue(f["tell"][0].startswith('"output_path" in SETTINGS_s2 names an output, but the step asks for '
                                                'no saved file or render: leave that key out'))
        f = BG.build_facts(PLAN, 3, code % 4, warned(), {})  # s4 asks for a render: put it under "output"
        self.assertEqual(f["tell"], [BG.dead_tell("s4", ["output_path"])])
        self.assertIn('keep the path in "output" alone', f["tell"][0])
        sets = dict(PLAN, steps=PLAN["steps"][:1] + [dict(PLAN["steps"][1], instructions="Set the output path to "
                                                                                         "//renders/. " + MARK)])
        self.assertEqual(BG.build_facts(sets, 1, code % 2 + 'p = SETTINGS_s2["output_path"]\n', warned(), {})
                         ["reasons"], [])  # a step that asks to set the output path itself
        self.assertEqual(BG.build_facts(PLAN, 1, 'SETTINGS_s2 = {"output": "//x.png"}\n', warned(), {})["reasons"], [])

    def test_an_input_file_is_no_dead_output(self):
        """The independent checks (Nov 6): a texture, HDRI or font the step names, kept under a *_filepath key and
        handed to a loader (or a font or a sound by its kind), is a file the piece reads in, not an output; a render's
        path read into scene.render is still dead."""
        step = dict(PLAN["steps"][2], instructions="Give the shade the linen texture at //textures/linen.png. " + MARK)
        plan = dict(PLAN, steps=PLAN["steps"][:2] + [step] + PLAN["steps"][3:])
        for body in ('    img = bpy.data.images.load(SETTINGS_s3["shade_texture_filepath"], check_existing=True)\n',
                     '    p = bpy.path.abspath(SETTINGS_s3["shade_texture_filepath"])\n'
                     '    img = bpy.data.images.load(filepath=p)\n',
                     '    with bpy.data.libraries.load(SETTINGS_s3["shade_texture_filepath"]) as (src, dst):\n'
                     '        pass\n'):
            src = code(body, "s3", '{"shade_texture_filepath": "//textures/linen.png"}')
            f = BG.build_facts(plan, 2, src, warned(), {"s2": S2})
            self.assertEqual((f["dead_output"], f["reasons"]), ([], []), body)
        # the second checks (Nov 6): through a helper of the piece that loads it, given the key or the value kept there
        for helper, call in (('def _s3_image(key):\n    path = bpy.path.abspath(SETTINGS_s3[key])\n'
                              '    return bpy.data.images.load(path, check_existing=True)\n',
                              '_s3_image("shade_texture_filepath")'),
                             ('def _s3_load(path):\n    return bpy.data.images.load(path)\n',
                              '_s3_load(SETTINGS_s3["shade_texture_filepath"])')):
            src = code('    img = ' + call + '\n    ctx["scene"].render.filepath = SETTINGS_s3["render_filepath"]\n', "s3",
                       '{"shade_texture_filepath": "//textures/linen.png", "render_filepath": "//room.png"}')
            src = src.replace("\n\ndef build_s3", "\n\n" + helper + "\n\ndef build_s3")
            self.assertEqual(BG.dead_output_key(src, "s3", step), ["render_filepath"], helper)
            # a helper whose parameter loads nothing spares nothing
            other = src.replace("bpy.data.images.load(path", "print(path")
            self.assertEqual(BG.dead_output_key(other, "s3", step), ["render_filepath", "shade_texture_filepath"],
                             helper)
        font = code('    pass\n', "s3", '{"font_filepath": "//fonts/sign.ttf"}')
        self.assertEqual(BG.dead_output_key(font, "s3"), [])
        render = code('    bpy.context.scene.render.filepath = SETTINGS_s3["render_filepath"]\n', "s3",
                      '{"render_filepath": "//room.png"}')
        self.assertEqual(BG.dead_output_key(render, "s3"), ["render_filepath"])

    def test_a_get_or_create_of_the_steps_own_object_is_told_to_list_it(self):
        """The independent checks (Nov 6): s3 gets or makes its own floor_lamp, which its provides line forgot; no
        dependency hands floor_lamp on, so the plain provides tell lists it, not the stand-in tell. With s2 dropped, or
        when s2 does hand it on, it is a stand-in for a dependency's key."""
        msg = 'registers ctx["objects"] key(s) floor_lamp that provides doesn\'t list'
        own = ('if "floor_lamp" in ctx["objects"]:\n    lamp = ctx["objects"]["floor_lamp"]\nelse:\n'
               '    ctx["objects"]["floor_lamp"] = lamp = None\n')
        handing = S2.replace('provides: chimera_sofa as ctx["objects"]["sofa"]',
                             'provides: chimera_sofa as ctx["objects"]["sofa"], floor_lamp')
        f = BG.build_facts(PLAN, 2, own, warned(("provides_missing", msg)), {"s2": S2})
        self.assertTrue(f["tell"][0].startswith('ctx["objects"] gets "floor_lamp" from the piece'), f["tell"])
        for earlier, stand_in in (({"s2": S2}, False), ({}, True), ({"s2": handing}, True), (None, True)):
            row, = BG.warning_faults(warned(("provides_missing", msg)), PLAN, 2, own, earlier)
            self.assertEqual(row["own"], stand_in, earlier)
            self.assertEqual(row["tell"].startswith('"floor_lamp" in ctx["objects"]: the piece registers its own'),
                             stand_in, row["tell"])

    def test_soft_on_a_used_step_as_ctx_channel(self):
        for reasons in (["validator_warning:provides_missing"], ["dead_output_key"], ["marker_misused"],
                        ["silent_default"], ["ctx_channel", "dead_output_key", "validator_warning:handoff_long"]):
            self.assertTrue(T.soft(reasons, used=True), reasons)
            self.assertFalse(T.soft(reasons), reasons)
            self.assertEqual(T._blender_stage(reasons), "alone")
            self.assertEqual(BG._hard(reasons), [])  # they go on to the joined check
        self.assertTrue(T.soft(["output_missing", "dead_output_key"], used=True))
        self.assertFalse(T.soft(["alone_strict:5.2.2", "dead_output_key"], used=True))
        self.assertEqual(BG._hard(["provides_missing", "validator_warning:provides_missing"]), ["provides_missing"])
        # what the gate's tell lines say, once, after ctx_tell's and before the measured faults
        out = {"ok": False, "reasons": ["dead_output_key"], "ctx_tell": "ctx line " + MARK,
               "facts_tell": ["dead line " + MARK, "marker line " + MARK],
               "measured": {"faults": ["dead line " + MARK, "size line " + MARK]}}
        self.assertEqual(BG.tell_lines(out), ["ctx line " + MARK, "dead line " + MARK, "marker line " + MARK,
                                              "size line " + MARK])

    def test_the_new_wordings_are_ours_and_not_chimeras(self):
        """Registered for the echo check (blender_gate.TELL_FORMS, before step 6's), each refused when a reply
        repeats it, none sharing a run of NOTE_N words with any of Chimera's own texts (contract.texts: its rules and
        handoff text, filled for s1 to s7), none naming a version or the notes' words for the checks."""
        from contract import texts
        forms = BG.BUILD_TELL_FORMS + SI.TELL_FORMS
        self.assertEqual(len(BG.BUILD_TELL_FORMS), 11)
        k = BG.TELL_FORMS.index(BG.BUILD_TELL_FORMS[0])
        self.assertEqual(BG.TELL_FORMS[k:k + len(forms)], forms)
        chimeras = [v for v in vars(texts).values() if isinstance(v, str) and len(v) > 40]
        chimeras += [texts.fill(texts.MODE_BLENDER, sid="s%d" % n) for n in range(1, 8)]
        for form in forms:
            self.assertEqual(H.echoed_note("assumed: " + form + "\n" + MARK), "failure_line", form)
            self.assertIsNone(H.notes_leak(form, ""), form)
            self.assertEqual(H.versions_named(form), set(), form)
            n, sh = H._shingles(form)
            for text in chimeras:
                self.assertFalse(H.runs(text, n) & sh, (form, text[:60]))


if __name__ == "__main__":
    unittest.main()

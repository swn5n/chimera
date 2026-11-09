"""Hidden errors: what a Blender piece's own try/except kept Chimera from seeing (step 6a; results/DATAGEN-SMOKE.md,
"Third smoke run", and DESIGN.md, "blender_gate.py").

    cmd += ["--python-expr", PRELUDE % {"path": path, "maxline": n}]  # before --python path
    script = piece + "\\n" + EPILOGUE                                   # before every other epilogue
    rec = blender_gate._marked_line(output, SILENT_MARK)              # one version's record
    s1 = swallowed(code, {v: rec, ...}, line_of)                      # [{line, source, error, op, versions}]
    s2 = skipped_sockets({v: rec, ...}, line_of, code)                # [{line, key, owner, node, type, close}]

A run that exits 0 can still have done less than its code says: Blender refused a setting (an enum value it lacks, a
removed attribute, an input that isn't there) and the piece's own except caught the error, so Chimera's check, which
sees only what ends a run, passes it, and so does every check after it. The second smoke run kept three such Blender
examples (the audit's X07, X58 and X20, all bad: keys left BEZIER where Linear was asked, FFMPEG refused twice), and
X06 and the third run's D29 looked up the Principled BSDF's inputs by names it doesn't have ("Base_Color",
"Specular", "Transmission") behind an `if key in node.inputs`, so the glass stayed opaque.

PRELUDE is a --python-expr that watches the script's own frames before the script runs, and EPILOGUE, appended right
after the script and before the names, measuring and probes' epilogues (so nothing after it is watched), stops
watching and prints one line, SILENT_MARK plus compact JSON of at most SILENT_BUDGET characters (the material facts
are cut first, then the other facts, then the lists from their ends; never reached on the stored pieces, whose largest
record is 1,850 characters alone and 3,093 joined). It starts with blender_run.WM_MARK, so the strict rule never reads
it.
- Blender 5.2.2 (Python 3.13): sys.monitoring, tool id 4, else 3, else 2 (how "none" when all are taken: nothing is
  judged), RAISE and EXCEPTION_HANDLED, and LINE only at the indexed guard lines (DISABLE everywhere else, so a line
  costs one call the first time). 5.0.1 (Python 3.11) has no sys.monitoring: sys.settrace, with a local tracer only
  in the script's frames, where an "exception" event followed by a "line" event in the same frame means the error was
  handled there. Measured on the 10 slowest stored pieces, twice each, one run at a time: +0.00 s median in both
  (max +0.03 s in 5.2.2, +0.05 s in 5.0.1; a whole direct run 0.62 s and 0.44 s); with and without it, the run's
  verdict, output lines, probes and measuring were the same on 24 stored pieces (X06, X07, X20, X58 and 20 at random)
  in both versions.
- An error counts as handled in the piece when the code object that handles it is the piece's: its file is the
  script and its first line is in the piece (co_firstlineno <= maxline; a module's is 1). Not the handler's offset:
  in 5.2.2 EXCEPTION_HANDLED's offset maps to line None (co_lines; probed again Nov 4, in a function and at module
  level) and f_lineno is still the raising line, which is why the first prototype saw no handler line in any 5.2.2
  record.
- Each event: type, message (400 characters), the deepest line of the script in its traceback ("line"), the file it
  was raised in ("origin", "<script>" for the script's own), the instruction there when it is the script's ("op"),
  for a KeyError on the line the RNA type of each collection subscripted there ("coll"), and for a failed STORE_ATTR
  whose target and value are pure (names, attributes, subscripts by a constant) the value it meant ("meant"), read
  again at the end ("landed": the target holds it after all).
- Guards indexed from the script's own syntax: every `key in X` (or not in), `X.get(key)`, hasattr(X, key) and
  getattr(X, key, default) whose operands are pure. At their line, before it runs, the operands are read again in the
  frame: a key a node's socket collection lacks is a miss (with the sockets close to it: the key, lowercased without
  spaces and underscores, starts theirs, or difflib's 0.6, up to 4), one it has a hit, and an attribute a bpy struct
  lacks an attribute miss. A pure operand is evaluated once more, so a getter the piece defines runs twice.
- At the end EPILOGUE compares each miss's close sockets with a fresh node of the same type (linked, default or set),
  and records facts: every material that isn't the factory's with each node's inputs that differ from a fresh one,
  the render's output settings, and each action's key interpolation counts.
- Caps (the prelude's own numbers): 300 events ("cut" counts the rest), 100 misses, 100 attribute misses, 200 hits
  ("hit_cut" when more: a hit that went unrecorded would make a miss look unguarded, so skipped_sockets judges no
  such version). None was reached on the stored pieces (at most 4 events, 4 misses, 6 hits in a run).
Blind spots: in 5.0.1 a piece that sets its own trace function or runs threads isn't watched; in 5.2.2 tool ids 2-4
must be free; a version that rendered, quit or crashed prints no line and nothing is judged (watched()).

The verdicts claim little, since every false one costs a good piece:
- swallowed (S1): per piece line, an error handled in the piece in every version's run that came from Blender:
  raised in Blender's own Python (under Contents/Resources/<version>/, not its python/lib), or by an operation on the
  piece's own line whose message is Blender's RNA wording (BPY_WORDS, BPY_ATTR), never by a raise statement of the
  piece's own and never an AttributeError on None or on a class the piece defines. Excused (excused, with the why that
  excused_events records): another computer's GPU backend on the source line (GPU_LINE), an add-on (ADDON, in the
  source or the message), a mode switch with nothing to switch ("mode_set.poll()"), a KeyError from bpy.data, a
  collection's objects or a tree's nodes (an exists probe), a KeyError or an IndexError whose handler is a fallback
  (get-or-create: an empty material slot list filled in the handler), a file
  that isn't there or can't be opened (an OSError, or Chimera's file markers in the message; never "could not be
  found", which is how Blender says an operator is missing, the script's fault in Chimera too), a failed set whose
  target holds the value it meant at the end in every version (landed), and for any other operation a handler that
  does the same another way and raised nothing itself (another_way: the same value assigned, the same function
  called). Everything else counts, a removed attribute read or set inside a try too (policy B: the lint's own policy
  inside a try; a told teacher has to write only the code that works, which costs working legacy-first pieces such as
  the smoke's k10013).
- skipped_sockets (S2): a guard miss on a node's inputs in every version, where the node has a close input, every
  close input ended unlinked at the fresh node's default, and the same guard line on the same node found none of the
  close names (a loop that tries the old name, then the new one, isn't skipped), nor does the piece's code name one
  of them as a string anywhere (it set it on another path, maybe to its default). Outputs are never judged.
- attr_misses and excused_events are facts only: hasattr misses fired on 4 of 118 gate-passing pieces and couldn't
  tell harm (dead EEVEE probes beside keys left BEZIER). Since Nov 5 one of them is a reason, attr_miss
  (missed_keys): a miss on the way to the keys, where the step's words ask for linear keys (asks_linear) and every
  version's keys stayed otherwise, the one effect the report measures that a step asks for (soft on a step a later
  one depends on: task.SOFT_IF_USED). It fires on the stored X07 (bad) and the fourth smoke's kept blender-0008-00 s4,
  never on a piece whose keys are linear, a dead probe beside them included (the third smoke's kept c5).
Measured (round 6, Nov 4, sandboxed, both Blenders, rule B and the file excuse, through the gate's own direct run with
binary B's alone harness): of the 191 distinct stored alone scripts that ran clean, the 118 that passed the gate have 7
flagged, 3 swallowed (X07, X58, X20) and 4 skipped_input (X06, its sibling try, the smoke's repair of the same step, the
third run's D29), every one read and real, the same pieces and lines the mapper's prototype found; the 74 that failed a
later check (a piece can be both) have 9 (a swallowed "Geometry" socket, feature_set, shadow_method, use_soft_shadows,
FFMPEG, fcurves reads whose keys stayed BEZIER, and the policy's k10013). Of the audits' 55 graded Blender entries (32
bad, 17 weak, 6 ok) the 8 flagged are bad (4 pieces: X06 = Y08, X07 = Y44, X20 = Y27, X58 = Y09); no ok or weak one. 0
of 133 joined runs flagged anything their piece's alone run didn't, and every alone flag came back joined, so a joined
run's events are recorded only (blender_gate's "joined_silent"). The handled errors it doesn't count, 11 lines in all,
are 6 GPU probes and 5 not from Blender.

tell(s1, s2) and missed_tell(missed): the teacher's lines (never in a request or a target), the error cut at a word end
to ERROR_CHARS and the source to SOURCE_CHARS, less when the line would pass TELL_CHARS, through hints.unversioned.
TELL_FORMS is their
fixed wording, ours, for hints.echoed_note (through blender_gate.TELL_FORMS); MISSED_FORMS is missed_tell's, which
echoed_note reads directly.
"""
from __future__ import annotations

import ast
import re

from datagen.hints import unversioned
from runner import blender_run

SILENT_MARK = blender_run.WM_MARK + " dg-silent "  # starts with the runner's own mark: the strict rule never reads it
SILENT_BUDGET = 6000  # characters of the JSON after the mark
WATCHED = ("monitoring", "settrace")
TELL_EACH = 3  # lines per kind told
TELL_CHARS = 299  # under blender_gate.TELL_KEEP's 300
SOURCE_CHARS, ERROR_CHARS = 80, 120
EXCUSED_KEEP = 20  # excused_events rows kept

PRELUDE = r'''
import sys as _dgs_sys
def _dgs_install(_path, _maxline):
    # datagen/silent.py: the piece's handled errors and guard misses, watched from before it runs
    _st = {"ev": [], "cut": 0, "how": None, "miss": [], "miss_refs": [], "attr_miss": [], "hit": []}
    _dgs_sys._dg_silent = _st
    _seen = {}
    _keep = []
    _live = [True]
    def _ours(code):
        # the piece's own code: its file, and its first line in the piece (an epilogue's function is past maxline)
        return code.co_filename == _path and code.co_firstlineno <= _maxline
    def _deepest(exc, tb=None):
        tb, last, script = (tb if tb is not None else exc.__traceback__), None, None
        while tb is not None:
            last = tb
            if tb.tb_frame.f_code.co_filename == _path:
                script = tb
            tb = tb.tb_next
        return last, script
    def _opname(code, lasti):
        try:
            import dis
            for ins in dis.get_instructions(code):
                if ins.offset == lasti:
                    return ins.opname
        except Exception:
            pass
        return None
    def _saw(exc, frame_line, tb=None, frame=None):
        if not _live[0] or isinstance(exc, (StopIteration, StopAsyncIteration, GeneratorExit)):
            return None
        rec = _seen.get(id(exc))
        if rec is not None and rec[0] is exc:
            return rec[1]
        last, script = _deepest(exc, tb)
        line = script.tb_lineno if script is not None else frame_line
        if not line or line > _maxline:
            return None
        if len(_st["ev"]) >= 300:
            _st["cut"] += 1
            return None
        o = last.tb_frame.f_code if last is not None else None
        ofile = o.co_filename if o is not None else None
        try:
            msg = str(exc)[:400]
        except Exception:
            msg = ""
        r = {"type": type(exc).__name__, "msg": msg, "line": line,
             "origin": "<script>" if ofile == _path else ofile,
             "origin_line": last.tb_lineno if last is not None else None,
             "op": _opname(o, last.tb_lasti) if ofile == _path else None, "handled": None}
        if isinstance(exc, KeyError) and frame is not None and ofile == _path:
            r["coll"] = _colls(frame, line)
        _seen[id(exc)] = (exc, r)
        _keep.append(exc)
        _st["ev"].append(r)
        if r["op"] == "STORE_ATTR" and frame is not None:
            _target(frame, line, r)
        return r
    def _handled_by(code, exc):
        if not _ours(code):
            return
        rec = _seen.get(id(exc))
        if rec is not None and rec[0] is exc and rec[1]["handled"] is None:
            rec[1]["handled"] = code.co_name
            rec[1]["handled_in"] = code.co_firstlineno
    def _colls(frame, line):
        # the RNA type of each collection the line subscripts, read again in its frame
        out = []
        was = _live[0]
        _live[0] = False
        try:
            import bpy as _bpy
            for c in _subs.get(line, ()):
                try:
                    C = eval(c, frame.f_globals, frame.f_locals)
                except Exception:
                    continue
                if type(C).__name__ != "bpy_prop_collection":
                    continue
                try:
                    rid = C.rna_type.identifier
                except Exception:
                    rid = None
                kind = None
                try:
                    if len(C):
                        x = C[0]
                        T = _bpy.types
                        kind = "id" if isinstance(x, T.ID) else "socket" if isinstance(x, T.NodeSocket) \
                            else "node" if isinstance(x, T.Node) else type(x).__name__
                except Exception:
                    pass
                out.append([rid, kind])
        except Exception:
            pass
        finally:
            _live[0] = was
        return out
    def _target(frame, line, r):
        # the attribute the failing statement set and the value it meant, read again in its frame (pure operands only)
        was = _live[0]
        _live[0] = False
        try:
            import ast as _a
            for n in _a.walk(_tree):
                if isinstance(n, _a.Assign) and n.lineno <= line <= getattr(n, "end_lineno", n.lineno) and \
                        len(n.targets) == 1 and isinstance(n.targets[0], _a.Attribute) and _pure(n.targets[0].value) \
                        and _pure(n.value):
                    owner = eval(compile(_a.Expression(n.targets[0].value), "<dgs>", "eval"), frame.f_globals,
                                 frame.f_locals)
                    val = eval(compile(_a.Expression(n.value), "<dgs>", "eval"), frame.f_globals, frame.f_locals)
                    _st.setdefault("targets", []).append((r, owner, n.targets[0].attr, val))
                    r["meant"] = repr(val)[:80]
                    break
        except Exception as e:
            r["target_failed"] = repr(e)[:120]
        finally:
            _live[0] = was
    # guards: `key in X`, `X.get(key)`, hasattr(X, key) and getattr(X, key, default) with pure operands, read again at
    # the line event (before the line runs, so the same values)
    _idx = {}
    _subs = {}
    try:
        import ast as _ast
        with open(_path, encoding="utf-8") as _f:
            _tree = _ast.parse(_f.read())
        def _pure(n):
            if isinstance(n, (_ast.Name, _ast.Constant)):
                return True
            if isinstance(n, _ast.Attribute):
                return _pure(n.value)
            if isinstance(n, _ast.Subscript):
                return _pure(n.value) and isinstance(n.slice, _ast.Constant)
            return False
        for n in _ast.walk(_tree):
            pair = None
            if isinstance(n, _ast.Compare) and len(n.ops) == 1 and isinstance(n.ops[0], (_ast.In, _ast.NotIn)):
                pair = (n.comparators[0], n.left)
            elif isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute) and n.func.attr == "get" and n.args:
                pair = (n.func.value, n.args[0])
            kind = "key"
            if pair is None and isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name) and \
                    ((n.func.id == "hasattr" and len(n.args) == 2) or (n.func.id == "getattr" and len(n.args) == 3)):
                pair, kind = (n.args[0], n.args[1]), "attr"
            if isinstance(n, _ast.Subscript) and isinstance(n.ctx, _ast.Load) and _pure(n.value) and \
                    not isinstance(n.value, _ast.Constant) and n.lineno <= _maxline:
                _subs.setdefault(n.lineno, []).append(compile(_ast.Expression(n.value), "<dgs>", "eval"))
            if pair and _pure(pair[0]) and _pure(pair[1]) and n.lineno <= _maxline \
                    and not isinstance(pair[0], _ast.Constant):
                _idx.setdefault(n.lineno, []).append((compile(_ast.Expression(pair[0]), "<dgs>", "eval"),
                                                      compile(_ast.Expression(pair[1]), "<dgs>", "eval"), kind))
    except Exception as e:
        _st["idx_failed"] = repr(e)[:200]
    _mseen = set()
    def _look(frame, line):
        was = _live[0]
        _live[0] = False
        try:
            for c, k, kind in _idx.get(line, ()):
                try:
                    C = eval(c, frame.f_globals, frame.f_locals)
                    K = eval(k, frame.f_globals, frame.f_locals)
                except Exception:
                    continue
                if kind == "attr":
                    try:
                        import bpy as _bpy
                        if not isinstance(K, str) or not isinstance(C, _bpy.types.bpy_struct) or hasattr(C, K):
                            continue
                        rid = C.bl_rna.identifier
                    except Exception:
                        continue
                    ak = (line, K, rid)
                    if ak in _mseen or len(_st["attr_miss"]) >= 100:
                        continue
                    _mseen.add(ak)
                    _st["attr_miss"].append({"line": line, "attr": K, "on": rid})
                    continue
                if type(C).__name__ != "bpy_prop_collection" or not isinstance(K, str):
                    continue
                try:
                    import bpy as _bpy
                    if not len(C) or not isinstance(C[0], _bpy.types.NodeSocket):
                        continue
                    keys = list(C.keys())
                    if K in keys:
                        try:
                            hk = (line, K, C[0].node.as_pointer())
                            if hk not in _mseen:
                                if len(_st["hit"]) < 200:
                                    _mseen.add(hk)
                                    _st["hit"].append({"line": line, "key": K, "node": C[0].node.as_pointer()})
                                else:
                                    _st["hit_cut"] = True
                        except Exception:
                            pass
                        continue
                    node = C[0].node
                    sk = (line, K, node.as_pointer(), C[0].is_output)
                except Exception:
                    continue
                if sk in _mseen or len(_st["miss"]) >= 100:
                    continue
                _mseen.add(sk)
                import difflib
                squash = K.lower().replace("_", "").replace(" ", "")
                close = [x for x in keys if x.lower().replace(" ", "").startswith(squash)] if squash else []
                for x in difflib.get_close_matches(K, keys, n=3, cutoff=0.6):
                    if x not in close:
                        close.append(x)
                _st["miss"].append({"line": line, "key": K, "node": node.bl_idname, "node_name": node.name,
                                    "ptr": node.as_pointer(), "side": "outputs" if C[0].is_output else "inputs",
                                    "close": close[:4]})
                _st["miss_refs"].append(node)
        except Exception:
            pass
        finally:
            _live[0] = was
    M = getattr(_dgs_sys, "monitoring", None)
    if M is not None:
        tool = None
        for t in (4, 3, 2):
            try:
                M.use_tool_id(t, "dg-silent")
                tool = t
                break
            except ValueError:
                continue
        if tool is None:
            _st["how"] = "none"
            return
        def _line_of(code, off):
            try:
                for a, b, l in code.co_lines():
                    if a <= off < b:
                        return l
            except Exception:
                pass
            return None
        def _raise(code, off, exc):
            try:
                if code.co_filename == _path:
                    _saw(exc, _line_of(code, off), None, _dgs_sys._getframe(1))
            except Exception:
                pass
        def _handled(code, off, exc):
            try:
                _handled_by(code, exc)
            except Exception:
                pass
        def _line(code, line):
            if code.co_filename != _path or line not in _idx:
                return M.DISABLE
            _look(_dgs_sys._getframe(1), line)
        E = M.events
        M.register_callback(tool, E.RAISE, _raise)
        M.register_callback(tool, E.EXCEPTION_HANDLED, _handled)
        ev = E.RAISE | E.EXCEPTION_HANDLED
        if _idx:
            M.register_callback(tool, E.LINE, _line)
            ev |= E.LINE
        M.set_events(tool, ev)
        _st["how"] = "monitoring"
    else:
        _pending = {}
        def _local(frame, event, arg):
            try:
                if event == "exception":
                    r = _saw(arg[1], frame.f_lineno, arg[2], frame)
                    if r is not None:
                        _pending[id(frame)] = arg[1]
                elif event == "line":
                    if frame.f_lineno in _idx:
                        _look(frame, frame.f_lineno)
                    exc = _pending.pop(id(frame), None)
                    if exc is not None:
                        _handled_by(frame.f_code, exc)
                elif event == "return":
                    _pending.pop(id(frame), None)
            except Exception:
                pass
            return _local
        def _global(frame, event, arg):
            if _ours(frame.f_code):
                return _local
            return None
        _dgs_sys.settrace(_global)
        _st["how"] = "settrace"
_dgs_install(%(path)r, %(maxline)d)
del _dgs_install
'''

_EPILOGUE = r'''

# ---- datagen silent report (worker-model/datagen/silent.py): stops watching, then the piece's hidden errors ----
def _dgs_report():
    import sys, json
    st = getattr(sys, "_dg_silent", None) or {"ev": [], "how": "missing"}
    try:
        sys.settrace(None)
    except Exception:
        pass
    M = getattr(sys, "monitoring", None)
    if M is not None:
        for t in (4, 3, 2):
            try:
                if M.get_tool(t) == "dg-silent":
                    M.set_events(t, 0)
                    for e in (M.events.RAISE, M.events.EXCEPTION_HANDLED, M.events.LINE):
                        M.register_callback(t, e, None)
                    M.free_tool_id(t)
            except Exception:
                pass
    out = {"how": st.get("how")}
    try:
        for r, owner, attr, val in st.get("targets") or []:
            try:
                cur = getattr(owner, attr)
                if isinstance(val, (str, bytes, bool, int, float)) or val is None:
                    r["landed"] = bool(cur == val) if not isinstance(val, float) else abs(float(cur) - val) < 1e-6
                else:
                    try:
                        r["landed"] = len(cur) == len(val) and all(abs(float(x) - float(y)) < 1e-6
                                                                   for x, y in zip(cur, val))
                    except Exception:
                        r["landed"] = bool(cur == val)
                r["now"] = repr(cur)[:80]
            except Exception as e:
                r["landed"] = None
                r["landed_failed"] = repr(e)[:120]
        out.update({"cut": st.get("cut", 0), "ev": st.get("ev") or [], "miss": st.get("miss") or [],
                    "attr_miss": st.get("attr_miss") or [], "hit": st.get("hit") or []})
        for k in ("idx_failed", "hit_cut"):
            if st.get(k):
                out[k] = st[k]
        import bpy
        for m, node in zip(out["miss"], st.get("miss_refs") or []):
            try:
                tree = node.id_data
                tmp = bpy.data.node_groups.new("_dgs_tmp", tree.bl_idname)
                try:
                    fresh = tmp.nodes.new(node.bl_idname)
                    side = getattr(node, m["side"])
                    fside = getattr(fresh, m["side"])
                    state = {}
                    for name in m["close"]:
                        s = side.get(name)
                        f = fside.get(name)
                        if s is None:
                            continue
                        if s.is_linked:
                            state[name] = "linked"
                        elif hasattr(s, "default_value") and f is not None:
                            a, b = s.default_value, f.default_value
                            try:
                                same = all(abs(float(x) - float(y)) < 1e-6 for x, y in zip(a, b))
                            except TypeError:
                                same = a == b
                            state[name] = "default" if same else "set"
                    m["close_state"] = state
                finally:
                    bpy.data.node_groups.remove(tmp)
                owner = [mt.name for mt in bpy.data.materials if mt.node_tree is not None and mt.node_tree == tree]
                m["owner"] = owner[0] if owner else tree.name
            except Exception as e:
                m["state_failed"] = (type(e).__name__ + ": " + str(e))[:200]
        def val(v):
            try:
                if isinstance(v, (int, float, bool, str)):
                    return round(v, 4) if isinstance(v, float) else v
                return [round(float(x), 4) for x in v]
            except Exception:
                return None
        try:
            mats = []
            tmp = bpy.data.materials.new("_dgs_ref")
            try:
                try:
                    tmp.use_nodes = True
                except Exception:
                    pass
                ref = {}
                def defaults(idname):
                    if idname not in ref:
                        d = {}
                        try:
                            n = tmp.node_tree.nodes.new(idname)
                            for s in n.inputs:
                                if hasattr(s, "default_value"):
                                    d[s.identifier] = val(s.default_value)
                            tmp.node_tree.nodes.remove(n)
                        except Exception:
                            d = None
                        ref[idname] = d
                    return ref[idname]
                for m in bpy.data.materials:
                    if m is tmp or m.name in ("Material", "Dots Stroke"):
                        continue
                    row = {"name": m.name, "users": m.users, "diffuse": val(m.diffuse_color), "nodes": []}
                    tree = m.node_tree
                    if tree is not None:
                        for n in tree.nodes:
                            d = defaults(n.bl_idname)
                            changed = {}
                            for s in n.inputs:
                                if s.is_linked:
                                    changed[s.name] = "linked"
                                elif hasattr(s, "default_value") and d is not None:
                                    v = val(s.default_value)
                                    if d.get(s.identifier) != v:
                                        changed[s.name] = v
                            row["nodes"].append({"type": n.bl_idname, "changed": changed})
                        row["links"] = len(tree.links)
                    mats.append(row)
            finally:
                bpy.data.materials.remove(tmp)
            out["materials"] = mats
            sc = bpy.context.scene
            r = sc.render
            im = r.image_settings
            out["render"] = {"engine": r.engine, "file_format": im.file_format,
                             "media_type": getattr(im, "media_type", None), "filepath": r.filepath,
                             "ffmpeg": [r.ffmpeg.format, r.ffmpeg.codec], "fps": r.fps,
                             "res": [r.resolution_x, r.resolution_y, r.resolution_percentage],
                             "frames": [sc.frame_start, sc.frame_end]}
            acts = []
            for a in bpy.data.actions:
                curves = []
                try:
                    curves = list(a.fcurves)
                except Exception:
                    try:
                        for layer in a.layers:
                            for strip in layer.strips:
                                for cb in strip.channelbags:
                                    curves.extend(cb.fcurves)
                    except Exception:
                        curves = []
                modes = {}
                for fc in curves:
                    for k in fc.keyframe_points:
                        modes[k.interpolation] = modes.get(k.interpolation, 0) + 1
                acts.append({"name": a.name, "curves": len(curves), "interp": modes})
            out["actions"] = acts
        except Exception as e:
            out["facts_failed"] = (type(e).__name__ + ": " + str(e))[:200]
        size = lambda: len(json.dumps(out, separators=(",", ":"), default=str))
        dropped = []
        for k in ("materials", "actions", "render"):
            if size() <= _dgs_budget:
                break
            if k in out:
                del out[k]
                dropped.append(k)
        if dropped:
            out["dropped"] = dropped
        trimmed = {}
        for k in ("attr_miss", "miss", "ev", "hit"):
            while size() > _dgs_budget and out.get(k):
                out[k].pop()
                trimmed[k] = trimmed.get(k, 0) + 1
                out["trimmed"] = trimmed
    except Exception as e:
        out = {"how": st.get("how"), "failed": (type(e).__name__ + ": " + str(e))[:200]}
    print(_dgs_mark + json.dumps(out, separators=(",", ":"), default=str), flush=True)
_dgs_mark, _dgs_budget = %(mark)r, %(budget)d
try:
    _dgs_report()
except Exception:
    pass
del _dgs_report, _dgs_mark, _dgs_budget
'''
EPILOGUE = _EPILOGUE % {"mark": SILENT_MARK, "budget": SILENT_BUDGET}


def watched(rec):
    """Whether one version's record (the line's JSON, or None) watched the piece: printed, with a way to watch."""
    return isinstance(rec, dict) and rec.get("how") in WATCHED and "failed" not in rec


# ---------------------------------------------------------------- where an error came from

BLENDER_HOME = re.compile(r"/Contents/Resources/\d+\.\d+/")
# Blender's own wording for its RNA errors (bpy_rna.cc, bpy_props, operators): the API's messages, not the piece's
BPY_WORDS = re.compile(r"bpy_struct|bpy_prop_collection|bpy_prop_array|enum \"[^\"]*\" not found in|"
                       r"expected an? \w+ type, not|error with (?:argument|keyword argument)|"
                       r"Function\.\w+ expected|\.poll\(\) failed|Operator bpy\.ops|Calling operator \"bpy\.ops|"
                       r"context is incorrect|\bkey \"[^\"]*\" not found|Error: |is read-only|does not support|"
                       r"keyword \"\w+\" unrecognized|takes at most|: expected .* not ", re.I)
BPY_ATTR = re.compile(r"^'(bpy_struct|bpy_func|bpy_prop_collection|[A-Z]\w*)' object has no attribute '\w+'$")
NOT_BPY_TYPES = {"NoneType", "NotImplementedType"}  # capitalised, but Python's own


def _own_classes(code):
    try:
        return {n.name for n in ast.walk(ast.parse(code or "")) if isinstance(n, ast.ClassDef)}
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return set()


def from_blender(ev, own=frozenset()):
    """The error came out of Blender: raised inside Blender's own Python (bpy.ops, bpy_types, add-on modules), or by
    an operation on the piece's line that isn't a raise statement (a C call, an attribute set or read, a subscript)
    whose message is Blender's own wording. own: the class names the piece defines (an AttributeError on one, or on
    None, is the piece's own, though BPY_ATTR's capitalised type reads like Blender's)."""
    o = ev.get("origin")
    if o and o != "<script>":
        return bool(BLENDER_HOME.search(o)) and "/python/lib/python3" not in o
    if ev.get("op") in ("RAISE_VARARGS", "RERAISE"):
        return False
    msg = ev.get("msg") or ""
    m = BPY_ATTR.search(msg)
    if m:
        return m.group(1) not in NOT_BPY_TYPES and m.group(1) not in own
    return bool(BPY_WORDS.search(msg))


# ---------------------------------------------------------------- the handler, read from the piece

QUIET_CALLS = {"print", "log", "warning", "warn", "info", "debug", "error", "exception", "report"}


def _quiet(stmt):
    """A statement that does nothing to the scene: pass, ..., continue, break, a print or a log call, a return of a
    constant or a plain name, a plain name set to a constant, a name, a list or a dict."""
    if isinstance(stmt, (ast.Pass, ast.Continue, ast.Break)):
        return True
    if isinstance(stmt, ast.Expr):
        v = stmt.value
        if isinstance(v, ast.Constant):
            return True
        if isinstance(v, ast.Call):
            f = v.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            return name in QUIET_CALLS
        return False
    if isinstance(stmt, ast.Return):
        return stmt.value is None or isinstance(stmt.value, (ast.Constant, ast.Name))
    if isinstance(stmt, ast.Assign):
        return all(isinstance(t, ast.Name) for t in stmt.targets) and isinstance(stmt.value, (ast.Constant, ast.Name,
                                                                                            ast.List, ast.Dict))
    return False


def _parse(code):
    try:
        return ast.parse(code or "")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None


def _try_at(tree, line):
    """The innermost try in tree whose body holds line, or None."""
    best = None
    for n in ast.walk(tree):
        if isinstance(n, (ast.Try, getattr(ast, "TryStar", ast.Try))) and n.body:
            a, b = n.body[0].lineno, max(getattr(s, "end_lineno", s.lineno) for s in n.body)
            if a <= line <= b and (best is None or a >= best.body[0].lineno):
                best = n
    return best


def handlers_at(code, line):
    """The innermost try in the piece whose body holds line: ("swallow" | "fallback" | "reraise", the first handler's
    line) of its handlers taken together, or (None, None) when no try holds it (a with that suppresses, or a handler
    in a caller)."""
    tree = _parse(code)
    t = _try_at(tree, line) if tree is not None else None
    if t is None:
        return None, None
    kinds = []
    for h in t.handlers:
        if any(isinstance(s, ast.Raise) for s in ast.walk(h)):
            kinds.append("reraise")
        elif all(_quiet(s) for s in h.body):
            kinds.append("swallow")
        else:
            kinds.append("fallback")
    kind = "swallow" if kinds and all(k == "swallow" for k in kinds) else \
        "reraise" if "reraise" in kinds else "fallback"
    return kind, t.handlers[0].lineno if t.handlers else None


def _stmt_at(tree, line):
    """The innermost simple statement whose lines hold line."""
    best = None
    for n in ast.walk(tree):
        if isinstance(n, ast.stmt) and not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.If,
                                                           ast.For, ast.While, ast.Try, ast.With)):
            if n.lineno <= line <= getattr(n, "end_lineno", n.lineno):
                if best is None or n.lineno >= best.lineno:
                    best = n
    return best


def _call_name(node):
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None


def another_way(code, line, raised_lines):
    """The try's handler does what the failing statement meant another way and didn't fail itself (no error was
    raised on its lines, raised_lines): it assigns the same value to another target, or the same target and value
    again (after setting something up), or calls the same function. False for a handler that only passes, prints,
    continues, or sets the same target to another value (X20's OPEN_EXR in place of FFMPEG)."""
    tree = _parse(code)
    if tree is None:
        return False
    st, t = _stmt_at(tree, line), _try_at(tree, line)
    if st is None or t is None or not t.handlers:
        return False
    for h in t.handlers:
        a, b = h.lineno, max(getattr(s, "end_lineno", s.lineno) for s in h.body)
        if any(a <= l <= b for l in raised_lines):
            continue  # the handler failed too
        for n in ast.walk(h):
            if isinstance(st, ast.Assign) and isinstance(n, ast.Assign) and ast.dump(n.value) == ast.dump(st.value):
                return True
            if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call) and isinstance(n, ast.Call) and \
                    _call_name(n) and _call_name(n) == _call_name(st.value):
                return True
    return False


# ---------------------------------------------------------------- the verdicts

GPU_LINE = re.compile(r"compute_device_type|get_devices|\.devices\b|\.preferences\b")  # another computer's GPU
ADDON = re.compile(r"\baddon|\badd-on|Add-on not loaded", re.I)  # an add-on this Blender may lack (Chimera's addonRe)
MODE_SET_POLL = "mode_set.poll()"  # switching mode with nothing to switch: a no-op
# Chimera's own file markers (app/hydra_check.go's envMarkers): a handled error that says the file or the folder isn't
# there or can't be opened is the computer's, not the piece's. Never "could not be found": that is how Blender says
# an operator is missing (bpy.ops), which Chimera counts as the script's fault (noOperator)
FILE_MSG = re.compile(r"\[errno|no such file|cannot open|can't open|unable to open|cannot read|failed to open|"
                      r"failed to read|failed to write|permission denied|operation not permitted|"
                      r"read-only file system", re.I)
OS_ERRORS = {"OSError", "IOError", "FileNotFoundError", "PermissionError", "IsADirectoryError", "NotADirectoryError",
             "FileExistsError"}
EXISTS_COLLECTIONS = ("BlendData", "Collection", "SceneObjects", "Nodes")  # by name: bpy.data, objects, a tree's nodes
# Why a handled error at a piece line isn't counted (excused_events' "why"; the report counts them)
WHY = ("not_blender", "not_every_version", "gpu", "addon", "mode_set", "get_or_create", "exists_probe", "file",
       "landed", "another_way")


def excused(code, pl, src, ev):
    """Why a handled error from Blender at piece line pl (source src) isn't the piece's hidden failure, or "": another
    computer's GPU backend, an add-on that may be missing, a mode switch with nothing to switch, a get-or-create
    lookup (a KeyError or an IndexError whose handler makes the thing: `mats[0] = mat` on an empty slot list, else
    append; the step-6 checker's two such correct pieces were swallowed, and no stored alone run changes) or an
    exists probe (a KeyError by name in bpy.data, a collection's objects or a tree's nodes), or a file the computer
    doesn't have."""
    msg = ev.get("msg") or ""
    if GPU_LINE.search(src):
        return "gpu"
    if ADDON.search(src) or ADDON.search(msg):
        return "addon"
    if MODE_SET_POLL in msg:
        return "mode_set"
    if ev.get("type") in ("KeyError", "IndexError") and handlers_at(code, pl)[0] == "fallback":
        return "get_or_create"
    colls = ev.get("coll") or []
    if ev.get("type") == "KeyError" and colls and all(
            k in ("id", "node") or (rid or "").startswith(EXISTS_COLLECTIONS) for rid, k in colls):
        return "exists_probe"
    if ev.get("type") in OS_ERRORS or FILE_MSG.search(msg):
        return "file"
    return ""


def _identity(x):
    return x


def _judged(code, by_version, line_of=None):
    """Every piece line with an error handled there in some version, judged: [{line, source, error, op, versions,
    why}], why "" for a line swallowed counts (WHY's labels otherwise)."""
    line_of = line_of or _identity
    lines = (code or "").split("\n")
    own = _own_classes(code)
    blender, other, raised = {}, {}, set()
    for v, rec in by_version.items():
        for ev in (rec or {}).get("ev") or []:
            pl = line_of(ev.get("line"))
            if pl is None:
                continue
            raised.add(pl)
            if ev.get("handled") is None:
                continue
            (blender if from_blender(ev, own) else other).setdefault(pl, {}).setdefault(v, []).append(ev)
    out = []
    for pl in sorted(set(blender) | set(other)):
        vs = blender.get(pl) or {}
        src = lines[pl - 1].strip() if 0 < pl <= len(lines) else ""
        some = vs or other[pl]
        ev = some[sorted(some)[0]][0]
        row = {"line": pl, "source": src, "error": "%s: %s" % (ev.get("type"), (ev.get("msg") or "")[:160]),
               "op": ev.get("op"), "versions": sorted(set(vs) | set(other.get(pl) or {}))}
        evs = [e for v in vs for e in vs[v]]
        if not vs:
            why = "not_blender"
        elif set(vs) != set(by_version):
            why = "not_every_version"  # a fallback for one version, or a path one version doesn't take
        else:
            why = excused(code, pl, src, ev)
            if not why and all(e.get("op") == "STORE_ATTR" for e in evs) and all(e.get("landed") is True for e in evs):
                why = "landed"
            if not why and not all(e.get("op") == "STORE_ATTR" and "landed" in e for e in evs) and \
                    another_way(code, pl, raised - {pl}):
                why = "another_way"
        out.append(dict(row, why=why))
    return out


def swallowed(code, by_version, line_of=None):
    """S1. Errors from Blender that the piece handled at its own lines in every version's run, not excused:
    [{line, source, error, op, versions}]. by_version: {version: record}; line_of maps a script line to the piece's
    line (None: not the piece's), the identity by default."""
    return [{k: r[k] for k in ("line", "source", "error", "op", "versions")}
            for r in _judged(code, by_version, line_of) if not r["why"]]


def excused_events(code, by_version, line_of=None):
    """The handled errors at the piece's lines that swallowed doesn't count, each with why (WHY): facts for the
    record and the report, at most EXCUSED_KEEP."""
    return [{"line": r["line"], "error": r["error"][:120], "why": r["why"], "versions": r["versions"]}
            for r in _judged(code, by_version, line_of) if r["why"]][:EXCUSED_KEEP]


def skipped_sockets(by_version, line_of=None, code=None):
    """S2. A guarded lookup on a node's inputs (`key in node.inputs`, `node.inputs.get(key)`) that missed in every
    version, where the node has an input the key is close to, every close input it has ended unlinked at the fresh
    node's default, and the same guard line on the same node found none of the close names: [{line, key, owner, node,
    type, close}] (owner: the material, else the tree; node: its name; type: its bl_idname; close: the inputs left at
    their default). A version whose hits were capped (hit_cut) or trimmed judges nothing. With code (the piece's), a
    miss one of whose close inputs the code names as a string isn't skipped: the piece set it on another path, here
    to the value that is its default (the step-6 checker's gold material set "Specular IOR Level" to 0.5 through a
    one-line legacy-first conditional the guard doesn't see); none of the 13 stored flags names one."""
    line_of = line_of or _identity
    tree = _parse(code) if code is not None else None
    named = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)} \
        if tree is not None else set()
    per = {}
    for v, rec in by_version.items():
        rec = rec or {}
        if rec.get("hit_cut") or (rec.get("trimmed") or {}).get("hit"):
            continue
        hits = {(h.get("line"), h.get("node"), h.get("key")) for h in rec.get("hit") or []}
        for m in rec.get("miss") or []:
            if m.get("side") != "inputs":
                continue
            pl = line_of(m.get("line"))
            if pl is None:
                continue
            state = m.get("close_state") or {}
            close = [c for c in m.get("close") or [] if state.get(c) == "default"]
            if not close or any(state.get(c) in ("set", "linked") for c in m.get("close") or []):
                continue
            if any((m.get("line"), m.get("ptr"), c) in hits for c in m.get("close") or []):
                continue
            if named & set(m.get("close") or []):
                continue
            per.setdefault((pl, m["key"], m.get("owner"), m.get("node_name")), {})[v] = (close, m.get("node"))
    out = []
    for (pl, key, owner, node), vs in sorted(per.items(), key=str):
        if set(vs) == set(by_version):
            close, idn = vs[sorted(vs)[0]]
            out.append({"line": pl, "key": key, "owner": owner, "node": node, "type": idn, "close": close})
    return out


def attr_misses(by_version, line_of=None):
    """hasattr/getattr guards that found no such attribute on a bpy struct in every version: [{line, attr, on}].
    A fact: on the stored pieces it couldn't tell harm from a dead probe."""
    line_of = line_of or _identity
    per = {}
    for v, rec in by_version.items():
        for m in (rec or {}).get("attr_miss") or []:
            pl = line_of(m.get("line"))
            if pl is None:
                continue
            per.setdefault((pl, m.get("attr"), m.get("on")), set()).add(v)
    return [{"line": k[0], "attr": k[1], "on": k[2]} for k, vs in sorted(per.items(), key=str)
            if vs == set(by_version)]


# ---------------------------------------------------------------- a guard that skipped what the step asks (Nov 5)
#
# attr_miss as a reason, for the one effect the epilogue measures that a step's words ask for: linear keys. The
# fourth smoke's kept blender-0008-00 r1 s4 (qwen3.8 c4) claims LINEAR in its provides line, but its three hasattr
# fallbacks (fcurves on the slot, the layer and the Action) find nothing in either Blender and the keys stay BEZIER;
# the second smoke's X07 (graded bad) is the same, and the third smoke's kept c5, whose hasattr on Action.fcurves
# missed too, set LINEAR another way, so it stays a fact there. Since the lint no longer fails a guarded read
# (tools/rna_lint.guards), this is what holds such a piece to the step.

# A step's words that ask for linear keys: "interpolation mode is Linear", "Set interpolation to `LINEAR`",
# "keyframe.interpolation = 'LINEAR'", "with linear interpolation"; not an image texture's, a shape key's or a colour
# ramp's interpolation (NOT_KEYS, just before), nor a linear mapping or a gradient
LINEAR_ASK = re.compile(r"\binterpolat\w*(?:\s+(?:mode|type))?\s+(?:(?:set\s+)?(?:to|is|as|of)\s+|[=:]\s*)?"
                        r"[`'\"]?linear\b|\blinear\s+(?:keyframe\s+|key\s+)?interpolat\w*", re.I)
NOT_KEYS = re.compile(r"\b(?:textures?|images?|shape[\s‑-]*keys?|colou?r\s*ramps?|gradients?)\W+(?:\w+\W+){0,2}$",
                      re.I)
# The attributes a piece probes on its way to the keys: the curves, and anything on an Action, its slots, layers and
# strips (the stored misses: fcurves on Action, ActionSlot, ActionLayer and ActionKeyframeStrip, slot on ActionLayer)
KEY_ATTRS = frozenset({"fcurves", "channelbag", "channelbags", "keyframe_points"})


def asks_linear(text):
    """The phrase of a step's title and instructions that asks for linear keys (LINEAR_ASK), or None. On the 545
    distinct Blender steps of the helper's raw plans and the four smoke runs it finds 16, every one about keyframes
    (an image texture's "interpolation to `Linear`" and a shape key's are left out); of the smoke runs' steps only
    blender-0008-00 s4 ("Ensure interpolation mode is Linear")."""
    for m in LINEAR_ASK.finditer(text or ""):
        if not NOT_KEYS.search(text[max(0, m.start() - 40):m.start()]):
            return m.group(0)
    return None


def _modes(rec):
    """{interpolation: keys} over every action of one version's report, or None when it has no action facts."""
    acts = (rec or {}).get("actions")
    if acts is None:
        return None
    out = {}
    for a in acts:
        for k, n in (a.get("interp") or {}).items():
            out[k] = out.get(k, 0) + int(n or 0)
    return out


def missed_keys(by_version, line_of=None, words=""):
    """attr_miss's reason (Nov 5): the hasattr or getattr guards on the piece's way to the keys (KEY_ATTRS, or any
    attribute of an Action* struct) that found nothing in every version (attr_misses), when the step's words ask for
    linear keys (asks_linear) and every version's report shows keys and none of them LINEAR: [{line, attr, on,
    keys}], keys the first version's {interpolation: count}. [] otherwise, so never on a piece whose keys are linear,
    nor on one that made no keys or whose report has no action facts (the budget cut them, or they failed)."""
    if not asks_linear(words):
        return []
    misses = [m for m in attr_misses(by_version, line_of)
              if m["attr"] in KEY_ATTRS or str(m.get("on") or "").startswith("Action")]
    if not misses:
        return []
    modes = [_modes(rec) for rec in by_version.values()]
    if not modes or any(m is None or not sum(m.values()) or m.get("LINEAR") for m in modes):
        return []
    keys = dict(sorted(modes[0].items()))
    return [dict(m, keys=keys) for m in misses]


def joined_line_of(linemap, sid):
    """For a joined run: a line of the joined script to sid's own piece line through the line map's origins
    ([sid, part, function, piece line] per script line), None for any other step's or Chimera's."""
    origins = (linemap or {}).get("origins") or []

    def line_of(n):
        o = origins[n - 1] if isinstance(n, int) and 0 < n <= len(origins) else None
        return o[3] if o and o[0] == sid and isinstance(o[3], int) else None
    return line_of


# ---------------------------------------------------------------- what the next try is told

SWALLOWED_ATTR = ("line %d `%s`: %s, and the piece's own except caught it: that name isn't in the Blender the piece "
                  "runs in, so write only the code that works there, with no try around it")
SWALLOWED = ("line %d `%s` raised %s, and the piece's own except caught it, so that line did nothing: fix the call "
             "itself instead of catching its error")
SKIPPED = ("line %d looked up the input %r on %s's %s, which has no input of that name (it has %s), so the lookup was "
           "skipped and %s stayed at its default: use the input's real name")
_MISSING_NAME = re.compile(r"has no attribute|could not be found", re.I)  # SWALLOWED_ATTR's errors: a name not there
# The fixed runs of 5 words or more between the forms' slots, for hints.echoed_note
TELL_FORMS = tuple(p.strip(" :,`()") for f in (SWALLOWED_ATTR, SWALLOWED, SKIPPED) for p in re.split(r"%[sdr]", f)
                   if len(re.findall(r"\w+", p)) >= 5)


def _cut(text, n):
    """text in at most n characters, cut at a word end with "…"."""
    text = " ".join((text or "").split())
    if len(text) <= n:
        return text
    if n < 2:
        return text[:max(n, 0)]
    head = text[:n - 1]
    k = head.rfind(" ")
    return (head[:k] if k > n // 2 else head).rstrip(" ,;:") + "…"


def _fit(form, line, source, error):
    """form with line, source and error, the error cut first to ERROR_CHARS and the source to SOURCE_CHARS, both less
    when the whole would pass TELL_CHARS (the error keeps the room the source can spare)."""
    source, error = unversioned(source), unversioned(error)
    room = TELL_CHARS - len(form % (line, "", ""))
    err = _cut(error, min(ERROR_CHARS, max(room - min(len(source), 40), 20)))
    src = _cut(source, min(SOURCE_CHARS, max(room - len(err), 10)))
    return unversioned(form % (line, src, err))[:TELL_CHARS]


def refit(text, n):
    """text, a whole SWALLOWED_ATTR or SWALLOWED line of tell()'s, in at most n characters, with its fixed words whole
    (what the piece's own except did and what to do): its quoted error cut first, to 20 characters at the least, then
    its source, to 10. None when text is no such line (or one cut at TELL_CHARS) or can't fit. For hints._line, which
    makes room for a fix this way (the independent checks, Nov 6)."""
    m = re.match(r"line (\d+) `", text or "")
    if not m:
        return None
    for form in (SWALLOWED_ATTR, SWALLOWED):
        _, mid, rest = form.split("%s")
        if not text.endswith(rest):
            continue
        body = text[m.end():len(text) - len(rest)]
        k = body.find(mid)
        if k < 0:
            return None
        src, err = body[:k], body[k + len(mid):]
        room = n - (len(text) - len(src) - len(err))
        if len(src) + len(err) <= room:
            return text
        err = _cut(err, max(20, room - len(src)))
        src = _cut(src, max(10, room - len(err)))
        if len(src) + len(err) > room:
            return None
        return text[:m.end()] + src + mid + err + rest
    return None


def tell(found_s1, found_s2):
    """Teacher-only lines (never in a target): what the piece hid and where, at most TELL_EACH of each kind (one
    skipped lookup told once, whatever materials it was made on)."""
    out = []
    for f in found_s1[:TELL_EACH]:
        form = SWALLOWED_ATTR if f["error"].startswith("AttributeError") and _MISSING_NAME.search(f["error"]) \
            else SWALLOWED
        out.append(_fit(form, f["line"], f.get("source") or "", f["error"]))
    told = []
    for f in found_s2:
        if (f["line"], f["key"]) in told or len(told) >= TELL_EACH:
            continue
        told.append((f["line"], f["key"]))
        close = list(f.get("close") or [])[:3]
        whole = (f["key"], f.get("owner") or "a node tree", f.get("node") or "node")
        for n, k in ((40, 3), (24, 1)):  # the names, then fewer of the close inputs and shorter names
            names = [_cut(str(x), n) for x in whole]
            line = SKIPPED % (f["line"], names[0], names[1], names[2], ", ".join(map(repr, close[:k])), close[0])
            if len(line) <= TELL_CHARS:
                break
        out.append(unversioned(line)[:TELL_CHARS])
    return out


# attr_miss's tell line (missed_tell): ours, teacher-only. It names where the keys are (the fact the teacher's notes
# give too, hints.BLENDER5's keyframes), since every stored repair of these steps dodged the missing name instead.
MISSED = ("line %d looked for %s on %s, which isn't there, so what it guards never ran and the keys stayed %s where "
          "the step asks for linear ones: set interpolation on the keyframe_points of "
          "anim_utils.action_get_channelbag_for_slot(action, slot).fcurves")
# Its fixed runs of 5 words or more between the slots, for hints.echoed_note (registered there with the notes)
MISSED_FORMS = tuple(p.strip(" :,") for p in re.split(r"%[sdr]", MISSED) if len(re.findall(r"\w+", p)) >= 5)


def missed_tell(found):
    """The tell line for missed_keys' findings (one line, the first guard's), at most TELL_CHARS long; [] for none."""
    if not found:
        return []
    f = found[0]
    keys = " and ".join(sorted(f.get("keys") or {})) or "unchanged"
    return [unversioned(MISSED % (f["line"], _cut(str(f.get("attr") or ""), 30), _cut(str(f.get("on") or ""), 30),
                                  keys))[:TELL_CHARS]]

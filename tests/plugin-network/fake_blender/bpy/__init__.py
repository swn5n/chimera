"""A tiny stand-in for Blender's bpy, for fake_blender/blender.py: a fresh scene (Cube, Camera, Light), objects,
the scene collection, a few operators, and the render_init handlers. Errors read like Blender's own."""
import time
from types import SimpleNamespace


class Object:
    def __init__(self, name, data=None):
        self.name, self.data = name, data
        self.location, self.rotation_euler, self.scale = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)

    def __repr__(self):
        return "bpy.data.objects['%s']" % self.name


class _Objects:
    def __init__(self):
        self._items = {}

    def new(self, name, object_data):
        base, n = name, 0
        while name in self._items:
            n += 1
            name = "%s.%03d" % (base, n)
        o = self._items[name] = Object(name, object_data)
        return o

    def get(self, name, default=None):
        return self._items.get(name, default)

    def __getitem__(self, key):
        if key not in self._items:
            raise KeyError('bpy_prop_collection[key]: key "%s" not found' % key)
        return self._items[key]

    def __contains__(self, key):
        return key in self._items

    def __iter__(self):
        return iter(list(self._items.values()))

    def __len__(self):
        return len(self._items)


class _CollectionObjects:
    def __init__(self, name):
        self._name, self._linked = name, []

    def link(self, obj):
        if obj in self._linked:
            raise RuntimeError("Error: Object '%s' already in collection '%s'" % (obj.name, self._name))
        self._linked.append(obj)

    def unlink(self, obj):
        if obj not in self._linked:
            raise RuntimeError("Error: Object '%s' not in collection '%s'" % (obj.name, self._name))
        self._linked.remove(obj)

    def __iter__(self):
        return iter(list(self._linked))

    def __len__(self):
        return len(self._linked)


data = SimpleNamespace(objects=_Objects())
_scene = SimpleNamespace(name="Scene", collection=SimpleNamespace(name="Scene Collection", objects=_CollectionObjects("Scene Collection")),
                         frame_start=1, frame_end=250)
for _name in ("Cube", "Camera", "Light"):
    _scene.collection.objects.link(data.objects.new(_name, None))
context = SimpleNamespace(scene=_scene)


def _persistent(fn):
    return fn


app = SimpleNamespace(version=(5, 0, 1), version_string="5.0.1", background=True,
                      handlers=SimpleNamespace(render_init=[], persistent=_persistent))


def _cube_add(**kw):
    o = data.objects.new("Cube", None)
    o.location = tuple(kw.get("location", (0.0, 0.0, 0.0)))
    context.scene.collection.objects.link(o)
    return {"FINISHED"}


def _save_as_mainfile(filepath="", **kw):
    try:
        with open(filepath, "wb") as f:
            f.write(b"BLENDER-v501")
    except OSError as e:
        raise RuntimeError("Error: Cannot open file %s@ for writing: %s" % (filepath, e.strerror)) from None
    return {"FINISHED"}


def _render(**kw):
    for fn in list(app.handlers.render_init):
        fn(context.scene)
    time.sleep(200)  # a long render
    return {"FINISHED"}


ops = SimpleNamespace(mesh=SimpleNamespace(primitive_cube_add=_cube_add),
                      wm=SimpleNamespace(save_as_mainfile=_save_as_mainfile),
                      render=SimpleNamespace(render=_render))

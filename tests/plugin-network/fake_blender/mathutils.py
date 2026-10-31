"""A tiny stand-in for Blender's mathutils: a Vector, and (like the real one) no radians."""


class Vector(tuple):
    def __new__(cls, values=(0.0, 0.0, 0.0)):
        return super().__new__(cls, (float(v) for v in values))

    x = property(lambda self: self[0])
    y = property(lambda self: self[1])
    z = property(lambda self: self[2])

    def __add__(self, other):
        return Vector(a + b for a, b in zip(self, other))

    def __sub__(self, other):
        return Vector(a - b for a, b in zip(self, other))

    def __mul__(self, k):
        return Vector(a * k for a in self)

    @property
    def length(self):
        return sum(a * a for a in self) ** 0.5

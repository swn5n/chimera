package main

import (
	"strings"
	"testing"
)

// The tests here are small. What proves the reader is worker-model/tools/
// check_join_parity.py, which holds it against Python's ast on real files and on
// damaged ones. These keep the shape of it in view without a Python around.

func parsed(t *testing.T, src string) *pyNode {
	t.Helper()
	tree, err := pyParse(src)
	if err != nil {
		t.Fatalf("%q: line %d: %s", src, err.line, err.msg)
	}
	return tree
}

func dumped(t *testing.T, src string) string {
	t.Helper()
	var b strings.Builder
	pyDump(&b, parsed(t, src))
	return b.String()
}

func TestPyStatementsAndTheirLines(t *testing.T) {
	src := `"""Doc."""
import bpy, os.path as p
from .. import a as b, c


@dec(1)
@other
def f(x, /, y=1, *z, k, **kw) -> int:
    return x

class C(Base, metaclass=M):
    pass

x = [
    1,
]
a = 1; b = 2
if x:
    y
elif z:
    w
else:
    v
`
	want := []struct {
		kind      string
		line, end int
		name      string
	}{
		{"Expr", 1, 1, ""}, {"Import", 2, 2, ""}, {"ImportFrom", 3, 3, ""}, {"FunctionDef", 8, 9, "f"}, {"ClassDef", 11, 12, "C"},
		{"Assign", 14, 16, ""}, {"Assign", 17, 17, ""}, {"Assign", 17, 17, ""}, {"If", 18, 23, ""},
	}
	tree := parsed(t, src)
	if len(tree.body) != len(want) {
		t.Fatalf("%d statements, want %d", len(tree.body), len(want))
	}
	for i, w := range want {
		n := tree.body[i]
		if n.kind != w.kind || n.line != w.line || n.end != w.end || (w.name != "" && n.name != w.name) {
			t.Errorf("statement %d: %s %d-%d %s, want %+v", i, n.kind, n.line, n.end, n.name, w)
		}
	}
	f := tree.body[3]
	if f.decorators[0].line != 6 || f.decorators[1].line != 7 {
		t.Errorf("decorators on %d and %d", f.decorators[0].line, f.decorators[1].line)
	}
	if p := f.params; p.positional != 2 || !p.varargs || p.keywordOnly != 1 || !p.kwargs {
		t.Errorf("params %+v", *p)
	}
	if imp := tree.body[1]; imp.names[1] != (pyAlias{"os.path", "p"}) {
		t.Errorf("import %+v", imp.names)
	}
	if from := tree.body[2]; from.level != 2 || from.name != "" || from.names[0] != (pyAlias{"a", "b"}) {
		t.Errorf("from %+v", from)
	}
	elif := tree.body[8].orelse[0]
	if elif.kind != "If" || elif.line != 20 || elif.end != 23 {
		t.Errorf("elif %s %d-%d", elif.kind, elif.line, elif.end)
	}
}

func TestPyWalkIsBreadthFirst(t *testing.T) {
	tree := parsed(t, "def f():\n    if x:\n        a()\n    b(c())\nd()\n")
	var calls []string
	for _, n := range pyWalk(tree) {
		if n.kind == "Call" {
			calls = append(calls, n.fn.name)
		}
	}
	if got := strings.Join(calls, " "); got != "d b a c" {
		t.Errorf("calls in order %s", got)
	}
}

func TestPyCallStartsWhereItsChainDoes(t *testing.T) {
	tree := parsed(t, "x = (\n  a\n).b(\n  c\n).d()\n")
	if n := tree.body[0].value; n.kind != "Call" || n.line != 1 {
		t.Errorf("%s on %d", n.kind, n.line)
	}
}

// Statements Python accepts that a weaker reader wouldn't. None of them may fail.
func TestPyReadsWhatPythonAccepts(t *testing.T) {
	for _, src := range []string{
		"match = 1\nmatch.x\nmatch[0]\nmatch(1)\ncase = 2\ntype = 3\n_ = 4\n",
		"match x:\n    case 1 | 2 if y: pass\n    case {\"a\": [b, *c], **d}: pass\n    case K(a=1) as e: pass\n    case -1.5: pass\n",
		"match (x), y:\n    case _: pass\n",
		"type X = int\ntype Y[T: int = str, *U, **V] = list[T]\ndef f[T](x: T) -> T: pass\nclass C[T](Base): pass\n",
		"if (n := 10) > 5: pass\nf(x := 1, y=(z := 2))\n[y := 1, y**2]\na[b := 1]\n{(k := 1): 2}\n",
		"def f(a, b=1, /, c=2, *, d, e=3, **k): pass\ndef g(*a: *Ts): pass\nlambda *a, b=1, **k: 0\nlambda: 0\nlambda x, /: x\n",
		"with (a as b, c as d,): pass\nwith (a, b): pass\nwith (a) as b, c: pass\nwith (yield): pass\nwith a as (b, c), d as e[0]: pass\n",
		"try: pass\nexcept* (A, B) as e: pass\nelse: pass\nfinally: pass\n",
		"print >>f, x\nx = yield\nx += yield y\nawait z\nasync def g():\n    async with a as b, c: pass\n    async for i in x: pass\n    return [i async for i in y]\n",
		"x: int\n(y): int = 1\na.b: int\nc[0]: str = 'x'\n*a, b = c\n[a, *b] = c\n(a, (b, c)) = d\nfor i, (j, *k) in x: pass\nfor x, in y: pass\nfor a[0] in b: pass\n",
		"a[1:2, ::3, ...]\na[*b]\na[*b, c]\na[b, *c]\na[:]\na[::]\nb = a[1:2:]\nx = *a, b\nreturn\nreturn *a, b\n",
		"f(*a, b, *c, d=1, *e, **f, g=2)\nf(a for a in b)\nclass D(*a, **k): pass\n{**a, 'b': 1, **c}\n{*a, b}\n{a: b for a, b in c if d if e}\n",
		"0xFF_FF + 0o77 + 0b1 + 1_000 + 1.5e-3 + 1j + .5 + 5. + 0_0 + 1e5j\n1if x else 2\nx = 1 if y else 2 if z else 3\nnot a is not b not in c\n",
		"del a, b[0], (c, d), [e]\ndel (a), b,\nglobal g, h\nassert a, b\nraise A from B\nimport a.b.c\nfrom . import x\nfrom ...y.z import (a, b as c,)\nfrom . import *\n",
		"x = 'a' \"b\" '''c''' r'\\d' u'e'\ny = b'' rb'\\x'\n",
		"f'{x!r:>{w}} {{literal}} {y=} {z = } {a:%H:%M} {\"nested\"} {f\"{1}\"} {d[\"k\"]} {lambda_} {(lambda: 1)()}'\n",
		"f'''{\n    x  # a comment\n}'''\nrf'\\{x}'\nf'\\N{BULLET} {x}'\nf\"{x:{y}.{z}}\" 'plain' f'{y}'\n",
		"if x:\n\ty\n\tz\nclass A:\n  def f(self):\n      pass\n  x = 1\n\n# done\n",
		"x = [\n    1,  # one\n\n    2,\n]\ny = 1 + \\\n    2\nif a and \\\n   b:\n    pass\n",
		"é = 1\nπ_2 = é\ndef naïve(): pass\n\f\nx = 1\n",
		"class A: pass; x = 1\nif a: b; c\nfor x in y: pass\nwhile 1: break\nelse: pass\n",
		"@a.b[c](d)\n@(yield)\n@x if y else z\ndef f(): pass\n",
		"", "\n\n", "# only a comment", "    # indented comment\n", "pass;\n", "\\\nx = 1\n",
	} {
		if _, err := pyParse(src); err != nil {
			t.Errorf("%q: line %d: %s", src, err.line, err.msg)
		}
	}
}

// Python 3.13's own words for the mistakes workers make. check_join_parity.py keeps the
// long list; these are the ones the stored replies really have.
func TestPySaysWhatPythonSays(t *testing.T) {
	for _, c := range []struct {
		src  string
		line int
		msg  string
	}{
		{"x = 1 2\n", 1, "invalid syntax"},
		{"x = 'abc\n", 1, "unterminated string literal (detected at line 1)"},
		{"x = \"\"\"abc\n\n\n", 1, "unterminated triple-quoted string literal (detected at line 3)"},
		{"x = 'a\\'\n", 1, "unterminated string literal (detected at line 1); perhaps you escaped the end quote?"},
		{"f(a=1,\n  b,\n  c)\n", 3, "positional argument follows keyword argument"},
		{"f(**a, b)\n", 1, "positional argument follows keyword argument unpacking"},
		{"[\n 1)\n", 2, "closing parenthesis ')' does not match opening parenthesis '[' on line 1"},
		{"x = [1 2]\n", 1, "invalid syntax. Perhaps you forgot a comma?"},
		{"x = {\n 'a': 1\n 'b': 2\n}\n", 2, "invalid syntax. Perhaps you forgot a comma?"},
		{"{'a': 1, b c}\n", 1, "':' expected after dictionary key"},
		{"x = (1,\n2\ny = 3\n", 1, "'(' was never closed"},
		{"a[\n", 1, "'[' was never closed"},
		{"0777\n", 1, "leading zeros in decimal integer literals are not permitted; use an 0o prefix for octal integers"},
		{"1abc\n", 1, "invalid decimal literal"},
		{"2.else8\n", 1, "invalid decimal literal"},
		{"def f():\nx = 1\n", 2, "expected an indented block after function definition on line 1"},
		{"if x:\n", 1, "expected an indented block after 'if' statement on line 1"},
		{"x = a\u202fb\n", 1, "invalid non-printable character U+202F"},
		{"x = 5 ±3\n", 1, "invalid character '±' (U+00B1)"},
		{"a + b = c\n", 1, "cannot assign to expression here. Maybe you meant '==' instead of '='?"},
		{"f() = 1\n", 1, "cannot assign to function call here. Maybe you meant '==' instead of '='?"},
		{"None = 1\n", 1, "cannot assign to None"},
		{"x = f() = 3\n", 1, "cannot assign to function call"},
		{"if x = 1:\n  y\n", 1, "invalid syntax. Maybe you meant '==' or ':=' instead of '='?"},
		{"if x\n  y\n", 1, "expected ':'"},
		{"def f:\n  x\n", 1, "expected '('"},
		{"def f() x:\n  y\n", 1, "expected ':'"},
		{"try:\n  x\n", 2, "expected 'except' or 'finally' block"},
		{"  x = 1\n", 1, "unexpected indent"},
		{"if x:\n    y\n  z\n", 3, "unindent does not match any outer indentation level"},
		{"if x:\n\ty\n        z\n", 3, "inconsistent use of tabs and spaces in indentation"},
		{"x = 1 \\ y\n", 1, "unexpected character after line continuation character"},
		{"x = 1\\", 1, "unexpected EOF while parsing"},
		{"print 'x'\n", 1, "Missing parentheses in call to 'print'. Did you mean print(...)?"},
		{"x = 1 if y\n", 1, "expected 'else' after 'if' expression"},
		{"'C:\\Users\\x'\n", 1, "(unicode error) 'unicodeescape' codec can't decode bytes in position 2-3: truncated \\UXXXXXXXX escape"},
		{"'a' b'b'\n", 1, "cannot mix bytes and nonbytes literals"},
		{"f'{}'\n", 1, "f-string: valid expression required before '}'"},
		{"f'{a'\n", 1, "f-string: expecting '}'"},
		{"f'}'\n", 1, "f-string: single '}' is not allowed"},
		{"a\x00b\n", 0, "source code string cannot contain null bytes"},
	} {
		_, err := pyParse(c.src)
		if err == nil {
			t.Errorf("%q parsed", c.src)
		} else if err.line != c.line || err.msg != c.msg {
			t.Errorf("%q: line %d: %s", c.src, err.line, err.msg)
		}
	}
}

// What keeps an error pass from going round for ever must not limit a valid script.
func TestPyHasNoLimitOnValidCode(t *testing.T) {
	src := strings.Repeat("for x in y:\n    del a, b\n    z = {1: 2, 3: 4}\n", pyMaxTries)
	tree := parsed(t, src)
	if len(tree.body) != pyMaxTries {
		t.Errorf("%d statements", len(tree.body))
	}
}

// A script that's wrong in a way that sends the error pass round and round still ends.
func TestPyGivesUpOnTheWords(t *testing.T) {
	src := "x = " + strings.Repeat("a[", 150) + "1" + strings.Repeat("]", 150) + " 2\n"
	if _, err := pyParse(src); err == nil || err.msg != "invalid syntax" {
		t.Errorf("%+v", err)
	}
}

func TestPyStringValues(t *testing.T) {
	for _, c := range []struct{ src, kind, want string }{
		{`"a" 'b'`, "str", "ab"},
		{`"\x41\101\u0041\n\q"`, "str", "AAA\n\\q"},
		{`r"\n"`, "str", `\n`},
		{`b"a"`, "bytes", "a"},
		{"\"a\\\nb\"", "str", "ab"},
		{`"""x"y"""`, "str", `x"y`},
		{`"\N{BULLET}"`, "str", `\N{BULLET}`}, // the app has no table of names
	} {
		n := parsed(t, c.src).body[0].value
		if n.kind != "Constant" || n.constant != c.kind || n.str != c.want {
			t.Errorf("%s: %s %s %q", c.src, n.kind, n.constant, n.str)
		}
	}
	if n := parsed(t, `f"{a}" "b"`).body[0].value; n.kind != "JoinedStr" {
		t.Errorf("an f-string joined to a string is %s", n.kind)
	}
}

func TestPyReadsInsideFStrings(t *testing.T) {
	want := "(Module 0 (Expr 1-1 (JoinedStr 1 (FormattedValue 1 (Call 1 (Name 1 g) (Name 1 x)) (JoinedStr 1 (FormattedValue 1 (Name 1 w)))))))"
	if got := dumped(t, `f"{g(x):{w}}"`); got != want {
		t.Errorf("%s", got)
	}
}

func TestPyRepr(t *testing.T) {
	for s, want := range map[string]string{
		"a": `'a'`, "it's": `"it's"`, `it's "x"`: `'it\'s "x"'`, "a\nb\t\\": `'a\nb\t\\'`, "é→": `'é→'`, "\x01\u202f": `'\x01\u202f'`,
	} {
		if got := pyRepr(s); got != want {
			t.Errorf("%q: %s", s, got)
		}
	}
}

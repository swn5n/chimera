package main

import (
	"strings"
	"testing"
)

func gapCodes(p *workerPiece) string {
	var c []string
	for _, i := range p.Issues {
		c = append(c, i.Code)
	}
	return strings.Join(c, " ")
}

func TestGapsSection(t *testing.T) {
	if got := findSection("## A\nx\n\n# Top\ny\n", "a", 0); got != "## A\nx" {
		t.Errorf("%q", got)
	}
}

const gapHand = "\n\n```handoff\nprovides: a\nuses: none\nassumed: none\n```"

func gapBlender(body string) *workerPiece {
	return validatePiece("```python\nimport bpy\nSETTINGS_s1 = {}\n\ndef build_s1(ctx):\n"+body+"\n\nif __name__ == \"__main__\":\n    build_s1({\"scene\": bpy.context.scene, \"collection\": bpy.context.scene.collection, \"objects\": {}})\n```"+gapHand, pieceAsk{Mode: modeBlender, Sid: "s1", RejectCut: true})
}

func TestGapsFinalbody(t *testing.T) {
	if p := gapBlender("    for o in bpy.data.objects:\n        try:\n            pass\n        finally:\n            bpy.data.objects.remove(o)"); !strings.Contains(gapCodes(p), "deletes_scene") {
		t.Error(gapCodes(p))
	}
}

func TestGapsAlias(t *testing.T) {
	if p := gapBlender("    a = bpy.data\n    b = a\n    for o in b.objects:\n        bpy.data.objects.remove(o)"); !strings.Contains(gapCodes(p), "deletes_scene") {
		t.Error(gapCodes(p))
	}
}

func TestGapsTypeChecking(t *testing.T) {
	p := validatePiece("```python\nimport typing\nif typing.TYPE_CHECKING:\n    import os\n\ndef f():\n    pass\n```"+gapHand, pieceAsk{Mode: modePythonScript, Sid: "s1", RejectCut: true})
	if strings.Contains(gapCodes(p), "runs_on_import") {
		t.Error(gapCodes(p))
	}
}

func TestGapsLimits(t *testing.T) {
	bad := func(name, src, want string) {
		if _, e := pyParse(src); e == nil || !strings.Contains(e.msg, want) {
			t.Errorf("%s: %+v", name, e)
		}
	}
	bad("level", strings.Repeat("(", 201)+"1"+strings.Repeat(")", 201)+"\n", "too many nested parentheses")
	var deep strings.Builder
	for i := 0; i < 100; i++ {
		deep.WriteString(strings.Repeat(" ", i) + "if x:\n")
	}
	deep.WriteString(strings.Repeat(" ", 100) + "pass\n")
	bad("indent", deep.String(), "too many levels of indentation")
	f := "1"
	for i := 0; i < 160; i++ {
		f = `f"{` + f + `}"`
	}
	bad("fstrings", f+"\n", "too")
	if _, e := pyParse("type X[*Ts = *a] = int\n"); e != nil {
		t.Errorf("star default: %+v", e)
	}
}

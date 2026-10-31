package main

// Facts before opinions, past the crash: a script that runs can still build the
// wrong thing, and the reviewer can't see a render. On Oct 31 every script that ran
// was reviewed as done, one with a camera that saw nothing and others with the
// scene out of shot. blenderSceneFacts measures the scene as the script ends, and
// this says what's wrong with it. It claims little, on purpose, because a false
// alarm costs repairs that can damage a good scene: a task that says to frame
// everything and objects that are provably outside the frame, a camera that can
// reach nothing at all, objects with no geometry, and the factory cube in a scene
// built from nothing. What it can't prove (a table upside down, a shot that's merely
// bad) stays with the reviewer. Goals are read in English: anything else goes unjudged.
// Two reviews with real scripts wrote scenes a person would keep to set this off:
// the tests carry what they found.

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
)

// sceneObject and sceneFacts are blenderSceneFacts's line.
type sceneObject struct {
	Name  string    `json:"name"`
	At    []float64 `json:"at"`
	Size  []float64 `json:"size"`
	Hits  int       `json:"hits"`  // rays from the camera that reached it first
	Frame bool      `json:"frame"` // its bounding box may be inside the frame
}

type sceneCamera struct {
	Name  string    `json:"name"`
	At    []float64 `json:"at"`
	Ahead []float64 `json:"ahead"`
	Lens  float64   `json:"lens"`
	Type  string    `json:"type"`
	Clip  []float64 `json:"clip"` // clip_start and clip_end
}

type sceneFacts struct {
	Camera   *sceneCamera  `json:"camera"`
	Objects  []sceneObject `json:"objects"` // unseen ones first; may be only some of them
	Total    int           `json:"total"`
	Seen     int           `json:"seen"`
	Out      int           `json:"out"`    // nowhere near the frame
	Filled   float64       `json:"filled"` // the share of the frame with anything in it
	Cube     bool          `json:"cube"`   // the default cube, as it came
	Empty    []string      `json:"empty"`  // objects with no geometry: the first few
	Blank    int           `json:"blank"`  // how many there are
	Animated bool          `json:"animated"`
	Span     [][]float64   `json:"span"`   // lowest and highest corner of the main objects
	Pose     *scenePose    `json:"pose"`   // a view that frames them, tried
	Unseen   bool          `json:"unseen"` // something renders that rays can't reach
}

// scenePose is a camera view that was tried, with what it saw.
type scenePose struct {
	At       []float64 `json:"at"`
	Rotation []float64 `json:"rotation"` // Euler XYZ, radians
	Sees     int       `json:"sees"`
	ClipEnd  float64   `json:"clip_end"` // set if the camera has to reach further
}

var (
	cameraGoalRe = regexp.MustCompile(`(?i)\b(?:with|add|adds|adding|and|plus|place|places|position|set up|sets up|put|aim|point|needs?|has|have|include|includes|including|use|using)\s+(?:(?:a|an|the|one|its|another|second)\s+)?(?:[\w-]+\s+){0,2}cameras?\b|\bcameras?\s+(?:that|which|to|on|at|is|should|must|will|framing|frames?|sees?|shows?|showing|looking|looks|pointed|pointing|aimed|facing)\b|\bfram(?:es?|ing)\s+(?:it|them|this|that|everything|all|the)\b|\bin (?:the )?(?:shot|view)\b|\brender(?:s|ed|ing)?\b`)
	noCameraRe   = regexp.MustCompile(`(?i)\b(?:no need (?:to|for)|don'?t|do not|without|never|not|no)\s+(?:\w+\s+)?(?:render|camera)|\b(?:model|sculpt|design)\s+(?:a|an|the)\s+(?:[\w-]+\s+){0,3}camera\b|\b(?:film|vintage|toy|security|cctv|retro|polaroid|dslr)\s+camera\b`)
	wholeGoalRe  = regexp.MustCompile(`(?i)\b(?:frames?|framing|shows?|showing|sees?|captures?|fits?)\s+(?:\w+\s+)?(?:everything\b|it all\b|all of (?:it|them)\b|all\s*(?:[.,;:!?]|$)|the (?:whole|entire)\s+(?:scene|thing|set|composition|layout)\b)|\b(?:everything|all of it|it all) (?:is )?in (?:the )?(?:frame|shot|view)\b`)
	newSceneRe   = regexp.MustCompile(`(?i)\b(?:build|builds|building|create|creates|creating|make|makes|making|compose|composes|generate|generates|design|designs|model|models|set up|sets up)\s+(?:a|an|one|the)\s+(?:[\w,-]+\s+){0,3}scene\b|^\W*(?:a|an)\s+(?:[\w,-]+\s+){0,3}scene\b`)
	ownSceneRe   = regexp.MustCompile(`(?i)\b(?:my|our|this|current|existing|open)\s+(?:\w+\s+)?(?:scene|file|project)\b|\b(?:add|put|place|insert|drop)\b.*\b(?:to|into|in|on)\s+the\s+scene\b|\b(?:add-?on|operator|function|class|plug-?in)\b`)
	aimedGoalRe  = regexp.MustCompile(`(?i)\bcameras?\s+(?:that|which|to)\s+(?:\w+\s+)?(?:fram|sees?\b|shows?\b|looks?\b|captures?\b)|\brender\s+(?:it|them|this|that|the)\b`)
	addsRe       = regexp.MustCompile(`primitive_\w+_add|\.objects\.new\(|object\.\w+_add\(`)
	takesRe      = regexp.MustCompile(`active_object|context\.object\b|selected_objects|scene\.objects|view_layer\.objects|data\.objects\[`)
	emptyGoalRe  = regexp.MustCompile(`(?i)\b(?:empty|blank)\s+(?:\w+\s+)?(?:mesh|object)`)
	cubeRe       = regexp.MustCompile(`(?i)\bcubes?\b`)
)

// takeScene takes blenderSceneFacts's lines out of what a run printed and says
// whether it got as far as measuring.
func takeScene(res runResult) (runResult, *sceneFacts, bool) {
	var facts *sceneFacts
	measuring := false
	cut := func(s string) string {
		after := false // whatever measuring sets off isn't the script's doing
		if !strings.Contains(s, "chimera-check: ") {
			return s
		}
		lines := strings.Split(s, "\n")
		kept := lines[:0]
		for _, l := range lines {
			t := strings.TrimSpace(l)
			if t == sceneStartMarker {
				measuring, after = true, true
				continue
			}
			if text, ok := strings.CutPrefix(t, sceneMarker); ok {
				var f sceneFacts
				if json.Unmarshal([]byte(text), &f) == nil {
					facts = &f
				}
				continue
			}
			if !after || strings.Contains(l, renderStopMarker) { // output and errors arrive in either order
				kept = append(kept, l)
			}
		}
		return strings.Join(kept, "\n")
	}
	res.Output, res.Stderr = cut(res.Output), cut(res.Stderr)
	return res, facts, measuring
}

// sceneFaults says what's certainly wrong with a scene, given what the task
// asked for. Empty means nothing the check can tell.
func sceneFaults(f *sceneFacts, goal, script string) []string {
	if strings.Contains(script, "register_class") {
		return nil // an add-on: what it builds comes when it's used
	}
	var out []string
	own := ownSceneRe.MatchString(goal)
	moving := f.Animated || strings.Contains(script, "app.handlers") // what's there now isn't the end of it
	if f.Blank > 0 && !moving && !own && !emptyGoalRe.MatchString(goal) {
		out = append(out, fmt.Sprintf("%s no geometry.", isOrAre(f.Empty, f.Blank, "has", "have")))
	}
	if f.Cube && newSceneRe.MatchString(goal) && !own && !cubeRe.MatchString(goal) && !strings.Contains(script, "'Cube'") && !strings.Contains(script, `"Cube"`) && !takesWhatsThere(script) {
		out = append(out, "The default cube is still in the scene.")
	}
	wantsCamera := cameraGoalRe.MatchString(goal) && !noCameraRe.MatchString(goal) && !own
	if f.Camera == nil {
		if wantsCamera && (wholeGoalRe.MatchString(goal) || newSceneRe.MatchString(goal) || aimedGoalRe.MatchString(goal)) {
			out = append(out, "The scene has no camera.")
		}
		return out
	}
	whole := wholeGoalRe.MatchString(goal)
	if f.Total == 0 || !wantsCamera || !(whole || newSceneRe.MatchString(goal)) || moving || f.Camera.Type == "PANO" {
		return out // a fresh scene says nothing about what a camera sees in the person's own file
	}
	switch {
	case f.Seen == 0 && f.Filled == 0 && f.Out == f.Total && !f.Unseen:
		out = append(out, fmt.Sprintf("The camera sees none of the %d objects.", f.Total))
	case f.Out > 0 && whole && !among(f.Camera.At, f.Span):
		var names []string
		for _, o := range f.Objects {
			if o.Hits == 0 && !o.Frame {
				names = append(names, o.Name)
			}
		}
		out = append(out, fmt.Sprintf("%s out of frame.", isOrAre(names, f.Out, "is", "are")))
	}
	return out
}

// takesWhatsThere says whether a script picks up what's in the scene before it
// adds anything: in a factory scene that's the cube, used on purpose.
func takesWhatsThere(script string) bool {
	if at := addsRe.FindStringIndex(script); at != nil {
		script = script[:at[0]]
	}
	return takesRe.MatchString(script)
}

// among says whether the camera stands inside the objects' span: in a room or on a
// street there's always something behind it, and only going outside would frame that.
func among(at []float64, span [][]float64) bool {
	if len(at) != 3 || len(span) != 2 {
		return false
	}
	for i := range at {
		if at[i] < span[0][i] || at[i] > span[1][i] {
			return false
		}
	}
	return true
}

// isOrAre names a few things and how many more there are, with the verb that fits.
func isOrAre(names []string, total int, one, many string) string {
	if len(names) > 3 {
		names = names[:3]
	}
	s := strings.Join(names, ", ")
	if total > len(names) {
		return fmt.Sprintf("%s and %d more %s", s, total-len(names), many)
	}
	if total > 1 {
		return s + " " + many
	}
	return s + " " + one
}

func coords(v []float64) string {
	parts := make([]string, len(v))
	for i, x := range v {
		parts[i] = fmt.Sprintf("%.2f", x)
	}
	return "(" + strings.Join(parts, ", ") + ")"
}

// measured says what the scene holds, for a model working out a fix.
func measured(f *sceneFacts) string {
	var b strings.Builder
	if c := f.Camera; c != nil {
		fmt.Fprintf(&b, "The camera %s is at %s, looking along %s, with a %.0f mm lens", c.Name, coords(c.At), coords(c.Ahead), c.Lens)
		if len(c.Clip) == 2 {
			fmt.Fprintf(&b, " and clipping from %g to %g", c.Clip[0], c.Clip[1])
		}
		b.WriteString(". ")
	}
	if len(f.Span) == 2 {
		fmt.Fprintf(&b, "The objects reach from %s to %s. ", coords(f.Span[0]), coords(f.Span[1]))
	}
	if p := f.Pose; p != nil && len(p.At) == 3 && len(p.Rotation) == 3 && p.Sees > 0 && p.Sees >= f.Seen {
		clip := ""
		if p.ClipEnd > 0 {
			clip = fmt.Sprintf(", clip_end = %g on its data", p.ClipEnd)
		}
		fmt.Fprintf(&b, "Tried and measured: with rotation_mode = 'XYZ', location = %s, rotation_euler = (%.4f, %.4f, %.4f)%s, and nothing else aiming it (no parent, no constraint, no later change), the camera frames the objects and rays reach %d of the %d. Set those exactly, and remove whatever else aims it. ",
			coords(p.At), p.Rotation[0], p.Rotation[1], p.Rotation[2], clip, p.Sees, f.Total)
	}
	if f.Total > 0 {
		fmt.Fprintf(&b, "%d of the %d objects are out of frame, and %.0f%% of the frame has something in it.", f.Out, f.Total, 100*f.Filled)
	}
	for _, o := range f.Objects {
		state := "in frame"
		switch {
		case o.Hits > 0:
			state = fmt.Sprintf("takes up %.0f%% of the frame", 100*float64(o.Hits)/(64*36))
		case !o.Frame:
			state = "out of frame"
		}
		fmt.Fprintf(&b, "\n%s at %s, size %s: %s.", o.Name, coords(o.At), coords(o.Size), state)
	}
	if len(f.Objects) < f.Total {
		fmt.Fprintf(&b, "\n… and %d more.", f.Total-len(f.Objects))
	}
	return b.String()
}

// withScene adds to a check that passed what was measured: the scene may be why
// the script isn't done after all.
func withScene(c resultCheck, f *sceneFacts, goal, script string) resultCheck {
	if f == nil {
		return c
	}
	faults := sceneFaults(f, goal, script)
	if len(faults) == 0 {
		if f.Camera != nil && f.Total > 0 && !f.Animated {
			c.Summary += fmt.Sprintf(" %d of its %d objects are in the camera's frame.", f.Total-f.Out, f.Total)
		}
		return c
	}
	c.Outcome = "wrong_scene"
	c.Error = strings.Join(faults, " ")
	c.Summary = strings.TrimSuffix(c.Summary, ".") + ", but the scene is wrong. " + c.Error
	c.Measured, c.Faults = measured(f), len(faults)
	if f.Total > 0 {
		c.Seen = float64(f.Total-f.Out) / float64(f.Total)
	}
	return c
}

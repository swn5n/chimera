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
//
// Most tasks never say to frame anything: "a scene of a cup on a table" is what
// people ask for. A scene is something to look at, so it wants a camera, and that
// camera has to show what the task names. Only what it names: a review of 280 good
// scenes found no count of objects that tells a bad shot from a wide one, since a
// wall of tiles or a forest is mostly out of any good picture.

import (
	"encoding/json"
	"fmt"
	"regexp"
	"slices"
	"strings"
)

// sceneObject and sceneFacts are blenderSceneFacts's line.
type sceneObject struct {
	Name  string    `json:"name"`
	At    []float64 `json:"at"`
	Size  []float64 `json:"size"`
	Hits  int       `json:"hits"`  // rays from the camera that reached it first
	Frame bool      `json:"frame"` // its bounding box may be inside the frame
	Cut   bool      `json:"cut"`   // the frame could hold it, but holds little of it and rays hardly reach it
	Share float64   `json:"share"` // how much of its box the frame holds, if it's cut
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
	Out      int           `json:"out"` // nowhere near the frame
	Cut      int           `json:"cut"` // in the frame, barely
	Cameras  int           `json:"cameras"`
	Shown    []string      `json:"shown"`  // the words in the names of what's in the frame
	Hidden   []string      `json:"hidden"` // and of what isn't
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
	noCameraRe   = regexp.MustCompile(`(?i)\b(?:i['’]?ll|i will|we['’]?ll|let me)\s+(?:[\w-]+\s+){0,3}(?:cam(?:era)?s?\b|render)|\b(?:leave|forget|ignore|skip|omit|no)\s+(?:about\s+)?(?:the\s+|a\s+)?cam(?:era)?s?\b|\bcam(?:era)?s?\s+(?:does\s?n'?t|do\s?n'?t|is\s?n'?t|not)\s+(?:matter|needed|important)\b|\b(?:no need (?:to|for)|don'?t|doesn'?t|do not|does not|without|never|not|no|skip|omit|leave out)\s+(?:[\w-]+\s+){0,3}(?:render|cameras?\b)|\bcameras?\b[^.]*\b(?:not needed|myself|later)\b|\b(?:model|sculpt|design)\s+(?:a|an|the)\s+(?:[\w-]+\s+){0,3}camera\b|\b(?:film|vintage|toy|security|cctv|retro|polaroid|dslr)\s+camera\b`)
	wholeGoalRe  = regexp.MustCompile(`(?i)\b(?:frames?|framing|shows?|showing|sees?|captures?|fits?)\s+(?:\w+\s+)?(?:everything\b|it all\b|all of (?:it|them)\b|all\s*(?:[.,;:!?]|$)|the (?:whole|entire)\s+(?:scene|thing|set|composition|layout)\b)|\b(?:everything|all of it|it all) (?:is )?in (?:the )?(?:frame|shot|view)\b`)
	newSceneRe   = regexp.MustCompile(`(?i)\b(?:build|builds|building|create|creates|creating|make|makes|making|compose|composes|generate|generates|design|designs|model|models|set up|sets up|want|need|give|draw|produce|render|show)\s+(?:me\s+|us\s+)?(?:(?:a|an|one)\s+(?:[\w,-]+\s+){0,3}` + sceneWords + `\b|the\s+(?:[\w,-]+\s+){0,3}` + sceneWords + `\s+(?:of|described|below)\b)|^\W*(?:a|an)\s+(?:[\w,-]+\s+){0,3}` + sceneWords + `\b|(?:\b(?:a|an)\s+(?:[\w,-]+\s+){0,3}|\b(?:blender|3d)\s+|^\W*)(?:scene|diorama|still life)\s+(?:of|with|showing|featuring|containing)\b`)
	ownSceneRe   = regexp.MustCompile(`(?i)\b(?:my|our|this|current|existing|open)\s+(?:\w+\s+)?(?:scene|file|project)\b|\b(?:add|put|place|insert|drop|create|make)\b.*\b(?:to|into|in|on)\s+the\s+scene\b|\b(?:add-?on|operator|function|class|plug-?in)\b|\b(?:in|to|into|for|from|of|across|throughout)\s+(?:a|an)\s+(?:[\w,-]+\s+){0,3}scene\b|\bscene[- ](?:graph|collection|wide|strip|transition|node|properties|settings|data|units)\b|\blandscape\s+(?:painting|format|orientation|mode|poster|photo|picture|print)\b`)
	aimedGoalRe  = regexp.MustCompile(`(?i)\bcameras?\s+(?:that|which|to)\s+(?:\w+\s+)?(?:fram|sees?\b|shows?\b|looks?\b|captures?\b)|\brender\s+(?:it|them|this|that|the)\b`)
	addsRe       = regexp.MustCompile(`primitive_\w+_add|\.objects\.new\(|object\.\w+_add\(`)
	takesRe      = regexp.MustCompile(`active_object|context\.object\b|selected_objects|scene\.objects|view_layer\.objects|data\.objects\[`)
	emptyGoalRe  = regexp.MustCompile(`(?i)\b(?:empty|blank)\s+(?:\w+\s+)?(?:mesh|object|scene)|\bscene\s+with\s+nothing\b`)
	cubeRe       = regexp.MustCompile(`(?i)\bcubes?\b`)
	// A task that wants some of it out of shot, or isn't about what's in front of the camera.
	tightGoalRe = regexp.MustCompile(`(?i)\bclose[- ]?ups?\b|\bmacro\b|\bcrop(?:s|ped|ping)?\b|\bdetail (?:shot|view)\b|\bportrait\b|\bout of (?:the )?(?:shot|frame|view)\b|\boff[- ]?(?:camera|screen|frame)\b|\bbehind the camera\b|\breflect(?:s|ed|ing|ion|ions)?\b|\bsilhouettes?\b|\bshadows? (?:of|from|cast)\b|\bfirst[- ]person\b|\bpov\b`)
	// A task that says what the camera is for: that's what counts, not what the check would pick.
	shotGoalRe = regexp.MustCompile(`(?i)\bcameras?\s+(?:that|which|to|should|must|will|shall|needs? to|has to|is|are)\s+(?:\w+\s+){0,2}(?:fram|sees?\b|shows?\b|looks?\b|captures?\b|points?\b|aims?\b|focus)|\bcameras?\s+(?:looking|aimed|pointed|pointing|focused|facing|at|on|in front of|behind|above|below|beside|near|[\d.]+)\b|\b(?:aim|point|put|place|position|move|set|tilt)\s+(?:the|a|your)\s+(?:[\w-]+\s+){0,2}cameras?\b|\b(?:mm|metres?|meters?)\s+camera\b|\bfram(?:e|es|ing)\s+(?:the|a|an)\b|\bzoom(?:s|ed|ing)?\b|\bfocus(?:es|ed|ing)?\s+on\b|\btight (?:shot|framing)\b|\bdepth of field\b`)
	// The word before a break ends a noun phrase: "a small wooden cabin near a lake" names a cabin and a lake.
	goalThingRe = regexp.MustCompile(`([a-z]{3,})(?:\s*(?:[,.;:!?]|$)|\s+(?:and|or|on|in|at|by|with|of|near|next|under|over|beside|behind|lit|also|that|which|plus|from|for|to|around|standing|sitting|parked)\b)`)
	// What's in a cup isn't another thing to find: "a cup of tea".
	contentsRe = regexp.MustCompile(`\b(cups?|mugs?|glass(?:es)?|bowls?|plates?|bottles?|jars?|vases?|baskets?|pots?|stacks?|piles?)\s+of\s+(?:[\w-]+\s+)?[\w-]+`)
	// What lights a shot can stand outside it, unless the task says where it stands.
	offShotRe = regexp.MustCompile(`\b(?:(?:lit|illuminated)\s+(?:by|from|through)|(?:sun(?:light|shine)?|moon(?:light)?|daylight|light)\s+(?:\w+\s+){0,2}?(?:through|thru|from))\s+(?:(?:a|an|the)\s+)?(?:[\w-]+\s+){0,2}?[a-z]+(?:\s+(?:from|on|to)\s+the\s+(?:left|right|side|above|wall|ceiling))?\s*(?:[,.;:!?]|$)`)
	// "a scene of a farm with a barn" says where, then what.
	settingRe  = regexp.MustCompile(`\b(?:scene|diorama|landscape)\s+of\s+(?:(?:a|an|the)\s+)?(?:[\w-]+\s+){0,2}?[\w-]+\s+with\b`)
	nameWordRe = regexp.MustCompile(`[A-Z]+[a-z]*|[a-z]+`)
	// "a girl reading" isn't a reading, but "a painting" and "the ceiling" are things.
	determinerRe = regexp.MustCompile(`\b(?:a|an|the|my|our|this|that)\s+$`)
)

// sceneWords are what a task calls something to look at.
const sceneWords = `(?:scene|landscape|diorama|still life)`

// notThings are words that end a phrase without naming anything to see.
var notThings = map[string]bool{"blender": true, "scene": true, "landscape": true, "environment": true, "diorama": true, "life": true, "camera": true, "light": true, "lights": true, "lighting": true, "sun": true,
	"render": true, "mesh": true, "object": true, "objects": true, "model": true, "script": true, "python": true, "chimera": true, "main": true, "part": true, "parts": true,
	"can": true, "could": true, "will": true, "would": true, "use": true, "using": true,
	"spotlight": true, "spotlights": true, "frame": true, "picture": true, "image": true, "screen": true, "shot": true, "view": true,
	"left": true, "right": true, "top": true, "bottom": true, "front": true, "back": true, "side": true, "sides": true, "middle": true, "center": true, "centre": true, "corner": true, "edge": true, "near": true, "next": true, "behind": true, "above": true, "below": true}

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
	if f.Cube && addsRe.MatchString(script) && newSceneRe.MatchString(goal) && !own && !cubeRe.MatchString(goal) && !strings.Contains(script, "'Cube'") && !strings.Contains(script, `"Cube"`) && !takesWhatsThere(script) {
		out = append(out, "The default cube is still in the scene.")
	}
	isScene := newSceneRe.MatchString(goal)
	wantsCamera := (cameraGoalRe.MatchString(goal) || isScene) && !noCameraRe.MatchString(goal) && !own
	if f.Camera == nil {
		if wantsCamera && (wholeGoalRe.MatchString(goal) || isScene || aimedGoalRe.MatchString(goal)) && !(f.Total == 0 && emptyGoalRe.MatchString(goal)) {
			out = append(out, "The scene has no camera.")
		}
		return out
	}
	whole := wholeGoalRe.MatchString(goal)
	if f.Total == 0 || !wantsCamera || !(whole || isScene) || moving || f.Camera.Type == "PANO" {
		return out // a fresh scene says nothing about what a camera sees in the person's own file
	}
	inside := among(f.Camera.At, f.Span)
	switch {
	case f.Seen == 0 && f.Filled == 0 && f.Out == f.Total && !f.Unseen:
		out = append(out, fmt.Sprintf("The camera sees none of the %d objects.", f.Total))
	case f.Out > 0 && whole && !inside && !moreOfTheSame(f):
		var names []string
		for _, o := range f.Objects {
			if o.Hits == 0 && !o.Frame {
				names = append(names, o.Name)
			}
		}
		out = append(out, fmt.Sprintf("%s out of frame.", isOrAre(names, f.Out, "is", "are")))
	case isScene && !tightGoalRe.MatchString(goal) && (whole || !shotGoalRe.MatchString(goal)):
		// In a room there's always something behind the camera, and with a second
		// camera this one may not be the shot for it: only showing nothing that
		// was asked for is wrong there.
		if names := unshown(goal, f); len(names) > 0 && ((!inside && f.Cameras < 2) || noneNamedShown(goal, f)) {
			out = append(out, fmt.Sprintf("The camera doesn't show %s, which the task asked for.", strings.Join(names, ", ")))
		}
	}
	return out
}

// moreOfTheSame says whether all that's out of the frame is more of what's in it:
// the forest behind a camp.
func moreOfTheSame(f *sceneFacts) bool {
	for _, w := range f.Hidden {
		if !hasWord(f.Shown, w) {
			return false
		}
	}
	return len(f.Hidden) > 0
}

// outOfFrame says whether most or all of an object is outside the frame.
func (o sceneObject) outOfFrame() bool {
	return (o.Hits == 0 && !o.Frame) || o.Cut
}

// goalThings are the words a task uses to name something it wants to see.
func goalThings(goal string) []string {
	goal = strings.ToLower(goal)
	goal = offShotRe.ReplaceAllString(goal, ", ")
	goal = settingRe.ReplaceAllString(goal, ", ")
	goal = contentsRe.ReplaceAllString(goal, "$1, ")
	var out []string
	for _, m := range goalThingRe.FindAllStringSubmatchIndex(goal, -1) {
		w := goal[m[2]:m[3]]
		if notThings[w] || (len(w) > 5 && strings.HasSuffix(w, "ing") && !determinerRe.MatchString(goal[:m[2]])) {
			continue
		}
		out = append(out, w)
	}
	return out
}

// isPlace says whether a word says where the rest stands, as in "a bike in a garage".
// What stands there is in the frame, so the place is too, whatever one of its extras
// is called: a Garage_Door above the shot isn't the garage.
func isPlace(goal, w string) bool {
	return regexp.MustCompile(`(?i)\b(?:in|on|at)\s+(?:a|an|the|my|our|his|her|their)\s+(?:[\w-]+\s+){0,2}` + regexp.QuoteMeta(w) + `\b`).MatchString(goal)
}

// nameWords splits an object's name the way blenderSceneFacts does.
func nameWords(name string) []string {
	var out []string
	for _, w := range nameWordRe.FindAllString(name, -1) {
		// RE2 has no lookahead: capitals before a word end one letter early, as in LEDLamp.
		caps := len(w) - len(strings.TrimLeft(w, "ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
		if caps > 1 && caps < len(w) {
			out = append(out, strings.ToLower(w[:caps-1]))
			w = w[caps-1:]
		}
		out = append(out, strings.ToLower(w))
	}
	return out
}

// unshown is what the task names that the scene has but the camera doesn't show:
// nothing with that word in its name is in the frame.
func unshown(goal string, f *sceneFacts) []string {
	var out []string
	seen := map[string]bool{}
	things := goalThings(goal)
	for _, w := range things {
		if !sameWord(f.Hidden, w) || hasWord(f.Shown, w) || (isPlace(goal, w) && slices.ContainsFunc(things, func(t string) bool { return hasWord(f.Shown, t) })) {
			continue
		}
		found := false
		for _, o := range f.Objects {
			if o.outOfFrame() && sameWord(nameWords(o.Name), w) {
				found = true
				if !seen[o.Name] {
					seen[o.Name] = true
					out = append(out, o.Name)
				}
			}
		}
		if !found && !seen[w] {
			seen[w] = true
			out = append(out, w)
		}
	}
	if len(out) > 3 {
		out = out[:3]
	}
	return out
}

// noneNamedShown says whether the task names at least two things the scene has,
// and the camera shows none of them.
func noneNamedShown(goal string, f *sceneFacts) bool {
	hidden := map[string]bool{}
	for _, w := range goalThings(goal) {
		if hasWord(f.Shown, w) {
			return false
		}
		if sameWord(f.Hidden, w) {
			hidden[w] = true
		}
	}
	return len(hidden) >= 2
}

// sameWord says whether a word in a name is w, or a plural of it either way.
func sameWord(words []string, w string) bool {
	return slices.ContainsFunc(words, func(t string) bool {
		return t == w || t == w+"s" || t+"s" == w || t == w+"es" || t+"es" == w
	})
}

// hasWord is sameWord, or a word that starts with w, as in "tabletop". That's only
// for saying something is in shot: to say it isn't takes the word itself, since a
// Bathroom_Cabinet out of shot says nothing about a bath, nor a lamppost about a lamp.
func hasWord(words []string, w string) bool {
	return sameWord(words, w) || (len(w) >= 4 && slices.ContainsFunc(words, func(t string) bool { return strings.HasPrefix(t, w) }))
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
	cam := f.Camera != nil
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
		start := "Tried and measured: with "
		if !cam {
			start = "Tried and measured: add a camera, make it scene.camera, and with its default lens and "
		}
		fmt.Fprintf(&b, "%srotation_mode = 'XYZ', location = %s, rotation_euler = (%.4f, %.4f, %.4f)%s, and nothing else aiming it (no parent, no constraint, no later change), the camera frames the objects and rays reach %d of the %d. Set those exactly, and remove whatever else aims it. ",
			start, coords(p.At), p.Rotation[0], p.Rotation[1], p.Rotation[2], clip, p.Sees, f.Total)
	}
	if f.Total > 0 && cam {
		fmt.Fprintf(&b, "%d of the %d objects are out of frame, and %.0f%% of the frame has something in it.", f.Out+f.Cut, f.Total, 100*f.Filled)
	}
	for _, o := range f.Objects {
		state := "in frame"
		switch {
		case !cam:
			state = "in the scene"
		case o.Cut:
			state = fmt.Sprintf("only %.0f%% of it is in frame", 100*o.Share)
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
			c.Summary += fmt.Sprintf(" %d of its %d objects are in the camera's frame.", f.Total-f.Out-f.Cut, f.Total)
		}
		return c
	}
	c.Outcome = "wrong_scene"
	c.Error = strings.Join(faults, " ")
	c.Summary = strings.TrimSuffix(c.Summary, ".") + ", but the scene is wrong. " + c.Error
	c.Measured, c.Faults = measured(f), len(faults)
	if f.Total > 0 {
		c.Seen = float64(f.Total-f.Out-f.Cut) / float64(f.Total)
	}
	return c
}

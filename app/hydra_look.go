package main

// A look at the result. Rules about words can only go so far: on Nov 1 a cup buried
// in its table and a camera that saw nothing both passed, because the cup was called
// a cup and its box was in frame. So once a scene passes everything else, a vision
// model on this computer looks at a small render and says what it can make out.
//
// That's an opinion, which is why it comes last and is held to something simple:
// the scene is wrong if the picture shows nothing, or if most of what the task names
// can't be seen. On 147 scenes labelled by eye, the check with qwen3.8:27b flagged 4 of
// 83 good ones, 2 of them by the look, and caught 56 of 64 bad ones, where the rules
// alone caught 40; on 40 scenes from another model, which the rule wasn't chosen on, 0
// of 13 and 15 of 27, where the rules alone caught 4. Any single thing missing would have
// flagged a quarter of the good ones. If there's no such model here, or it can't answer,
// the check says what it said before. It stays on this computer, as the check does: a
// worker on an older build would drop the picture and answer blind.

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"time"
)

const (
	lookRenderTime = 60 * time.Second
	lookAskTime    = 2 * time.Minute // long enough to load the model
	lookMaxBytes   = 5 << 20
	lookMaxThings  = 8
)

const lookSystem = "You check a rendered picture against what was asked for. Judge only what is visible in the picture. A rough, low-poly or oddly coloured shape still counts if you can tell what it is."

const lookPrompt = "The request was: %q\n\nThis picture is the render from the scene's camera. List the main physical objects the request names, the ones that should appear in the picture, and for each say whether it can be seen in the picture. Leave out anything that isn't an object in the shot: whatever lights or films the scene (sun lamps, key, fill and rim lights, the camera), the sky or world colour, render settings, constraints, weather and moods. Also say whether the picture shows nothing useful (blank): empty, a single flat colour, or too dark to make anything out."

var lookFormat = json.RawMessage(`{"type":"object","properties":{"things":{"type":"array","items":{"type":"object","properties":{"name":{"type":"string"},"visible":{"type":"boolean"}},"required":["name","visible"]}},"blank":{"type":"boolean"}},"required":["things","blank"]}`)

// lookAnswer is what the model says about the picture.
type lookAnswer struct {
	Things []struct {
		Name    string `json:"name"`
		Visible bool   `json:"visible"`
	} `json:"things"`
	Blank bool `json:"blank"`
}

// wantsLook says whether a result can be judged by its picture: a scene built from
// nothing, to be seen from its camera as it stands. One frame says little about
// something that moves, or about a task that wants part of it out of shot.
func wantsLook(goal, script string, f *sceneFacts) bool {
	return f != nil && !f.Animated && !strings.Contains(script, "app.handlers") && !strings.Contains(script, "register_class") &&
		newSceneRe.MatchString(goal) && !ownSceneRe.MatchString(goal) && !noCameraRe.MatchString(goal) && !tightGoalRe.MatchString(goal)
}

// lookModel is the model the numbers above are for. Others can see too, but a
// wrong_scene costs repairs: gemma4:12b flagged 9 of the same 77 good pictures.
func (a *App) lookModel() (ModelInfo, bool) {
	name := os.Getenv("CHIMERA_LOOK_MODEL") // for measuring another model
	if name == "" {
		name = "qwen3.8:"
	}
	return a.visionModel(name)
}

func (a *App) canLook() bool {
	_, ok := a.lookModel()
	return ok
}

// lookAt adds to a check that passed what a model can see in its render. Anything
// that goes wrong leaves the check as it was.
func (a *App) lookAt(ctx context.Context, c resultCheck, goal string, png []byte) resultCheck {
	m, ok := a.lookModel()
	if !ok {
		return c
	}
	ctx, cancel := context.WithTimeout(ctx, lookAskTime)
	defer cancel()
	ans, err := askLook(ctx, a.ollama.Client(), m.Name, goal, png)
	if err != nil {
		return c
	}
	return withLook(c, ans, m.Name, partOfIt(goal, c.Scene))
}

// partOfIt says whether this camera may be meant to show only some of what the
// task names: there's a second one, or the task says what it's on. As in
// sceneFaults, only showing none of it is wrong then.
func partOfIt(goal string, f *sceneFacts) bool {
	return (f != nil && f.Cameras > 1) || (shotGoalRe.MatchString(goal) && !wholeGoalRe.MatchString(goal))
}

func askLook(ctx context.Context, client *OllamaClient, model, goal string, png []byte) (lookAnswer, error) {
	var ans lookAnswer
	reply, err := client.ChatImage(ctx, model, lookSystem, fmt.Sprintf(lookPrompt, goal), png, lookFormat)
	if err != nil {
		return ans, err
	}
	return ans, json.Unmarshal([]byte(reply), &ans)
}

// withLook says what the answer means for the check.
func withLook(c resultCheck, ans lookAnswer, model string, part bool) resultCheck {
	var seen, unseen []string
	for _, t := range ans.Things {
		name := capRunes(strings.TrimSpace(t.Name), 60)
		switch {
		case name == "" || len(seen)+len(unseen) == lookMaxThings:
		case t.Visible:
			seen = append(seen, name)
		default:
			unseen = append(unseen, name)
		}
	}
	blank := ans.Blank && len(seen) == 0
	fine := 2*len(unseen) <= len(seen)+len(unseen)
	if part {
		fine = len(seen) > 0 || len(unseen) == 0
	}
	if !blank && fine {
		if len(seen) > 0 {
			c.Summary += fmt.Sprintf(" In a render, %s can make out %s.", model, strings.Join(seen, ", "))
		}
		return c
	}
	c.Outcome = "wrong_scene"
	if blank {
		c.Error = fmt.Sprintf("In a render from the camera, %s can't make anything out: it's empty, one flat colour or too dark.", model)
	} else {
		c.Error = fmt.Sprintf("In a render from the camera, %s can't make out %s.", model, strings.Join(unseen, ", "))
		if len(seen) > 0 {
			c.Error += " It can make out " + strings.Join(seen, ", ") + "."
		}
	}
	c.Summary = strings.TrimSuffix(c.Summary, ".") + ", but the scene is wrong. " + c.Error
	c.Look, c.Faults, c.Seen = true, 1, 0
	if n := len(seen) + len(unseen); n > 0 {
		c.Seen = float64(len(seen)) / float64(n)
	}
	if c.Scene != nil {
		c.Measured = measured(c.Scene)
	}
	return c
}

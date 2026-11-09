package main

// chimera --hydra-plan-request, --hydra-review-request and --hydra-read-reply: each
// reads one JSON object on stdin and prints, as JSON, what a long task itself sends its
// planner or reviewer, or makes of their reply, built by the functions the task uses
// (planRequest, reviewRequest, readPlan, readReview). Hydra Worker's training data
// (worker-model/datagen) gets Chimera's exact requests from them, as it gets a worker's
// from --hydra-worker-request. They need no data folder, network or window.
//
// --hydra-plan-request: goal; history, the chat before the task ([{"role", "content"}]);
// prior and critique, the round's base: the result it improves and what still needs
// work (onePass's base.Text and base.Critique); refs, what the library found, of which
// those scoring 0.3 or more are shown. It prints the messages, need_ctx, format and
// helper_fits, whether the request fits the helper (Hydra 1.0).
//
// --hydra-review-request: goal and result; it prints the same four keys.
//
// --hydra-read-reply: {"plan": reply} prints ok and the plan after cleanPlan (null when
// it can't be read); {"review": reply} prints ok, done, score and critique.

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
)

// promptRequest is a planner's or reviewer's request as data.
type promptRequest struct {
	Messages   []ChatMessage   `json:"messages"`
	NeedCtx    int             `json:"need_ctx"`
	Format     json.RawMessage `json:"format"`
	HelperFits bool            `json:"helper_fits"`
}

// promptRequestOf keeps what a model sees of a request, and whether it goes to the
// helper: a request that fits it prefers it.
func promptRequestOf(req submitReq) promptRequest {
	return promptRequest{Messages: req.Messages, NeedCtx: req.NeedCtx, Format: req.Format, HelperFits: req.PreferModel != ""}
}

type planRequestInput struct {
	Goal     string        `json:"goal"`
	History  []ChatMessage `json:"history"`
	Prior    string        `json:"prior"`
	Critique string        `json:"critique"`
	Refs     []LibEntry    `json:"refs"`
}

type reviewRequestInput struct {
	Goal   string `json:"goal"`
	Result string `json:"result"`
}

type readReplyInput struct {
	Plan   *string `json:"plan"`
	Review *string `json:"review"`
}

// plannedStep and plannedPlan are a cleaned plan as the planner meant it: what a run
// adds to a step (its status, model, output) is left out.
type plannedStep struct {
	ID           string   `json:"id"`
	Title        string   `json:"title"`
	Kind         string   `json:"kind"`
	Instructions string   `json:"instructions"`
	DependsOn    []string `json:"depends_on"`
}

type plannedPlan struct {
	Title   string        `json:"title"`
	Kind    string        `json:"kind"`
	Summary string        `json:"summary"`
	Steps   []plannedStep `json:"steps"`
}

func plannedOf(p hydraPlan) plannedPlan {
	out := plannedPlan{Title: p.Title, Kind: p.Kind, Summary: p.Summary, Steps: []plannedStep{}}
	for _, s := range p.Steps {
		out.Steps = append(out.Steps, plannedStep{ID: s.ID, Title: s.Title, Kind: s.Kind, Instructions: s.Instructions, DependsOn: orEmpty(s.DependsOn)})
	}
	return out
}

type planReply struct {
	OK   bool         `json:"ok"`
	Plan *plannedPlan `json:"plan"`
}

type reviewReply struct {
	OK       bool   `json:"ok"`
	Done     bool   `json:"done"`
	Score    int    `json:"score"`
	Critique string `json:"critique"`
}

// datagenMode reads a mode's input and prints what build gives for it. A failure is
// one "<name>: ..." line on stderr and exit 2.
func datagenMode[In any](name string, in io.Reader, out io.Writer, build func(In) (any, error)) int {
	fail := func(err error) int {
		fmt.Fprintf(os.Stderr, "%s: %v\n", name, err)
		return 2
	}
	var r In
	if err := json.NewDecoder(in).Decode(&r); err != nil {
		return fail(err)
	}
	result, err := build(r)
	if err != nil {
		return fail(err)
	}
	enc := json.NewEncoder(out)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(result); err != nil {
		return fail(err)
	}
	return 0
}

// runPlanRequest is --hydra-plan-request: a round's planner request, as onePass
// builds it from the round's base.
func runPlanRequest(in io.Reader, out io.Writer) int {
	return datagenMode("plan request", in, out, func(r planRequestInput) (any, error) {
		req := taskReq{Goal: r.Goal, history: r.History}
		return promptRequestOf(planRequest(req, 1, planPrior(r.Prior, r.Critique), r.Critique, usefulRefs(r.Refs))), nil
	})
}

// runReviewRequest is --hydra-review-request: the looping reviewer's request.
func runReviewRequest(in io.Reader, out io.Writer) int {
	return datagenMode("review request", in, out, func(r reviewRequestInput) (any, error) {
		return promptRequestOf(reviewRequest(taskReq{Goal: r.Goal}, r.Result)), nil
	})
}

// runReadReply is --hydra-read-reply: a planner's reply read as askPlanner reads it
// (then cleaned, as onePass does), or a reviewer's as askReviewer does.
func runReadReply(in io.Reader, out io.Writer) int {
	return datagenMode("read reply", in, out, func(r readReplyInput) (any, error) {
		switch {
		case (r.Plan == nil) == (r.Review == nil):
			return nil, fmt.Errorf(`give "plan" or "review", one of them`)
		case r.Plan != nil:
			plan, ok := readPlan(*r.Plan)
			if !ok {
				return planReply{}, nil
			}
			cleaned := plannedOf(cleanPlan(plan))
			return planReply{OK: true, Plan: &cleaned}, nil
		}
		v, ok := readReview(*r.Review)
		return reviewReply{OK: ok, Done: v.Done, Score: v.Score, Critique: v.Critique}, nil
	})
}

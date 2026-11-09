package main

// chimera --hydra-worker-request: reads one JSON object on stdin and prints the
// request a worker would get under the sub-agent contract, as JSON. It's how training
// data gets Chimera's exact words, and how worker-model/tools/check_contract_parity.py
// compares them with the prototype. It needs no data folder, network or window.
//
// The input: plan, as the planner wrote it (it's cleaned here); index, the step from 0;
// outputs, each step's reply by plan id: a string, null for a failed step, or
// {"output": ..., "status": ...}, and a step left out counts as failed; goal; refs;
// names, the names sheet; names_gate, true to give the sheet only to a step namesBlock
// would give it to (else it goes to any step); prev_result and critique, from round 2
// on; crash and piece, for a repair; room, the reply room.

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
)

type workerRequestInput struct {
	Plan       hydraPlan                  `json:"plan"`
	Index      int                        `json:"index"`
	Outputs    map[string]json.RawMessage `json:"outputs"`
	Goal       string                     `json:"goal"`
	Refs       []LibEntry                 `json:"refs"`
	Names      string                     `json:"names"`
	NamesGate  bool                       `json:"names_gate"`
	PrevResult *string                    `json:"prev_result"`
	Critique   string                     `json:"critique"`
	Piece      string                     `json:"piece"`
	Crash      *workerCrash               `json:"crash"`
	Room       *int                       `json:"room"`
}

// stepOutcome reads one entry of outputs. With no status an object counts as done if
// it has an output.
func stepOutcome(raw json.RawMessage) (output, status string, err error) {
	if len(raw) == 0 {
		return "", "failed", nil
	}
	var s *string
	if json.Unmarshal(raw, &s) == nil {
		if s == nil {
			return "", "failed", nil
		}
		return *s, "done", nil
	}
	var o struct {
		Output *string `json:"output"`
		Status string  `json:"status"`
	}
	if err := json.Unmarshal(raw, &o); err != nil {
		return "", "", err
	}
	status = o.Status
	if status == "" {
		status = "done"
		if o.Output == nil {
			status = "failed"
		}
	}
	if o.Output != nil {
		output = *o.Output
	}
	return output, status, nil
}

func runWorkerRequest(in io.Reader, out io.Writer) int {
	fail := func(format string, args ...any) int {
		fmt.Fprintf(os.Stderr, "worker request: "+format+"\n", args...)
		return 2
	}
	var r workerRequestInput
	if err := json.NewDecoder(in).Decode(&r); err != nil {
		return fail("%v", err)
	}
	plan := cleanPlan(r.Plan)
	if r.Index < 0 || r.Index >= len(plan.Steps) {
		return fail("no step %d: the plan has %d", r.Index, len(plan.Steps))
	}
	for i := range plan.Steps {
		s := &plan.Steps[i]
		var err error
		if s.Output, s.Status, err = stepOutcome(r.Outputs[s.ID]); err != nil {
			return fail("the output of %s: %v", s.ID, err)
		}
	}
	ask := workerAsk{Goal: r.Goal, Refs: r.Refs, Names: r.Names, PrevResult: r.PrevResult, Critique: r.Critique, Room: contractRoom}
	if r.NamesGate && !namesApply(plan.Steps[r.Index].Kind, plan, r.Goal) {
		ask.Names = ""
	}
	if r.Room != nil {
		ask.Room = *r.Room
	}
	var req workerRequest
	if r.Crash != nil {
		req = contractRepairRequest(plan, r.Index, ask, r.Piece, *r.Crash)
	} else {
		req = contractRequest(plan, r.Index, ask)
	}
	enc := json.NewEncoder(out)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(req); err != nil {
		return fail("%v", err)
	}
	return 0
}

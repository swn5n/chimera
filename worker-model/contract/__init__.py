"""The sub-agent contract prototype (docs/hydra-worker-plan.md, "The sub-agent contract"), for measuring only.

texts.py holds every frozen text; prompt.py builds the contract's worker request, today.py today's;
validate.py checks a piece, join.py joins pieces, linemap.py maps a check's line back to a step.
The Go version (app/hydra_assemble.go and prompts.go) comes after the user approves the contract.
"""

# qwen3:4b-instruct-2507-q4_K_M, contract prompt, on the worker eval (w1.0)

2026-10-29T23:04:35-05:00 · Ollama 0.40.1 · digest `0edcdef34593` · samples 1 (prose 1) · unseeded · Blender 5.2.2, 5.0.1

EVAL ONLY: model replies to eval cases; never training data.

Differences from what Chimera 0.7.0 sends: a reply is cut after 16384 tokens (runaway guard; Chimera sends no num_predict and has no cap).

| – | n | contract kept | strict 5.2.2 | strict 5.0.1 | both | crash 5.2.2 | assertions | API errors | repaired | expect | cut off | tokens | tok/s | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 3 | 33% | 0% | 0% | 0% | 67% | 0% | 6.0 | – | – | 0% | 814 | 139.5 | 6.18 |
| w2 | 3 | 33% | 0% | 0% | 0% | 67% | 0% | 6.0 | – | – | 0% | 814 | 139.5 | 6.18 |
| blender | 3 | 33% | 0% | 0% | 0% | 67% | 0% | 6.0 | – | – | 0% | 814 | 139.5 | 6.18 |

strict: Chimera's check passed and its output tail has no Traceback or Error line (tools/blender_check.py). crash: the check's outcome was failed (a definite crash). assertions: the eval's scene assertions in 5.2.2. API errors: tools/rna_lint.py errors per reply. expect: every word and pattern check the case has.

## Samples

| case | sample | mode | contract | run | 5.2.2 | 5.0.1 | assert | lint | tokens | s | first problem |
|---|---|---|---|---|---|---|---|---|---|---|---|
| w2-01 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 814 | 6.18 | 5.2.2: line 59: SyntaxError: unterminated string literal (detected at line 59) |
| w2-04 | 0 | blender | ok | joined | failed | failed | FAIL | 12 | 1640 | 12.141 | 5.2.2: line 25: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-08 | 0 | blender | broken | alone | unsure | unsure | FAIL | 5 | 380 | 3.049 | 5.2.2: line 17: TypeError: bpy_struct: item.attr = val: enum "EEVEE" not found in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH', |

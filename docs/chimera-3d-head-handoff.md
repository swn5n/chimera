# Handoff: build a 3D-mesh "Head" for Chimera from the Hunyuan3D already on this laptop

Written Oct 24, 2026. For the Claude instance on the laptop (the machine that runs the Perspective shadow Head in Blender). You have no access to the conversation this came from, so everything you need is here, and anything I could not confirm is marked **unverified**.

## Goal

Make this laptop's Hunyuan3D usable by the Chimera network as a **Head**: a job that arrives as a picture and comes back as a 3D mesh (GLB preferred, OBJ acceptable), run on this laptop's own install, with no ComfyUI.

The Perspective shadow Head already works on this machine by running Hunyuan3D and Blender locally. Build the mesh Head the same way, or wrap the same model in a small local server.

## What Chimera and Heads are (30-second version)

- Chimera is a small Go app (one binary, web UI) that pools several computers so work goes to whichever one has the right model or tool. Think SheepIt for AI agents.
- A **Head** is a tool-based worker. Instead of asking an LLM, Chimera hands a job to a user's deterministic tool or local model server when that does the job better (shadows, meshes, conversions). Internally the code still calls these "plugins" (`plugin.json`, `/plugin` API paths); the UI and docs say "Heads".
- A Head is a folder containing a manifest (`plugin.json`) plus a runner. Chimera runs it in a sandbox on the worker computer. The asker pays credits (2 per minute of worker time); the Head's owner earns a bonus when someone else's job runs on it, and a bonus when someone rates the result 4-5 stars.
- Chimera **0.6.0** is required on every computer (Heads protocol fields). Check Settings shows 0.6.0.

## What the Chimera side already does for you (verified in tests, Oct 24)

- The asker keeps returned files by extension-aware MIME sniffing, so a `.glb` is no longer dropped as `application/octet-stream`.
- A Head that takes a picture is considered when a message has an attached picture. A Head that needs no file (empty `accepts`, or `optional_input: true`) can also be chosen from words alone through a "should a tool handle this?" check.
- Manifest field `"network": "localhost"` lets a Head reach servers on the same machine while the sandbox otherwise blocks the network (macOS: `(deny network*)` then `(allow network* (remote ip "localhost:*"))`).
- The runner works under the macOS sandbox (`sandbox-exec`). The Perspective Head already runs under it on this machine, so the same sandbox constraints apply to you (see "Sandbox" below).

## The contract: where the truth lives

I do not have the exact manifest schema in front of me, so **do not copy field names from this file**. The authoritative sources, in order:

1. `heads/TEMPLATE/` in the Chimera folder (contract written in comments), plus `heads/README.md`.
2. `docs/CHIMERA-PLUGINS-HANDOFF-0.5.0.md`, the handoff you used for Perspective.
3. The working Perspective Head on this machine. Mirror its structure.
4. `heads/hunyuan3d-mesh/`, a reference mesh Head that speaks Hunyuan3D-2's `api_server.py` API (`/healthcheck`, async `/send` + `/status/{uid}`, fallback `/generate`; env `HUNYUAN3D_URL`, default `:8080`). It ran end to end only against a **fake** server, never real Hunyuan3D, so expect small API fixes.

If the Chimera folder is not on this machine, ask the user to send `heads/TEMPLATE/`, `heads/hunyuan3d-mesh/` and the 0.5.0 handoff doc.

## Step 0: inspect this machine first (report answers before building)

1. How does the shadow script load Hunyuan3D? Which Python, which package (`hy3dgen`, a Blender add-on, the Mac/MPS community port, something else), and where do the weights live?
2. Hunyuan3D **2.0 or 2.1**? Is the texture/paint step used, or shape only?
3. Can the model be imported and run from a normal Python process outside Blender, or only from Blender's bundled Python?
4. Cold-start time (model load) and per-mesh generation time, measured.
5. Peak memory during a run, and whether Blender holds the model resident while open.
6. Where does the shadow script write its output, and in what format?

## Step 1: pick an option

**Option A: headless Blender per job (default recommendation).** Fewest moving parts, and it matches how Perspective works.
- `run` calls `blender -b --python hunyuan_job.py -- <input image> <output dir>` (or the equivalent form Perspective uses).
- `hunyuan_job.py` loads the model exactly as the shadow script does, generates the mesh, and writes `mesh.glb` into the output directory the runner expects.
- Cost: model loads on every job (tens of seconds to minutes). Fine for batch and long tasks; poor for quick ones.
- No `network` field needed unless the script downloads anything (it should not; weights must already be on disk).

**Option B: small local server, then use the reference Head unchanged.** Pick this only if Step 0 shows the model runs in a standalone Python environment.
- A short script loads Hunyuan3D once and serves the same endpoints the `hunyuan3d-mesh` reference Head expects (or use the upstream `api_server.py` if this install supports it).
- Set `"network": "localhost"` in the manifest and `HUNYUAN3D_URL` to the server's address.
- Faster per job, but weights stay resident. Don't also keep Blender holding a second copy if memory is tight.
- The user must start the server before the Head can work. The Head's health check should fail clearly with a message such as "Hunyuan3D server not running at <url>".

If Option A's cold start turns out unusable, A can later become B without changing the Head's public behaviour.

## Head behaviour spec (either option)

- **Input:** one picture. Words-only is not meaningful, because Hunyuan3D is image-to-3D; chaining text to image to 3D is a later feature.
- **Output:** a mesh file (`.glb` preferred) returned as a result file, plus a short text note: model/version used, face count if cheap to get, generation time.
- **Description string matters.** Chimera's routing and its "should a tool handle this?" gate read the manifest description. Say plainly what it does ("Turns one picture of an object into a 3D mesh (GLB). Not for scenes, shadows, or editing existing meshes.") so it doesn't hijack unrelated chats.
- **Failure behaviour:** exit non-zero with a one-line human-readable reason (missing weights, out of memory, no picture, server down). Never hang. Check the timeout the runner enforces in TEMPLATE and stay within it, or document the limit.
- **Offline:** no network access, no downloads at run time. Weights and code must already be local.
- **Idempotent and clean:** write only inside the output directory the runner gives you.

## Sandbox (macOS)

The runner wraps Heads in `sandbox-exec`. Whatever Perspective needed to run Blender will be a good starting point. A mesh Head additionally needs:
- read access to wherever the Hunyuan weights, code and Python environment live;
- write access to the job's output directory and probably a scratch/temp area (some model code writes to `~/.cache/huggingface` or `/tmp`: find out, and prefer pointing caches at the job directory via env vars instead of widening the sandbox);
- on Apple Silicon, MPS/Metal access, which normally works without extra rules, but verify it inside the sandbox rather than outside it.

Test through the **real runner** (`--plugin-test` with the app binary), not just by running the script directly. Direct runs hide sandbox failures.

## Acceptance tests

1. Run the Head through `--plugin-test` with a sample object picture: it returns a valid GLB that opens in Blender (import it and check it has geometry).
2. Run it again with a bad input (not a picture): clean error, no hang.
3. Run with the model weights temporarily unreachable (or the server stopped, for Option B): clear error message.
4. From a second Chimera computer on the same network, send a picture with the Head available on this laptop. The Head should be chosen, the mesh should come back, and the asker should be charged credits. This has never been tried across two physical computers, so report anything odd.
5. Record: cold-start time, warm time, memory peak.

## What to send back to the user

- Which option you chose and why (include the Step 0 answers).
- The Head folder (manifest + runner + any job script), ready to drop into the app's Heads location.
- Test results for the five tests above, including real timings.
- Any change you needed to make to Chimera itself. Prefer none; if the manifest contract is missing something (for example an output-type declaration, a longer timeout, or a way to declare required read paths), describe it precisely rather than patching around it.

## Caveats and things to avoid

- **Licence:** Hunyuan3D 2.1's community licence excludes use in the EU, UK and South Korea. Note which version is installed and mention the licence in the Head's README.
- Don't change the app's built-in behaviour or version number. Heads are folders added alongside it.
- Don't invent manifest fields. If TEMPLATE doesn't define it, it doesn't exist.
- Head identity is its id only (no hash pinning yet), so pick a distinctive id (for example `hunyuan3d-mesh-laptop`) so it doesn't collide with the reference Head of the same purpose on the Studio.
- Privacy is deliberately not a goal for now: pictures sent to the pool can be read by the host and anyone let into the pool. Don't spend effort on it.
- The Studio (M3 Ultra, 96 GB) is also planned to run Hunyuan3D 2.1 with far more memory. This laptop's Head is worth building as a second 3D node and as a proof of the pattern, but jobs may prefer the Studio.

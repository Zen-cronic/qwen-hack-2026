# Verification log

What has actually been run against the live API, and what it proved. Sections 1–3b are the
day-1 verify-or-abort gate (Jul 6–7); section 4 is the first real end-to-end run (Jul 15).

Evidence for the PLAN.md verify-or-abort gate. Decision: **PASS — no abort, ClipCrew proceeds.**

## 1. Chat API smoke test — PASS

`scripts/verify_quota.py` against the sanctioned OpenAI-compatible endpoint:

- Endpoint: `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`, model `qwen-plus`
- Minimal completion succeeded; usage reporting works (prompt=15, completion=1, total=16 tokens)

## 2. Video-gen quota — PASS (abort rule not triggered)

Console snapshot Jul 6; all quotas unused, free tier, expire **2026-10-05** (well past the Jul 9 deadline). Wan 2.1/2.2 clips are fixed at 5 s, so seconds ÷ 5 = generation cycles:

| Model | Free quota | Cycles | Planned role |
|---|---|---|---|
| wan2.1-t2v-turbo | 200 s | 40 | draft/iteration workhorse |
| wan2.2-t2v-plus | 50 s | 10 | final-quality renders only |
| wan2.1-kf2v-plus | 200 s | 40 | keyframe→video fallback |
| wan2.2-i2v-flash | 50 s | 10 | image→video fallback |
| wan2.2-animate-mix / -move | 50 s each | 10 each | unused |
| qwen-image / -edit / -edit-plus | 100 images each | — | storyboard frames |
| wan2.1-t2i-plus | 200 images | — | storyboard frames |

Abort threshold was ~12 cycles; turbo alone covers 40. Total video budget: 600 s.

## 3. Wan endpoint + task lifecycle — VERIFIED LIVE, zero quota spent

Method: POSTed an intentionally invalid request (empty `input`) to the legacy host with the
real key. Billing happens at generation, not admission, so a validation failure exercises
auth + routing + queueing for free.

- `POST https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis`
  with `X-DashScope-Async: enable` → **HTTP 200**, `task_id`, `task_status: PENDING`
- Poll `GET /api/v1/tasks/{task_id}` → `FAILED` ~100 ms later with
  `InvalidParameter: "prompt must contain words"` — no generation, no spend
- Confirms the classic `dashscope-intl.aliyuncs.com` host serves Wan video with the same
  `QWEN_API_KEY` as chat; the new workspace-scoped `maas.aliyuncs.com` URLs are not needed

### Findings that shape the retry policy (Jul 7)

1. **HTTP 200 ≠ valid request.** Validation is asynchronous: bad requests are accepted,
   then fail on the first poll with `output.code`/`output.message`. Retries must branch on
   polled task status, never on the POST's HTTP status.
2. **Every wan2.1/2.2 call costs exactly 5 s of quota** — duration is fixed, no parameter.
3. **`video_url` expires 24 h after completion.** Download the MP4 immediately; persist the
   file, not the URL.
4. Cancel (`POST /api/v1/tasks/{task_id}/cancel`) only works while `PENDING`.

Machine-facing constants, request/response shapes, and the client live in `server/wan.py`.

## 3b. Hour-zero model probes (Jul 7) — Tier-B GO, Tier-0 confirmed

Run via `scripts/smoke_vl.py` and `scripts/probe_models.py`.

**Tier-B (qwen-vl semantic verdicts) — GO.** `smoke_vl.py` generates a bright and a
dark solid-gray PNG in memory and asks the VLM to classify each (a model that can't
see pixels can't beat a coin flip across the pair). `qwen-vl-plus` via the
OpenAI-compatible `image_url` shape classified both correctly on the first attempt
(bright→bright, dark→dark). **Decision: build real VLM verdicts in `tier_b.py`; no
human-stub fallback needed.** Pins (also the code defaults): `VL_MODEL=qwen-vl-plus`,
`VL_SHAPE=openai`. Cost: ~2–4k tokens, zero video quota.

**Tier-0 (t2i stills) — endpoint + generation confirmed.** `probe_models.py`:
- Zero-cost reachability: `POST /api/v1/services/aigc/text2image/image-synthesis`
  with an empty input returns **HTTP 400 `InvalidParameter: input.prompt should not
  be null`** — a field-level rejection that confirms endpoint + auth + model routing
  for `wan2.1-t2i-plus`. NB: the image endpoint validates **synchronously** (400),
  unlike the video endpoint which validates **asynchronously** (200 → poll → FAILED).
- `--real` generated one still (1 image credit, budgeted): task **SUCCEEDED**, image
  at `output.results[0].url`. That URL is a signed OSS link with an `Expires` param
  (~24h) — **download immediately, persist the file not the URL** (same as video).

## 3c. Edit + keyframe backends (Jul 19) — targeted repair is reachable

Section 2 banked free quota for three capabilities `server/` had never called. They are
the backend for a **targeted repair**: extract the frame a check indicted, re-render the
shot anchored to it, instead of blind-re-prompting a whole 5 s clip. Probed with
`scripts/probe_edit_models.py` using the section-3 trick — an empty `input` fails
server-side validation, so routing is proven without generating anything.

| Model | Endpoint (on `dashscope-intl.aliyuncs.com`) | Verdict |
|---|---|---|
| `qwen-image-edit`, `-plus` | `/api/v1/services/aigc/multimodal-generation/generation` (**sync**) | **round-trip SUCCEEDED** |
| `wan2.1-kf2v-plus` | `/api/v1/services/aigc/image2video/video-synthesis` | **round-trip SUCCEEDED** |
| `wan2.2-i2v-flash` | `/api/v1/services/aigc/video-generation/video-synthesis` | reachable |
| `wanx2.1-imageedit` | — | `Model not exist` — China-mainland only |

Findings that shape the client:

1. **Validation messages are free schema.** The rejections name the missing fields:
   `img_url must be set for image to video method` (i2v) and `video frames must be set`
   (kf2v). The probe cost nothing and returned the request shape.
2. **The video endpoints accept a base64 `data:` URI in place of a URL.** `i2v-flash`
   read a 1×1 data URI and rejected it with `Image height or width is too small than
   240` — a *decode* error, so the image was read. This is the finding the whole feature
   depends on: frames extracted on a `127.0.0.1` box have no public URL, and no OSS
   upload step is needed.
3. **`qwen-image-edit` takes a chat-shaped body on a SYNCHRONOUS endpoint** — not the
   image-synthesis shape the other Wan models use. The first probe tested
   `image2image/image-synthesis` with `base_image_url` / `image_url` / `images[]` under
   `X-DashScope-Async`, got `url error, please check url`, and wrongly concluded data
   URIs were unsupported. Corrected: **no async header** (sending one to the right path
   returns `403 AccessDenied: current user api does not support asynchronous calls` —
   which the first pass misread as an auth failure), and the body is
   `{"model": ..., "input": {"messages": [{"role": "user", "content": [{"image": <data
   URI>}, {"text": <instruction>}]}]}}` → `HTTP 200`, result under `output.choices`.
   **Base64 data URIs are accepted here too**, so neither half of the loop needs a
   public URL. Verified live at a cost of 1 of 100 free image edits.
4. **Editing is instruction-only — no mask, no bounding box.** `qwen-image-edit` exposes
   no region parameter, and the one DashScope model that does (`wanx2.1-imageedit`, with
   `function: description_edit_with_mask`) is China-Beijing-only, which is exactly why it
   answered `Model not exist` here. Region-locked repair in the Ideogram sense is not
   available on the international endpoint; instruction-scoped repair is.
5. **`wan2.1-kf2v-plus` confirmed end to end, at a cost of 5 s** (1 of 40 cycles): fields
   `input.first_frame_url` + `input.last_frame_url`, async submit, `output.video_url` on
   completion. Unlike i2v it enforces no 240 px minimum, so the guard intended to keep
   the probe free did not hold — it accepted and generated. Cancel is `PENDING`-only
   (section 3, finding 4) and the task was already `RUNNING`.

Net: local frame → data URI → (optional `qwen-image-edit`) → `i2v`/`kf2v` → `video_url`
is a verified path end to end, on quota entirely separate from the t2v draft/final
reserve. `server/patch.py` implements the video half; the edit half is wired but the
default repair path does not use it, because an instruction-only edit of a whole frame
is a blunter tool than a corrected prompt on a good anchor.

### 3c-i. First live patch (Jul 19) — the premium render, recovered

Run `3e1f628d4acf`, shot 0, contract `camera_motion: static`. The recorded history:
take 0 (`wan2.1-t2v-turbo`) passed at `|v|=0.30`; take 1 (`wan2.2-t2v-plus`, same prompt)
came back drifting left at `|v|=0.92` and FAILED, so `_promote` certified the draft and
the premium render went unused. That is section 4's "verification catches what promotion
changes", and until now the story ended there.

Patched via `patch_shot(..., model="wan2.2-i2v-flash")`:

| | before (take 1, premium) | after (patch) |
|---|---|---|
| `camera_motion` | **FAIL** — camera left, `|v|=0.92` | **PASS** — static, `|v|=0.09` |
| `flicker_below` | pass, std 2.59 | pass, std 0.29 |
| `brightness_range` | pass, luma 113.0 | pass, luma 109.4 |
| duration / scene_cuts | pass | pass |

Tier-A placed the drift at **0.4s–3.6s** (24 of 38 sampled frames, settling in the last
~1.4s), so the anchor was **0.2s**. Cost: **5 video-seconds** (1 of 10 `i2v-flash` cycles)
plus one qwen-plus repair call. Shot 0 is now certified with the patched clip.

Two things this establishes beyond the endpoint contract. `wan2.2-i2v-flash` is confirmed
on its SUCCESS path, not just its validation path. And the stored results of that run
predate localization entirely — the patch works because `patch_shot` re-measures the
source clip rather than trusting what was recorded beside it, which is free (deterministic
CV on a file already on disk) and is what lets a repair act on a run older than the feature.

## 3d. Narration — the episode gets a voice (Jul 19)

Wan's t2v/i2v models return silent clips, so a certified episode was silent too.
`GET {QWEN_BASE_URL}/models` with this key lists **149 models**, including the
`qwen3-tts-*` family — the video models are absent from that list because they live on
the async task API, not the OpenAI-compatible route.

**Contract (verified live):**

```
POST {DASHSCOPE}/api/v1/services/aigc/multimodal-generation/generation
  headers: Authorization, Content-Type   (NO X-DashScope-Async — this route is sync)
  body:    {"model": "qwen3-tts-flash", "input": {"text": "...", "voice": "Cherry"}}
  -> 200 {"output": {"audio": {"url": "...wav", "expires_at": ..., "id": ...}}}
```

- `input.voice` is **required** — omitting it is `400 InvalidParameter: The voice
  property is required.` The `input.messages` shape used by `qwen-image-edit` is rejected
  here; TTS takes flat `input.text`.
- Measured: a 107-character line synthesized in **2.4 s**.
- The URL is a signed OSS link with `expires_at` — downloaded immediately, like video.

**The gotcha worth writing down.** The returned WAV is *streamed*, so its header declares
an effectively infinite length: a ~7 s clip reports **44,739 s** to `wave` and to ffprobe.
Anything that trusts that header to size the output produces a twelve-hour episode. The
assembler is safe because `-shortest` bounds each segment by its VIDEO, and the paired
`apad` stops a *short* line from doing the reverse — truncating the video down to the
narration. Verified: a 5.00 s clip muxed with that 44,739 s-declaring wav yields exactly
5.00 s.

Because audio is truncated at the clip length, an over-long line is not harmless extra —
it is a sentence cut off mid-word. `narration_for` budgets ~2.6 words/second against the
shot's own duration.

Narration is cached by `sha1(model|voice|text)`, so a judge-mode replay re-narrates for
free, and a failed voice call degrades that shot to silence rather than failing a
certified run.

## 3e. What an anchor frame carries — and what it doesn't (Jul 19)

Frame-anchoring was extended from targeted repair (3c) to the *retake* and *promotion* paths,
to stop draft/repair/final from being three independent rolls that drift apart. Running it on
real Wan output falsified the extension in two specific places, and both are now encoded in
`server/pipeline.py` rather than left as prompt advice. The governing rule the measurements
produced: **anchor to preserve, re-roll to change.**

**i2v cannot repair a whole-clip defect.** Shot 1 asserts `camera_motion: right`; its first
draft came back static — `|v| = 0.005` against `STATIC_FLOW_THRESH = 0.4` — with Tier-A
localising the failure to `fail_window_s [0.0, 5.33]`, i.e. the entire clip. Anchoring the
retake at the only frame before the window (frame 0) pinned the very staticness the retake
existed to fix: the anchored retake measured `|v| = 0.112`, still a FAIL. A fresh `t2v` roll
on the same repaired prompt reached `|v| = 0.745 'right'` and passed.
→ `Pipeline._anchor_for_retake` returns `None` when the failure window opens at `t = 0`, so a
whole-clip defect re-rolls instead of anchoring. Stated as a general rule about failure
windows, not a special case for `camera_motion`.

The same rule reached the **manual** path later, and only because the graph's re-render
button was finally looked at (Jul 20). `patch.py` had its own `anchor_second`, which clamps
to `0.0` and anchored there quite happily — so the button offered, and the endpoint
performed, exactly the move measured above as useless. Worth recording as a process finding
rather than a bug: the automatic and manual paths computed the anchor independently, so
fixing one left the other confidently wrong, and no test caught it because both surfaces
agreed with themselves. `patch_shot` now re-rolls when nothing precedes the defect and
returns `anchor_s: None` to say so, and the button label drops the second it can no longer
promise.

**i2v promotion inverts motion.** An anchor frame carries composition, lighting and wardrobe;
it carries no motion vector. Promoting the approved `|v| = 0.745 'right'` take by anchoring at
`0.1 s` produced a final that panned the other way — `|v| = 6.15 'left'` — and failed the
re-verify. The shot still certified, because `_promote` already falls back to the passing
draft when a final regresses on Tier-A; the fallback absorbed the defect silently, which is
precisely why the ledger, not the outcome, is the thing worth reading.
→ `Pipeline.asserts_camera_motion` skips promotion entirely for a shot with a motion contract.
The clip that satisfied the contract is the clip that ships — the most consistent final
available, and one generation cheaper.

Net: shots **without** a motion contract get a frame-anchored `wan2.2-i2v-flash` final that is
visually continuous with the take the human approved; shots **with** one ship the approved take
itself. Both findings cost one clip each to discover (10 s of the 600 s budget) and are
reproducible from the run's `state.json`, which stores every take's `fail_window_s` and
measured flow magnitude.

## 3f. The voice roster — probed, because it cannot be listed (Jul 20)

Narration shipped with one hardcoded voice, so every character sounded the same. Giving a
cast distinct voices needs to know which voices this account may actually use, and the API
will not say: an unknown voice returns

```
400 InvalidParameter: Invalid voice specified, the requested voice does not exist
                      or is not licensed for use—please select a supported voice.
```

That message enumerates nothing, and *"not licensed for use"* means availability is an
account property, not a model property — so the roster has to be probed, not read. Probing
20 candidate names against `qwen3-tts-flash` on this key returned **200 with an audio URL
for all 20**:

`Cherry` · `Ethan` · `Nofish` · `Jennifer` · `Ryan` · `Katerina` · `Elias` · `Jada` ·
`Dylan` · `Sunny` · `Li` · `Marcus` · `Roy` · `Peter` · `Rocky` · `Kiki` · `Eric` ·
`Serena` · `Chelsie` · `Aiden`

**The design follows the same rule as the assertion DSL: the model names a speaker, the
server casts the voice.** `server/tts.py` pins a closed `CAST_VOICES` roster drawn from the
probed list, and the script agent emits only a `speaker` — a character name. It cannot emit
an invalid voice because it never emits a voice at all, which is the identical principle
that keeps a malformed assertion (`parse_assertions`) and a malformed graph
(`build_pipeline_graph` takes run parameters, not topology) out of the system. Worth stating
because the failure it prevents is quiet: an unlicensed voice degrades that shot to silence
rather than failing the run, so a certified episode would just have a hole in it.

Casting is by **order of first appearance**, fixed once at scripting into `ProjectState.cast`,
not by hashing the character's name. A hash can collide and give two characters one voice
with nothing to signal it; an ordinal is equally deterministic — the shot list is fixed
before narration runs — so a re-run casts identically and every narration cache key still
hits. That last part is load-bearing: the cache key is `sha1(model|voice|text)`, so unstable
casting would silently re-synthesize every line on a replay that should have been free.

## 4. First real end-to-end run (Jul 15) — what the synthetic clips hid

Sections 1–3b verify the API in isolation, and spend almost nothing doing it — which is
what made them cheap enough to run on day 1, and also the limit of what they can prove.
Every *end-to-end* test until this point ran on synthetic clips (`DAILIES_DEMO=1`, a fake
`WanClient` returning generated MP4s). That exercises the pipeline's control flow and never
once exercises the API's contract. A fake client validates nothing, so it cannot reject a
request the real service would reject.

`DAILIES_FIXTURES=1` closes that gap. It is the real pipeline — real `WanClient`, real
Tier-A, real Tier-B, real assemble — with only the two non-deterministic *text* stages
(the script agent and the repair agent) pinned to fixed prompts. Pinning them is what makes
the run free to repeat: prompts are cache keys, so identical prompts replay identical clips
from the content-addressed cache at zero video quota. `scripts/warm_fixtures.py` runs it
cold then warm and prints the ledger for both.

### 4.1 Result

| | billed video-seconds | wall clock | shots certified |
|---|---|---|---|
| Cold (2 uncached finals) | 10 s (~$3.00 est.) | 207 s | 3/3 |
| Warm (everything cached) | **0 s ($0.00)** | **6 s** | **3/3** |

The cold column bills only what was missing from the cache at that moment; from a genuinely
empty cache the pack costs 7 clips × 5 s = **35 s**. The warm column is the load-bearing one:
**re-certifying real 1080p video costs zero video quota**. That is the mechanism judge mode
relies on, measured rather than asserted.

### 4.2 The four bugs it found

None of these were visible to a green test suite. All four shared one shape: a fallback that
made failure look like success.

| Bug | Why a green test suite missed it |
|---|---|
| `wan2.2-t2v-plus` rejects `1280*720` — **every premium promote ever made had failed** with `InvalidParameter` in ~16 s | `_promote` treats a failed promote as "keep the passing draft", so a rejected final and a healthy skip produced identical state. The cost-tiered cascade — the wedge — had never run its premium tier. |
| The budget governor asked the cache about `1280*720` for **every** model | Size is part of the cache key, so it looked up the wrong key for finals and called every cached final "fresh". Under `JUDGE_MODE` (`fresh_final_cap=0`) that would have refused free replays of finals *during judging*. |
| The ledger wrote an empty `note` for both a no-op call and a hard failure | Which is precisely how the first two hid. The audit trail didn't audit. `_spend_note` now records the failure code. |
| `state.json` was write-only | Snapshots were atomically written and never read back. A push to main redeploys the box, so every release silently discarded every run a viewer had made — while the deployment diagram in [architecture.md](architecture.md) promised "cache + state persist across restarts". The cache did; state didn't. |

Fixed in `2917b09`; each fix has a regression test (`tests/test_wan.py`, `tests/test_fixtures.py`),
verified by reverting the fix and confirming the test fails.

**The finding under the findings:** the project's own thesis is that generated video ships
unverified because nobody runs the claim against the artifact. The premium tier had been
dead for the project's entire life, in a repo whose pitch is a conformance gate. Mocks test
the code you wrote; fixtures test the assumption you made. This bug lived in the gap.

### 4.3 Reject-before-spend, auditable from the filesystem

The fixture run asks Wan for a rightward pan on shot 1 and gets back a static shot — a real
instruction-following failure, not a staged one. The repair loop's real trajectory
(re-measured 2026-07-20 on the corgi pack):

| Take | Tier | Measured | Verdict |
|---|---|---|---|
| 0 | draft (720p) | `camera static, \|v\|=0.028` (want `right`) | **FAIL** — blocking |
| 1 | draft (720p) | `camera right, \|v\|=4.871` | PASS — certified |

Tier-A caught it for **zero tokens** — optical flow, no VLM call.

Two details worth reading off that table rather than around it.

**The retake is a fresh t2v roll, not a frame-anchored i2v one.** Tier-A localized the failure
to `fail_window_s: [0.0, 5.33]` — the whole clip. A camera that never moves has no *last good
frame* to continue from, so `_anchor_for_retake` returns None and the pipeline falls back to
re-rolling from the repaired prompt. The anchor path is for failures with a before; this
failure has none.

**Shot 1 never promotes.** Shots 0 and 2 each spend a second generation on a frame-anchored
`wan2.2-i2v-flash` final; shot 1 ships the draft that satisfied the contract. Four drafts,
**two** promotions — and the missing third is exactly the shot whose first take failed. Nothing
suppressed it; the pipeline never promotes a draft that didn't pass. That absence is the
architecture working, and it is checkable with `ls`.

### 4.4 Quota consumed to date

| Model | Used | Free quota | Remaining |
|---|---|---|---|
| `wan2.1-t2v-turbo` (drafts, `1280*720`) | 4 cycles (20 s) | 40 cycles (200 s) | **36** |
| `wan2.2-t2v-plus` (finals, `1920*1080`) | 3 cycles (15 s) | 10 cycles (50 s) | **7** |
| `wan2.1-t2i-plus` (Tier-0 stills) | 3 images | 200 images | 197 |

35 video-seconds total, ever. Every subsequent replay of the demo is free.

## 5. Tier-0: the gate that was never wired (Jul 15)

Section 3b confirmed the t2i endpoint and that a still generates. It did not — and could
not — confirm that anything ever *looked* at the still. Nothing did.

`subject_present` is one of the ten types in the closed vocabulary, carries `advisory=False`
(blocking-class, not a warning), and was evaluated by **nothing** in any production path:

- `tier0_fn` was `lambda spec, still: []` in all three runtimes (`app.py`, `demo.py`,
  `fixtures.py`), annotated "Tier-0 still checks are a cut-line item".
- `pipeline._tier0` generated **and billed** one t2i still per shot anyway, then called that
  stub and stored its empty list.
- `tier_b.py` carried a `_question` branch for `subject_present` that `ASSERTION_META` made
  unreachable — the type routes to `Tier.TIER0`, and Tier-B's filter selects only
  `Tier.TIER_B`. That branch is what made the check look wired.

The cut was half-made: the expensive half (generate the still) stayed, the valuable half
(read it) was dropped, and three docs kept advertising both.

### 5.1 Why a green suite missed it

The same shape as the four bugs in 4.2 — *a fallback that makes failure look like success* —
with a test-design twist worth naming. At

```
take.passed = not [r for r in results if not r.advisory and r.status is Status.FAIL]
```

a check that returns **no result** and a check that **passes** are the same empty list. Every
existing test asserted on results that exist, so no test could fail when a result was
silently missing. `test_specs.py`'s `len(ASSERTION_META) == 10` actively reinforced the
illusion: it proves each type is *declared*, never that anything *evaluates* it.

`tests/test_vocabulary_coverage.py` closes the class rather than the instance. It drives all
ten types through their owning tier and demands a result comes back, then asserts that each
of the three production runtimes injects a Tier-0 that returns a verdict. Both halves are
needed — an evaluator existing and the pipeline calling it are different facts, and only the
wiring test fails when the stub comes back.

Confirmed by re-introducing the stub: the wiring test fails, and restoring it passes. A test
never observed failing is not evidence.

### 5.2 Live measurement — `qwen-vl-plus` on a real cached still

| subject asked of the still | verdict | latency | tokens in/out |
|---|---|---|---|
| "a lighthouse keeper" (present) | PASS | 4.1 s | 325 / 33 |
| "a yellow school bus" (absent) | **FAIL** | 2.7 s | 325 / 31 |

Both directions were run deliberately: a check that only ever answers PASS is not a check.

**325 tokens to avoid a 5-second premium clip** — the reject-before-spend thesis at the
cheapest point in the cascade, now measured rather than asserted.

The still is downscaled to 512 px before it is sent (`STILL_WIDTH` in `server/tier0.py`).
The t2i models return 1024×1024; at source resolution the "1/25th of a clip" pre-screen
would cost more image tokens than the seven frames Tier-B sends for the *entire* video,
inverting the reason Tier-0 runs first. Downscaling cuts the payload to 27% of full-res.

### 5.3 Scope, stated precisely

A Tier-0 verdict is **evidence at the human review gate, not an automatic block.** Nothing
gates on `tier0_results`: the pipeline stores them and the UI renders them at the one human
checkpoint (`ReviewBar` in `web/src/components.tsx`), where the human decides whether to release video
budget. `advisory=False` marks `subject_present` blocking-class — it *would* block if it
appeared in a take's results — but its Tier-0 job is to inform the gate, and it never reaches
a take today.

Where it is exercised: demo mode's second shot declares `subject_present` (deterministic,
zero tokens). The fixture pack's three pinned shots declare no subject, so Tier-0 does not
run there — adding it would put a live VLM call on the "warm = 6 s" path measured in 4.1 and
that number would have to be re-measured, so it is left as a deliberate choice rather than a
silent one. Real mode exercises Tier-0 whenever the script agent emits `subject_present`,
which `server/script.py` instructs it to do for a named character.

## 6. Remaining eligibility items (manual)

- [ ] Alibaba Cloud Workbench screenshot showing running SAS resources ("no proof = not eligible")
- [ ] Public GitHub repo with MIT badge visible

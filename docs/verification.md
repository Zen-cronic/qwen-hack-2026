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

| Bug | Why 79 passing tests missed it |
|---|---|
| `wan2.2-t2v-plus` rejects `1280*720` — **every premium promote ever made had failed** with `InvalidParameter` in ~16 s | `_promote` treats a failed promote as "keep the passing draft", so a rejected final and a healthy skip produced identical state. The cost-tiered cascade — the wedge — had never run its premium tier. |
| The budget governor asked the cache about `1280*720` for **every** model | Size is part of the cache key, so it looked up the wrong key for finals and called every cached final "fresh". Under `JUDGE_MODE` (`fresh_final_cap=0`) that would have refused free replays of finals *during judging*. |
| The ledger wrote an empty `note` for both a no-op call and a hard failure | Which is precisely how the first two hid. The audit trail didn't audit. `_spend_note` now records the failure code. |
| `state.json` was write-only | Snapshots were atomically written and never read back. A push to main redeploys the box, so every release silently discarded every run a viewer had made — while the deployment diagram (`docs/architecture.md:183`) promised "cache + state persist across restarts". The cache did; state didn't. |

Fixed in `2917b09`; each fix has a regression test (`tests/test_wan.py`, `tests/test_fixtures.py`),
verified by reverting the fix and confirming the test fails.

**The finding under the findings:** the project's own thesis is that generated video ships
unverified because nobody runs the claim against the artifact. The premium tier had been
dead for the project's entire life, in a repo whose pitch is a conformance gate. Mocks test
the code you wrote; fixtures test the assumption you made. This bug lived in the gap.

### 4.3 Reject-before-spend, auditable from the filesystem

The fixture run asks Wan for a rightward pan on shot 1 and gets back a static shot — a real
instruction-following failure, not a staged one. The repair loop's real trajectory:

| Take | Tier | Measured | Verdict |
|---|---|---|---|
| 0 | draft (720p) | `camera static, \|v\|=0.34` (want `right`) | **FAIL** — blocking |
| 1 | draft (720p) | `camera right, \|v\|=1.47` | PASS |
| 2 | final (1080p) | `camera right, \|v\|=2.43` | PASS — certified |

Tier-A caught it for **zero tokens** — optical flow, no VLM call.

The cache is the receipt. Four prompts were drafted at `1280*720`; only **three** have a
matching `1920*1080` final. The missing one is `PAN_ASKED` — the exact draft that failed
Tier-A. Nothing suppressed it; the pipeline never promotes a draft that didn't pass, so
those 5 s of premium quota were never spent. The absence of that one cache entry *is* the
architecture working, and it is checkable with `ls`.

### 4.4 Quota consumed to date

| Model | Used | Free quota | Remaining |
|---|---|---|---|
| `wan2.1-t2v-turbo` (drafts, `1280*720`) | 4 cycles (20 s) | 40 cycles (200 s) | **36** |
| `wan2.2-t2v-plus` (finals, `1920*1080`) | 3 cycles (15 s) | 10 cycles (50 s) | **7** |
| `wan2.1-t2i-plus` (Tier-0 stills) | 3 images | 200 images | 197 |

35 video-seconds total, ever. Every subsequent replay of the demo is free.

## 5. Remaining eligibility items (manual)

- [ ] Alibaba Cloud Workbench screenshot showing running SAS resources ("no proof = not eligible")
- [ ] Public GitHub repo with MIT badge visible

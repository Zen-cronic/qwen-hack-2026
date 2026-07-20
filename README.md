# Dailies — test your generated video like you test your code

[![CI](https://github.com/Zen-cronic/qwen-hack-2026/actions/workflows/ci.yml/badge.svg)](https://github.com/Zen-cronic/qwen-hack-2026/actions/workflows/ci.yml)

Write what each shot has to do. Every take gets measured against it before it ships — and the
ones that miss get re-rendered, not shipped. Built on Qwen Cloud for the Global AI Hackathon
Series (Track 2 — AI Showrunner).

**Write the spec → approve the shot list → ship what passes.**
*Checked, not hoped · repaired, not re-rolled · any mp4, from any model.*

Give Dailies a premise and it writes the shot list, renders each shot, and measures every take
against the rules you set. A take that misses gets one bounded repair attempt. A take that
still misses never reaches your cut.

**Built on Qwen Cloud, end to end.** A `qwen-plus` agent authors each run by function-calling
`build_pipeline_graph`; **Wan** generates every shot and, when one breaks its contract, a
frame-anchored **Wan i2v** retake repairs it; **Qwen-VL** grades both the pre-render still and
the finished motion; **Qwen-TTS** narrates the certified cut. The verification half is then
re-exposed three ways — a native function-calling tool, a Qwen-Agent custom skill, and **an MCP
server a Qwen agent consumes** — so any pipeline or agent can gate generated video the way it
gates code. The full surface, mapped to the judging rubric, is in
[docs/qwen-usage.md](docs/qwen-usage.md).

![A Qwen agent reaching Dailies' conformance gate through the Model Context Protocol — client and server both ours. MCP ListTools returns two tools: run_shot_tests (free, deterministic, any mp4) and patch_clip (spends one i2v generation). The agent calls the free one with a camera_motion assertion merged over the brand_rules pack, and Dailies returns a real FAIL — camera static, |v|=0.00 — which the agent explains before offering to patch the clip.](docs/mcp-loop.png)

<sub>A real, unedited capture of `scripts/mcp_agent_demo.py`: a Qwen agent lists Dailies' **own** MCP tools, calls the free one, gets a deterministic Tier-A verdict back — and then offers to repair the clip, because MCP told it Dailies can act on a verdict as well as report one. Chat tokens only, zero video quota.</sub>

## The idea (improvement statement)

AI video fails *in motion*, after you've already paid for it — a gorgeous keyframe
becomes a clip that pans the wrong way, flickers, or drops the character. Existing tools
maximize output; **nobody tests the product**.

Dailies is the part nobody built: **the tests**. You write what a shot has to do — how long,
how bright, which way the camera moves, whether the title card is really there — and every take
is measured against it. The cheap checks are plain OpenCV that spends **zero tokens, so they run
on every take**; model-graded judgment sits on top as advice, never as the foundation. And
because the checks read frames rather than generator internals, Dailies stands outside the
pipeline it judges: point it at any mp4, from any generator.

Stated plainly so it can be argued with: Dailies is the only **standalone, model-agnostic
per-shot conformance gate** — authored shot specs compiled through a closed assertion grammar
into a cost-tiered cascade with bounded auto-repair. That claim is shape, not primacy, and it is
checkable. Research prototypes (Genflow Ad
Studio, VideoRepair) explore VLM-critique loops but don't ship; OpenMontage (~39.8k stars)
hard-gates its own renders — video-level, self-graded, inside its own pipeline, no assertion
grammar; Kinocut gates release on MCP quality checkpoints with no shot spec and no repair;
VBench grades *models* on a benchmark suite, not *your shots* against *your spec*; LTX Studio
locks storyboards on the authoring side but never verifies the rendered result; broadcast QC
has gated delivery against *technical* specs for a decade, never creative intent. The full
survey — including how it forced this paragraph's own rewrite — is in
[docs/market-landscape.md](docs/market-landscape.md).

### Why "Dailies"

In film production, *dailies* are the screening where yesterday's footage is reviewed before
more money is spent on top of it. Generation pipelines have started borrowing the word — and
proving the thesis while doing it: one shipping logline-to-video pipeline we surveyed carries
the config line `DAILIES_QC = False  # off = faster pipeline`, its review stage built and
then shipped switched off. When the gate lives inside the generator's codebase, the gate is
what gets traded for throughput. Dailies is the review stage that can't be quietly switched
off — because it doesn't belong to the pipeline it judges.

## Who it's for (and why it matters)

Every team adopting AI video quietly appoints a **human test suite** — one person who eyeballs
each clip for brand palette, length, flicker, character continuity, and whether the brief was
followed. That person is the bottleneck for everyone upstream who *owns* "correct" but can't
check it themselves. Dailies decouples the two roles: the stakeholder (brand / marketing / legal)
authors a machine-checkable spec once, and every generated shot is tested against it
automatically — spec-driven development, for video. The buyer is **marketing ops**, who already
pays for those review hours; the value is the human-review time an automated gate removes as teams
move to unattended batch generation. Because checks read frames, not generator internals, the
assertion layer is **model-agnostic** and outlives any one model. Full strategic case —
competitor analysis, moat, and productization path — in [docs/impact.md](docs/impact.md).

## How it works

```
premise → script + specs (qwen-plus) → compiled assertion checklist
        → Tier-0 still pre-screen (t2i, ~1/25th of video cost)
        → [human review gate — the one checkpoint, before any video spend]
        → drafts (wan2.1-t2v-turbo)
        → Tier-A CV (deterministic, ZERO tokens — the never-cut spine)
          + Tier-B VLM verdicts (qwen-vl, advisory)
        → bounded prompt-repair + retake
        → promote passing shots (wan2.2-i2v-flash, anchored on the approved frame)
        → narration (qwen3-tts-flash) → ffmpeg assembly → certified episode, with sound

        …and afterwards, per shot, without re-running any of the above:
        → targeted patch (wan2.2-i2v-flash / wan2.1-kf2v-plus)
```

- **A closed assertion DSL — 10 sentence types** across 3 tiers (`server/specs.py`). A spec is a
  short program in this language; the compiler translates each sentence to a call in a common check
  library and rejects any sentence outside the grammar *before* spending a token — that rejection is
  the DSL's compile error, and the literal "CI" in "CI for generated video". See [the grammar](#the-assertion-dsl) below.
- **Tier-A** (`server/tier_a.py`) is deterministic OpenCV — duration, brightness, flicker,
  scene cuts, camera motion (optical flow), palette ΔE. Zero tokens, so it runs on every take.
  It reports **where** a check fails, not just that it did: the per-frame series behind each
  measurement is kept, so a failure carries a time window (`fails 2.1s → 3.4s`) and writes the
  frame it actually indicted.
- **Targeted repair — edit a shot without re-running the pipeline** (`server/patch.py`). That
  window gives an anchor: the frame just before the defect. A frame-anchored Wan model
  re-renders the shot from there on a locus-aware prompt, Tier-A re-verifies, and a passing
  patch re-cuts the episode for free. No script call, no Tier-0, no review gate, no other shot.
  A patch has to earn the slot — if it still fails, the original clip stays. Anchored
  re-renders run on the i2v/kf2v free-tier pool, separate from the t2v draft/final quota.
  When the failure window opens at `0s` there is no good frame to keep — the defect is the
  whole clip — so the patch re-rolls from the corrected prompt instead of continuing from
  the very frame it needs to change, and draws t2v quota for that one case. Anchor to
  preserve, re-roll to change: [measured, not assumed](docs/verification.md).

  > **Live receipt** (Jul 19, when promotion still re-rolled on the premium t2v tier — this run is
  > what motivated anchoring promotion too, [verification §3e](docs/verification.md)).
  > On run `3e1f628d4acf`, the premium `wan2.2-t2v-plus` render of shot 0
  > drifted the camera left (`|v|=0.92`) against a `camera_motion: static` contract, so the gate
  > rejected it and the pipeline shipped the turbo draft instead. Tier-A placed the drift at
  > **0.4s–3.6s**; a patch anchored at **0.2s** re-rendered from the premium frame and came back
  > at **`|v|=0.09`, all five Tier-A checks green**, for 5 billed video-seconds. The premium look,
  > under contract — recovered by the same gate that rejected it.
- **Cost-quality frontier** is a first-class, measured feature: every call logs token/quota
  spend to a ledger (`server/metrics.py`); the dashboard charts pass-rate heatmaps, a
  cost-quality scatter, repair convergence, and cost-per-passing-second.
- **Judge-safe:** a content-addressed cache makes re-verification of cached clips cost zero
  video quota, so the live URL survives the judging window.
- **Agent-authored pipeline graph:** describe the episode in plain language and a Qwen tool
  (`build_pipeline_graph`, `server/agent_plan.py`) wires the run as a node graph — the model
  supplies only validated parameters, so the topology is always well-formed — then hands off
  to the same pipeline. The graph is a live control surface (React Flow, `web/src/graph.ts`)
  derived from the ordinary 2.5s poll.

![A Qwen agent wires the pipeline from a plain-language request — shot list, deterministic CV
and VLM checks, the human review gate, and a certified cut — as a live graph you can watch
run](dailies-agent.png)

![The finished run — capability heatmap, cost–quality frontier, repair convergence, and the
conformance board over a certified episode](dailies-done.png)

*(The other checkpoint that matters: [the review gate](dailies-review.png) — Tier-0 still
evidence on screen, before a single video-second is spent.)*

### Wired to Qwen Cloud and Alibaba Cloud

Dailies runs **on** Alibaba Cloud, not merely **against** its APIs: backend compute is a SAS
instance in `us-west-1`, media durability is OSS, and the run catalog is Postgres. Every row
below is a file you can open.

**Qwen Cloud — two API shapes, because the models need different ones.** Chat and vision go
through the **OpenAI-compatible** endpoint (`/compatible-mode/v1`), so the same `openai` client
carries function calling and structured output. Generation is long-running, so video, image and
speech go through the **native DashScope task API** — submit, poll, fetch — which the
OpenAI-compatible shape has no vocabulary for.

| Model | Role in the pipeline | Where |
|---|---|---|
| `qwen-plus` | Writes the shot list; compiles plain-language custom checks into the closed DSL; rewrites a failing prompt for a bounded retake; backs the `build_pipeline_graph` tool | `server/script.py`, `server/agent_plan.py` |
| `qwen-vl-plus` | Tier-0 verdicts on the pre-render still, and Tier-B advisory verdicts on frames | `server/tier0.py`, `server/tier_b.py` |
| `wan2.1-t2i-plus` | The Tier-0 still — pre-screens static assertions at ~1/25th of video cost | `server/wan.py` |
| `wan2.1-t2v-turbo` | Draft takes, the cheap tier every shot starts on | `server/wan.py` |
| `wan2.2-i2v-flash` | Frame-anchored work: the retake after a repair, and promotion of a passing draft — the anchor is what makes a final a *continuation* of the approved take rather than a fresh roll | `server/patch.py`, `server/pipeline.py` |
| `wan2.2-t2v-plus` | Fallback final, when no frame-anchored model is wired | `server/pipeline.py` |
| `qwen3-tts-flash` | Narration, one voice per character, cached like video | `server/tts.py` |

Note what the table implies about cost: **the deterministic tier is absent from it.** Tier-A is
OpenCV (`server/tier_a.py`) and calls nothing, which is the whole reason it can run on every
take — the Qwen surface is spent on generation and judgment, never on measurement.

**Alibaba Cloud services.**

| Service | What it holds | Notes |
|---|---|---|
| **SAS instance** (`us-west-1`) | The entire app — nginx + FastAPI + Postgres via one `docker compose` | Backend compute runs here, not just API calls from elsewhere ([deploy.md](docs/deploy.md)) |
| **OSS** (private bucket) | Published media, addressed by content hash (`media/<sha1>.mp4`) | Uploads use the **internal** endpoint from the box (free same-region traffic); browsers get a **presigned GET** (~1h). `server/oss.py` |
| **Postgres 18** | The catalog: finished runs as relational rows — projects, shots, takes, assertion results, ledger | Sidecar container, no public port. `server/db/models.py`, `server/catalog.py` |

The catalog is **additive and flag-gated** (`CATALOG_ENABLED`, default off): live runs stay on the
in-memory store and atomic `state.json`, and a run is mirrored into Postgres + OSS only once it
finishes. Publishing tolerates a dead database or bucket and never raises, because a storage
outage must not fail a run that already passed its gates — the conformance verdict is the
product, and archiving it is a separate concern with a lower right to fail.

One thing that bit us and is worth stating plainly: media paths are **many-to-one** against
content. Deterministic runs produce byte-identical episodes, so ~40 project paths collapsed onto
13 objects — which is why the path→hash mapping lives in its own `media_paths` table rather than
as a column on the object, where it would keep only the last path and 404 every other one.

### The closed assertion vocabulary

An assertion is a `type` from a **closed** set plus typed `params`. The compiler
(`server/specs.py` → `server/compiler.py`) translates each one into a call in a common check
library — a zero-token OpenCV routine (Tier-A) or a `qwen-vl` prompt (Tier-B) — and **rejects
anything outside the set before a token is spent**: `parse_assertions` raises on an unknown `type`
or malformed `params`. The closure holds at the process boundary too — send `{"type":
"vibe_check"}` to the MCP server and it comes back `isError: True`, not a guess.

The 10 types, their tier, and what each compiles to:

| Assertion type | Tier | Params | Compiles to |
|---|---|---|---|
| `duration_between` | A · deterministic | `min_s`, `max_s` | clip length within bounds |
| `brightness_range` | A · deterministic | `min`, `max` | mean-luma within bounds |
| `flicker_below` | A · deterministic | `max_std` | inter-frame luma std under threshold |
| `scene_cuts` | A · deterministic | `max` | HSV-histogram cut count at or under max |
| `camera_motion` | A · deterministic | `direction` (`left`\|`right`\|`up`\|`down`\|`static`\|`any`) | optical-flow pan direction |
| `palette_deltae` | A · deterministic | `palette`, `max_delta` | dominant-color ΔE to a brand palette |
| `subject_present` | 0 · pre-render still | `subject` | subject recognizable in the t2i still |
| `identity_consistent` | B · advisory | `subject` | VLM: same identity across frames |
| `action_completed` | B · advisory | `action` | VLM: the briefed action visibly completes |
| `title_card_present` | B · advisory | *(none)* | VLM: a title / text card is visible |

Tier-A sentences are deterministic and block promotion; Tier-B sentences are advisory (a VLM
judgment is softer evidence than a pixel measurement, so it flags for the human and never blocks).
The single Tier-0 sentence is asked of the pre-render *still* — 325 tokens to learn a prompt can't
render its own subject, before that shot costs a single video second — and its verdict is evidence
at the human review gate rather than an automatic block ([measured](docs/verification.md#5-tier-0-the-gate-that-was-never-wired-jul-15)).
User-authored plain-language rules compile *into* this same vocabulary (`server/script.py`). A rule
needing a modality the vocabulary lacks — audio, on-screen text, a time window like "the outro" — is
**omitted rather than approximated** with a type that means something else; the compiler never fakes
a check it cannot run. Known gap: that omission is currently silent, so an author gets no diagnostic
saying their rule went uncompiled.

## Run it

**Backend + tests** (Python 3.12):

```bash
python3.12 -m venv .venv && source .venv/bin/activate   # any Python 3.12 interpreter
cp .env.example .env               # add your QWEN_API_KEY
pip install -e ".[dev,mcp,agent]"  # mcp + agent extras: without them, those surfaces' tests skip
python scripts/verify_quota.py     # day-1 gate: API access + video-gen quota
pytest -q                          # full suite, no network needed
uvicorn server.app:create_production_app --factory --port 8099
```

**Zero-quota demo mode** (real pipeline + CV on synthetic clips, no video spend):

```bash
DAILIES_DEMO=1 SPA_DIST=web/dist uvicorn server.app:create_production_app --factory --port 8099
```

**End-to-end UI test** (Playwright drives the whole journey — premise → review gate →
certified episode — against the demo runtime; boots its own server, zero video quota):

```bash
npm --prefix web run build && npm --prefix web run e2e
```

**Qwen tool & MCP integration** (needs `pip install -e ".[agent]"` + a live key; chat tokens only):

```bash
python scripts/qwen_tool_demo.py    # qwen-plus calls run_shot_tests as a custom tool (function calling + Qwen-Agent)
python scripts/mcp_agent_demo.py    # a Qwen agent calls it through MCP (client + server both ours)
python -m server.mcp_server         # the raw MCP server (stdio) — the productization surface
```

See [docs/demo.md](docs/demo.md) for the full < 3-min demo run-of-show.

**Frontend** (Vite + React + TS):

```bash
npm --prefix web install && npm --prefix web run build   # -> web/dist
npm --prefix web run dev                                  # dev server, proxies /api
```

**Docker (deploy topology):** `docker compose up -d --build` → nginx (`:80`) serves the SPA
and proxies `/api` to the uvicorn app. A push to `main` triggers the deploy workflow
(GitHub Actions → SSH into the Alibaba Cloud SAS box → rebuild + health-gate); it needs the
three `SERVER_*` secrets from the runbook — see [docs/deploy.md](docs/deploy.md).

System dependency: `ffmpeg` (assembly).

## Docs

- [docs/qwen-usage.md](docs/qwen-usage.md) — how Dailies uses Qwen Cloud (function calling, custom skills, MCP producer+consumer, Wan, Qwen-VL, Qwen-TTS), mapped to the judging rubric
- [docs/demo.md](docs/demo.md) — demo run-of-show (< 3 min) showcasing the workbench, Qwen custom tool, and MCP loop
- [docs/impact.md](docs/impact.md) — Problem Value & Impact: pain, buyer, competitor analysis, moat, productization path
- [docs/market-landscape.md](docs/market-landscape.md) — the cited survey behind the improvement statement (and how it rewrote our own claim)
- [docs/architecture.md](docs/architecture.md) — C4 system-context + container diagrams (submission deliverable)
- [docs/profiling.md](docs/profiling.md) — per-tier cost/latency profiling (measured demo run + modeled cost design)
- [docs/verification.md](docs/verification.md) — verification log: the day-1 quota/API/Tier-B gate, the first real end-to-end run (the four bugs synthetic clips hid), and the Tier-0 gate that was billed but never wired
- [docs/deploy.md](docs/deploy.md) — Alibaba Cloud SAS deploy runbook
- [docs/hackathon.md](docs/hackathon.md) — hackathon source links
- [PLAN.md](PLAN.md) — build plan; [SUBMISSION.md](SUBMISSION.md) — deliverables checklist

Qwen models are called via the Qwen Cloud OpenAI-compatible endpoint
(`dashscope-intl.aliyuncs.com/compatible-mode/v1`) and the native async video/image task API.
Backend runs on Alibaba Cloud (SAS). MIT licensed.

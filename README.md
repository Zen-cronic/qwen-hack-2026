# Dailies — the neutral conformance gate for AI-generated video

[![CI](https://github.com/Zen-cronic/qwen-hack-2026/actions/workflows/ci.yml/badge.svg)](https://github.com/Zen-cronic/qwen-hack-2026/actions/workflows/ci.yml)

*CI for video shots: assertions compile, the deterministic tier spends zero tokens, failures
auto-repair or fail the build.* Built on Qwen Cloud for the Global AI Hackathon Series
(Track 2 — AI Showrunner).

Dailies takes a premise, writes a shot list, and — before any clip ships — runs each
generated shot through a **cost-tiered conformance cascade**. A shot that violates its
contract never costs premium tokens and never reaches your channel.

## The idea (improvement statement)

AI video fails *in motion*, after you've already paid for it — a gorgeous keyframe
becomes a clip that pans the wrong way, flickers, or drops the character. Existing tools
maximize output; **nobody tests the product**.

Dailies is the only **standalone, model-agnostic per-shot conformance gate**: authored shot
specs compile through a closed assertion DSL into a cost-tiered cascade with bounded
auto-repair. The spine of that cascade is deterministic OpenCV that spends **zero tokens — so
it runs on every take**; model-graded judgment is the advisory layer on top, never the
foundation. And because checks read frames, not generator internals, the gate stands outside
the pipeline it judges: point it at any mp4, from any generator.

That claim is shape, not primacy, and it is checkable. Research prototypes (Genflow Ad
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
        → promote passing shots (wan2.2-t2v-plus)
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
  A patch has to earn the slot — if it still fails, the original clip stays. Runs on the
  i2v/kf2v free-tier pool, separate from the t2v draft/final quota.

  > **Live receipt.** On run `3e1f628d4acf`, the premium `wan2.2-t2v-plus` render of shot 0
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

![The finished run — capability heatmap, cost–quality frontier, repair convergence, and the
conformance board over a certified episode](dailies-done.png)

*(The other checkpoint that matters: [the review gate](dailies-review.png) — Tier-0 still
evidence on screen, before a single video-second is spent.)*

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
pytest -q                          # 118 passed
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

# Dailies — CI for AI-generated video

*pytest for video shots.* Built on Qwen Cloud for the Global AI Hackathon Series (Track 2 — AI Showrunner).

Dailies takes a premise, writes a shot list, and — before any clip ships — runs each
generated shot through a **cost-tiered conformance cascade**. A shot that violates its
contract never costs premium tokens and never reaches your channel.

## The idea (improvement statement)

AI video fails *in motion*, after you've already paid for it — a gorgeous keyframe
becomes a clip that pans the wrong way, flickers, or drops the character. Existing tools
maximize output; **nobody tests the product**. Research prototypes (Genflow Ad Studio,
VideoRepair) explore VLM-critique loops but don't ship; VBench grades *models* on a
benchmark suite, not *your shots* against *your spec*; LTX Studio locks storyboards on the
authoring side but never verifies the rendered result.

Dailies is the first shipped **per-shot conformance harness**: shot specs compile to a
closed vocabulary of machine-checkable assertions, run as a cost-tiered cascade with
budget-bounded auto-repair.

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
        → ffmpeg assembly → certified episode
```

- **A closed assertion DSL — 10 sentence types** across 3 tiers (`server/specs.py`). A spec is a
  short program in this language; the compiler translates each sentence to a call in a common check
  library and rejects any sentence outside the grammar *before* spending a token — that rejection is
  the DSL's compile error, and the literal "CI" in "CI for generated video". See [the grammar](#the-assertion-dsl) below.
- **Tier-A** (`server/tier_a.py`) is deterministic OpenCV — duration, brightness, flicker,
  scene cuts, camera motion (optical flow), palette ΔE. Zero tokens, so it runs on every take.
- **Cost-quality frontier** is a first-class, measured feature: every call logs token/quota
  spend to a ledger (`server/metrics.py`); the dashboard charts pass-rate heatmaps, a
  cost-quality scatter, repair convergence, and cost-per-passing-second.
- **Judge-safe:** a content-addressed cache makes re-verification of cached clips cost zero
  video quota, so the live URL survives the judging window.

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
pytest -q                          # 113 passed
uvicorn server.app:create_production_app --factory --port 8099
```

**Zero-quota demo mode** (real pipeline + CV on synthetic clips, no video spend):

```bash
DAILIES_DEMO=1 SPA_DIST=web/dist uvicorn server.app:create_production_app --factory --port 8099
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
and proxies `/api` to the uvicorn app. A push to `main` auto-deploys to the Alibaba Cloud SAS
box (GitHub Actions → SSH → rebuild + health-gate); see [docs/deploy.md](docs/deploy.md).

System dependency: `ffmpeg` (assembly).

## Docs

- [docs/demo.md](docs/demo.md) — demo run-of-show (< 3 min) showcasing the workbench, Qwen custom tool, and MCP loop
- [docs/impact.md](docs/impact.md) — Problem Value & Impact: pain, buyer, competitor analysis, moat, productization path
- [docs/architecture.md](docs/architecture.md) — C4 system-context + container diagrams (submission deliverable)
- [docs/profiling.md](docs/profiling.md) — per-tier cost/latency profiling (measured demo run + modeled cost design)
- [docs/verification.md](docs/verification.md) — verification log: the day-1 quota/API/Tier-B gate, the first real end-to-end run (the four bugs synthetic clips hid), and the Tier-0 gate that was billed but never wired
- [docs/deploy.md](docs/deploy.md) — Alibaba Cloud SAS deploy runbook
- [docs/hackathon.md](docs/hackathon.md) — hackathon source links
- [PLAN.md](PLAN.md) — build plan; [SUBMISSION.md](SUBMISSION.md) — deliverables checklist

Qwen models are called via the Qwen Cloud OpenAI-compatible endpoint
(`dashscope-intl.aliyuncs.com/compatible-mode/v1`) and the native async video/image task API.
Backend runs on Alibaba Cloud (SAS). MIT licensed.

# Problem Value & Impact

*Why Dailies exists, who pays for it, and how it scales — the strategic case behind "CI for AI-generated video."*

## The pain (authentic, and already attested in this repo)

Every team that adopts AI video has quietly appointed a **human test suite**: one person who
eyeballs each generated clip for brand palette, length, flicker, character continuity, and
whether the brief was actually followed. That person is the bottleneck for everyone upstream
who *owns* "correct" but can't check it themselves — brand, legal, and the founder Slack "is
the vibe right?" and wait.

This is not a hypothetical persona. It is the audience the codebase was built around:
`packs/brand_rules.yaml` and `PLAN.md` name the primary user as **"a one-person social team
shipping unattended AI video."** The core insight is organizational, not technical:

> The person who **defines** "correct" (brand / marketing / legal) is not the person who
> **operates** the generator (the video editor). Today those roles are coupled through a
> human reviewer. Dailies decouples them: the stakeholder authors the contract once, in
> plain language, and every generated shot is tested against it automatically.

That is spec-driven development applied to media — the same shift software made from "manually
eyeball each build" to "CI runs the tests."

## Why it matters (the impact, and who pays)

The buyer is **marketing ops**, not the freelancer. They already own brand-risk liability and
already pay for the human review hours Dailies removes — so the ROI is denominated in a line
item their budget understands. The value compounds with generation volume: the moment a team
moves from eyeballing every clip to **unattended batch generation**, an automated conformance
gate is what makes that batch *deployable* — nobody has to watch all fifty clips in the morning.

Dailies makes the cost of that shift legible. Every Qwen/Wan call is logged to a ledger
(`server/metrics.py`), and the wallet reports what a batch **would cost at production list
prices** ("$X in production") while the hackathon runs on free-tier quota. The wedge is simple:
as generated-video volume goes up, the human-review bottleneck gets worse, and an independent
conformance gate gets more valuable — not less.

## Who it's for (three tiers)

- **Primary — marketing / social teams running unattended AI-video batches.** Brand rules as
  assertions; the QC gate is what makes unattended generation shippable.
- **Secondary — developers building on video-gen APIs.** Assertion packs as **regression tests
  in CI**; model-agnostic, so they *outlive any one generator* (Wan today, whatever's next).
- **Tertiary — AI drama studios.** The certified episode *is* the "short drama pipeline" the
  track asks for.

## "Why won't Mux or Adobe just build this as an add-on?"

The honest answer is **structural**, not "we'll move faster":

- **Generators (Runway, Pika, Luma, Kling, Sora) can't credibly grade their own output.** A
  green light from the vendor whose model just failed is marking its own homework — a brand-risk
  owner won't accept it — and each only covers its *own* model, so none can be the neutral gate
  a studio running four models needs.
- **Mux sells neutral *extraction* to engineers** ("what's in this video" — captions, tags,
  moderation), not a *conformance verdict against an authored spec* to a producer. Dailies sits
  one layer up and can consume Mux-style extraction as an input. Complement, not competitor.
- **Adobe is the real adjacent player, and we say so plainly.** GenStudio / Firefly already ships
  brand-check → compliance *score* → *regenerate* on generated content, with distribution and
  enterprise trust. But that loop is **locked to the Adobe stack** and today enforces **static
  brand rules**, not cross-model, video-native, time-based assertions.

So the defensible seat is scope, not a slogan: **Dailies is the neutral conformance gate for the
majority of teams generating *outside* any single vendor's walled garden.** Honest concession:
*inside Adobe's stack, on Adobe's models, Adobe wins.* Our wedge is the multi-model shop.

## The one real moat (with a mechanism)

The VLM eval primitive itself is commodity — open harnesses (VBench, VLM-as-judge) already grade
video quality, so "we test video with a model" is not defensible. The one asset with a
**compounding mechanism** is the **human-override calibration corpus**: every approve/reject at
the human gate (`POST /api/projects/{id}/verdict`) is a labeled datum — where the machine said
*pass* but a human said *fail*, and vice-versa — per assertion type × model × genre. That
labeled-disagreement corpus is exactly what tunes the gate to be more trustworthy than a raw
model call, it is collectable **only from the buyer-side review seat**, and it is structurally
unavailable to a self-grading generator or a static-rule loop. Neutrality is the *reason* that
seat exists; the calibration corpus is the *asset* that makes it widen over time.

## Productization path (commercial scaling / OSS adoption)

The criterion rewards a productization path over revenue, and Dailies' architecture makes one
concrete — **assertion packs are data, not code** (`packs/*.yaml`):

- **A consumable library / package (`@dailies/vidtest`).** The assertion engine (`server/specs.py`,
  `server/tier_a.py`, `server/compiler.py`) has no Wan coupling — deterministic checks run on any
  mp4 — so it lifts out as a standalone package a dev drops into CI as **regression tests for
  generated video**.
- **An MCP server** exposing `run_shot_tests` (and, next, `compile_shot` / `get_conformance_report`)
  so any pipeline or agent can **gate video the way it already gates code**. Shipped in
  `server/mcp_server.py` — a live, runnable surface, not a slide.
- **Model-agnostic by construction.** Checks take frames, not generator internals — swap the model,
  the conformance layer is unchanged. This is the real "works with any video model" claim and the
  root of the OSS-adoption path: packs run as regression tests that outlive any one generator.

## Honest scope — what's built vs. what's roadmap

The pitch survives "show me" because we do not claim what the engine can't do. Assertions are
**per-shot (~5s)**, evaluated **whole-clip**, from a **closed, validated vocabulary** — there is
no audio/transcript, no OCR, no time-windowing, and no episode-level concept today.

| Capability | Status | Note |
|---|---|---|
| 6 deterministic CV checks (duration, brightness, flicker, scene-cuts, camera-motion, brand-palette ΔE) | **BUILT** | Zero-token, runs on every take (`server/tier_a.py`) |
| 2 VLM-advisory checks (identity continuity, briefed-action) | **BUILT** | Advisory — flags for the human, never blocks (`server/tier_b.py`) |
| "Title / text-card present?" advisory check | **BUILT** | Whole-clip VLM judgment (no OCR) |
| Author your own checks in plain language | **BUILT** | Compiled to the validated vocabulary, rejected-before-spend (`server/script.py`) |
| Reject-before-spend gate, cost-tiered cascade, bounded auto-repair, re-verify-from-cache at $0 | **BUILT** | The "CI" in "CI for generated video" |
| MCP `run_shot_tests` (gate video like you gate code) | **BUILT** | `server/mcp_server.py`, model-agnostic on any mp4 |
| "Conspicuous title in the *first 3 seconds*" | **ROADMAP** | Needs time-windowed frame selection (checks are whole-clip today) |
| "Brand mentioned N times in the *outro*" | **ROADMAP** | Needs audio/ASR (Wan is silent) + count semantics + an episode-level window |
| On-screen-text / logo detection (OCR) | **ROADMAP** | No OCR modality yet |

The roadmap rows are real user demand, named honestly as roadmap — the modality expansions
(audio/ASR, OCR, time-windowing, episode-level assertions) are the next build, not a claim.

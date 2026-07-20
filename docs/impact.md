# Problem Value & Impact

*Why Dailies exists, who pays for it, and how it scales — the strategic case behind "CI for AI-generated video."*

## The pain (authentic, and already attested in this repo)

Picture the clip that shipped wrong. The camera drifts left when the brief said pan right. A
take flickers. The brand blue comes back a little off. The hero's face changes between the first
shot and the third. The title card never appears. The five-second beat runs to seven — and
nobody catches it until it's live, because the one person who reviews every clip was asleep, on
vacation, or three hundred clips behind. AI video fails *in motion*, after you've already paid
for it, and today the only safety net is a human eyeball. Every failure in that list is
something the engine actually checks: camera motion, flicker, brand-palette ΔE, character
continuity, a visible title card, duration bounds.

Behind that felt failure is an organizational one. Every team that adopts AI video has quietly
appointed a **human test suite**: one person who eyeballs each generated clip for brand palette,
length, flicker, character continuity, and whether the brief was actually followed. That person is the bottleneck for everyone upstream
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

## The thesis, measured (twice)

"Existing tools maximize output; **nobody tests the product**" is a falsifiable claim, so we
tested it two ways rather than leaning on it as rhetoric.

**Simulated field (2026-07-15).** We ran 15 independent LLM brainstorms over this track's
public brief — two model families, 14 personas, each seeing only the brief and the rubric
weights, none seeing this repo or each other; ~150 ideas in total. **All 15 produced a
premise-in, episode-out generator. Zero produced a way to check whether the episode came out
right** — no assertion grammar, no deterministic check tier, no gate that could judge a
pipeline it doesn't own. Two brainstorms even emitted the "CI for AI-generated video" phrase
verbatim, and both still attached it to a generator; one listed a continuity-QA service and a
budget-aware render router as *separate, unconnected ideas in the same list of ten*. The mode
contains the pitch. It does not contain the architecture.

**Observed field (2026-07-18).** Two days before the deadline we read the eight most
substantial shipped entries in this track's public GitHub field. Every one routes its quality
checks through a token-billed model call; six of the eight import no computer-vision library
at all (verified by grep); none ships a closed assertion vocabulary; none can gate a video it
didn't generate. One even ships a review stage named "dailies" — switched off by default, for
speed (the config line quoted in the README's "Why Dailies").

The pain described above predicts exactly this shape of field. These two measurements are
that prediction, counted.

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
test suite gets more valuable — not less.

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

So the defensible seat is scope, not a slogan: **Dailies tests the video whoever's model made
it** — which is the seat for every team generating *outside* one vendor's walled garden.
Honest concession:
*inside Adobe's stack, on Adobe's models, Adobe wins.* Our wedge is the multi-model shop.

And the distribution is **adoption-led, not platform-locked** — which is the deeper reason a
well-resourced incumbent can't just absorb this. The wedge is a *protocol*, not a product
surface: Dailies ships as an **MCP server** (`server/mcp_server.py`), the same primitive coding
agents already speak, so a team adopts the gate by pointing an agent it already runs at
`run_shot_tests` — no migration, no platform. And because the checks read frames, not generator
internals, the gate is **model-agnostic by construction**: one gate covers Wan today and whatever
model a shop adds next. An incumbent's advantage is its walled stack; ours is that we require
none. Adoption flows through the protocol — model by model, shop by shop — exactly where a
platform-locked add-on can't reach.

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

## Productization path — the OSS sequence (project → product → value)

The criterion rewards a credible path over present revenue, and the honest way to state one is
the open-source progression a16z describes: **project-community fit → product-market fit →
value-market fit**, in that order, with monetization as a *later* stage gated on traction — not
a number we claim today. Dailies' architecture makes each stage concrete because **assertion
packs are data, not code** (`packs/*.yaml`) and the engine has no generator coupling.

- **Stage 1 — project-community fit (now).** The asset is a runnable, model-agnostic conformance
  engine a developer adopts in minutes; it lifts out of `server/specs.py`, `server/tier_a.py`,
  and `server/compiler.py` as a standalone package (deterministic checks run on any mp4). Traction
  here is **stars, forks, and PRs** against the vocabulary and packs — community signal, not revenue.
- **Stage 2 — product-market fit (next).** As packs-as-data and the MCP tool get dropped into real
  CI as **regression tests for generated video**, the signal becomes **usage** — installs,
  `run_shot_tests` calls, packs authored. Still adoption depth, still not revenue.
- **Stage 3 — value-market fit (later, gated).** Only once usage is real does monetization make
  sense — a hosted gate, the human-override calibration corpus as a tuned managed service, team
  seats. We name this as a *later* stage on purpose: claiming revenue now would be dishonest, and
  the rubric does not ask for it.

### The hackathon-stage traction substitute

Stars and downloads don't exist yet, so the credible stand-in is a **productization surface you
can run right now**. `run_shot_tests` is exposed as a console-script entry point
(`[project.scripts]` in `pyproject.toml` → `dailies-mcp = "server.mcp_server:main"`), so the MCP
server is **runnable as a package** without cloning internals:

```bash
uvx --from '.[mcp]' dailies-mcp        # or: pipx run --spec '.[mcp]' dailies-mcp
```

(Runnable as a package — **not** published to PyPI yet.) That an outside agent can install the gate
and check video against an authored spec in one command is the honest substitute for community
traction at this stage: the distribution mechanism exists and works, ahead of the audience that
will use it.

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

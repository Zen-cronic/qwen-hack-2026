# ClipCrew → Dailies build plan — Jul 5–9, 2026

Deadline: **Jul 9, 2:00pm PDT** (submit by ~10:00am PDT — Alibaba's own X post said "Jul 8"; ambiguity = buffer).
Demo video is a first-class deliverable, not an afterthought.

> ⚠️ **Jul 15 DEADLINE CORRECTION:** the organizer's page reads **Jul 20, 2:00pm PDT** — the
> Jul 9 date above was the pre-correction reading. Submit target: **Jul 20, ~10:00am PDT**.

## Current state — Jul 18 (T-2)

**Shipped since the Jul 15 panel** (each item closes a recorded panel deduction or red-team action):
- Tier-0 still screen wired into every runtime path — it was billed but never evaluated (`7a5a374`)
- First real end-to-end run on Wan clips; the four bugs synthetic clips hid, found and fixed (`93c2603`, log in docs/verification.md)
- `check_duration`: unreadable clip → INCONCLUSIVE, not a fake 0.00s FAIL (`edf0572`)
- `palette_deltae`: true CIE ΔE*76 via the float Lab path — was 2.55×-lightness distance (`07d83b7`)
- CI test job — the CI-branded repo now runs its own suite, keyless (`affbc04`)
- README wedge rewritten shape-not-primacy + the cited market survey published (`31caca4`, docs/market-landscape.md)
- Impact doc carries both adversarial measurements: 15/15 probe + 0/8 observed field (`39757db`)
- Prompt-to-episode UX pass: sample premises, live stage captions, informed review gate, shareable final cut (`dc0d147`)
- Playwright e2e over the demo runtime — full journey + #16/repair-loop regressions pinned; `npm run e2e` (`e1571d7`)
- Frontier charts per-shot PRODUCTION cost (billed + cache-replayed), so the warm judge-mode re-run no longer collapses to one dot at $0; wallet still bills zero (`9309a54`)
- Media route served thumbnails only under the default DATA_DIR — every still 404'd in e2e/scratch runs; contract fixed + regression tests (`1365035`)
- Judged-surface polish: favicon, wedge in tab/header, honest empty states, nginx no-store on index.html, fresh screenshots embedded in README (`a6e8962`)

**Remaining before submit (operator-owned unless noted):**
- G4 green deploy — root cause diagnosed Jul 18: **zero GitHub secrets exist**; all three failures are
  `Error: missing server host` at ~5s. Fix = runbook "Setup, in order" step 2 (`SERVER_HOST`,
  `SERVER_USER`, `SERVER_SSH_KEY`), then re-run the workflow. The YAML itself is fine.
- G1 flip repo public · G2 Workbench screenshot · G3 live URL (G2/G3 follow from a green G4)
- Demo video (< 3 min, run-of-show in docs/demo.md) — the one mandatory deliverable with no draft
- Final pass: SUBMISSION.md checklist top to bottom on submit morning, each box re-verified by command

> ⚠️ **Jul 6 PIVOT:** the product is now **Dailies — CI for generated video**. Everything from the "Jul 6" section down is SUPERSEDED by [Pivot (Jul 6): Dailies](#pivot-jul-6-dailies--ci-for-generated-video) at the end of this file. The Jul 5 verify-or-abort results (quota, Wan API lifecycle) remain valid and load-bearing.

## Jul 5 (tonight) — verify-or-abort + bank eligibility deliverables
- [x] `python scripts/verify_quota.py` — Qwen API smoke test on free tier (1M tokens, no card needed) *(passed Jul 6: qwen-plus via dashscope-intl, usage reporting works)*
- [x] Confirm Wan / HappyHorse video-gen access + quota. **ABORT RULE: if quota can't cover ~a dozen generation cycles → pivot to DataCrew (Track 3) or skip.** Don't wait on the $40 voucher queue (multi-day delays reported). *(PASS Jul 6: 600s video quota across models — turbo alone covers 40 clips vs ~12 needed. Endpoint + task lifecycle verified live — evidence in docs/verification.md, constants in server/wan.py)*
- [ ] Capture **Alibaba Cloud Workbench screenshot** showing running SAS resources ("No proof = not eligible")
- [ ] Create public GitHub repo, push scaffold, confirm MIT license badge is visible at top of repo page

## Jul 6 (Mon eve) — pipeline spine  ⚠️ SlackHack submission-audit also due today
- [ ] Script agent (premise → scenes) on Qwen chat completions
- [ ] Storyboard agent (scenes → shot-list with prompts)
- [ ] ONE Wan shot generated end-to-end
- [ ] Metrics ledger records tokens/cost/latency from the very first call

## Jul 7 (Tue eve) — full pipeline
- [ ] Multi-shot generation loop with retry policy
- [ ] ffmpeg assembly (shots → cut)
- [ ] Human-in-the-loop checkpoint at storyboard stage
- [ ] Cost-quality dashboard chart (per-shot spend vs quality rating)

## Jul 8 (Wed eve) — polish + deliverables
- [ ] Demo video <3 min, real screencast, public on YouTube/Vimeo/Youku — use ClipCrew's own output inside the demo
- [ ] Architecture diagram (Qwen Cloud ↔ backend ↔ storage ↔ dashboard)
- [ ] Blog post (~2 hrs) — stacked $500×10 prize, "journey building with QwenCloud"
- [ ] Devpost form fully drafted (track identified, testing access link, description)

## Jul 9 (Thu AM) — submit
- [ ] Final checks against SUBMISSION.md
- [ ] Submit by ~10:00am PDT

## Cross-hackathon guard
SlackHack (Jul 13) demo-video day is reserved Jul 10–11 and survives ONLY if this entry truly ends Jul 9. Any slip here eats SlackHack's video day. SlackHack submission-audit (was due Jul 6) → reschedule to Jul 7 daytime or explicitly accept the slip.

---

# Pivot (Jul 6): Dailies — CI for generated video

**Why:** design review displaced the "budget-governed showrunner" positioning on two flaws: the HITL keyframe gate approves a *still* as proxy for motion it never verifies, and a live demo URL burns real clips on every run Jul 10–31, so the demo degrades mid-window. Locked **Dailies**. **Designated pivot: Wanform** (Terraform-for-video) if the hour-zero qwen-vl smoke test fails AND Tier-A CV looks weak.

## Positioning & audience

**Pitch:** *Dailies is CI for AI-generated video — pytest for video shots. Write your shot contract once; no clip that violates it costs premium tokens or ships to your brand channel.*

- **Primary (demo + Impact story):** marketing/social teams running unattended AI-video batch — brand rules as assertions; the QC gate is what makes unattended generation deployable (attested day-job pain: one-person social team).
- **Secondary (OSS path):** devs building on video-gen APIs — assertion packs as regression tests in CI; model-agnostic, outlives Wan.
- **Tertiary (theme fit):** AI drama studios — the certified episode IS the track's "short drama creation pipeline".
- **Prior-art improvement statement (say it before judges do):** Genflow Ad Studio (arXiv 2605.16748) / VideoRepair = unshipped research on VLM-critique loops; VBench grades *models* on benchmark suites, not *your shots* against *your spec*; LTX Studio locks storyboards on the authoring side but never verifies rendered output. Dailies is the only standalone, model-agnostic per-shot conformance gate — claim rewritten Jul 18 from "first shipped" (which a 2026-07-14 market survey falsified via OpenMontage/Kinocut) to shape-not-primacy; the cited survey is docs/market-landscape.md.

## Demo (<3 min, target 2:45 — "real working app", no third-party IP)

Recorded off cached artifacts; the planted kill-shot is pre-validated from hero run #1 (never gamble on live generation while recording).

| time | beat | on screen |
|---|---|---|
| 0:00–0:20 | Kill-shot cold open | Gorgeous keyframe ("this passed review") → the 5s clip it became: camera pans the WRONG way → red row: `camera_motion: FAIL — pans left, spec requires right`. VO: "AI video fails in motion — after you've paid for it. Nobody's testing the product." |
| 0:20–0:40 | Name + claim | "Dailies is CI for AI-generated video." Shot-contract YAML; 3-tier cascade diagram with costs (stills = 1/25th of video, CV = free, VLM = tokens only). |
| 0:40–1:45 | Pipeline run | Premise → specs + compiled assertion checklist → Tier-0 still kills a doomed prompt cheap → **the one human gate** (approve specs, spend video budget) → drafts render, wallet meter ticking → conformance board: planted failure caught by Tier A → repair prompt-delta → retake passes → certified shots auto-promote to `wan2.2-plus`. |
| 1:45–2:15 | The measurements | Assertion pass-rate heatmap ("an empirical capability map of wan2.1-turbo"), image→video transfer rate, repair convergence, cost-per-passing-second. "Profiling isn't a chart we added — it's what the pipeline is." |
| 2:15–2:35 | Certified episode + audience flip | Assembled drama plays, "certified 5/6 shots" → dropdown flip to `brand_rules` pack: "same harness, my employer's brand rules — how a one-person social team ships unattended AI video." |
| 2:35–2:45 | Close | Architecture diagram → live Alibaba Cloud URL ("re-verifies any cached clip at zero video cost — try it") → GitHub + MIT + "pytest for video prompts". |

## Architecture (graft onto the locked chassis)

**Chassis (unchanged):** FastAPI, Python 3.12+, single uvicorn worker; pipeline in `threading.Thread`; in-memory Store + lock + atomic JSON snapshots to `data/projects/{id}/state.json`; SPA polls `GET /api/projects/{id}` every 2.5s (no SSE); React+Vite+TS + Recharts, dark cutting-room CSS; ONE multi-stage Dockerfile (`spa` node:22-alpine → `app` python:3.12-slim+ffmpeg → `web` nginx+dist); compose = `app` (mem_limit 3g, `./data:/data`) + `web` (80:80); deploy = git clone + `docker compose up -d --build` on the SAS box (fallback `docker save | ssh docker load`); replay cache `data/cache/{sha1(model+prompt+seed)}`.

**Dailies modules (`server/`):**
- `specs.py` — pydantic ShotSpec/Assertion/AssertionResult; **closed vocabulary, exactly 10 assertion types** (compiler rejects invented ones): `duration_between`, `brightness_range`, `flicker_below`, `scene_cuts`, `camera_motion`, `palette_deltae` (Tier A) · `subject_present` (Tier 0 — on the still, NOT Tier B: "0/B" is how it fell between two tiers and got evaluated by neither, see docs/verification.md §5) · `identity_consistent`, `action_completed`, `title_card_present` (Tier B, advisory).
- `compiler.py` — pack YAML defaults + LLM dynamic assertions → validated per-shot lists.
- `tier0.py` — 1 t2i still/shot (`wan2.1-t2i-plus`) + a qwen-vl `subject_present` verdict on that still BEFORE any video spend (~325 tokens/shot; the still is downscaled to 512px first, or the pre-screen costs more than the Tier-B batch it exists to avoid). The verdict is evidence at the human gate, not an automatic block.
- `tier_a.py` — **never-cut spine, zero tokens**: ffmpeg `fps=8,scale=320` frames → Farneback optical flow (camera direction = −content flow; synthetic-shift unit test), flicker std, HSV-hist scene cuts, k-means palette ΔE, ffprobe duration.
- `tier_b.py` — qwen-vl JSON verdicts on 7 strided frames; **gated on hour-zero smoke test**; NO-GO ⇒ compiles to `inconclusive` + human verdict buttons.
- `repair.py` — qwen-plus prompt delta from failing assertions; max 1 retake/shot on draft tier.
- `packs/short_drama.yaml`, `packs/brand_rules.yaml` — presets are data, not code (the audience flip).
- `wan.py` extended for t2i; ledger/wallet in `metrics.py`; judge caps in `budget.py`.
- New deps: `fastapi`, `uvicorn[standard]`, `httpx`, `opencv-python-headless`, `numpy`, `pyyaml`.

**State flow:** `queued → scripting → tier0 → awaiting_review` [threading.Event — the ONLY human gate, pre-video-spend] `→ drafting → verifying → repairing → promoting → assembling → done|failed`. Promotion to `wan2.2-plus` automatic up to `final_cap=4`. Verdict overrides never block.

**Routes:** `POST /api/projects {premise, pack, max_shots}` · `GET /api/projects/{id}` (poll payload IS the conformance report: wallet + per-shot takes/assertion results/evidence frames + heatmap/transfer/repair/frontier metrics + episode) · `POST .../review` · `POST .../verdict` · `POST .../assemble` (free re-concat) · `GET /api/packs` · `GET /api/wallet` · `GET /api/media/...`.

**Judge mode (`JUDGE_MODE=1`):** per-session fresh-clip caps (2 drafts) enforced by the governor; cached-clip re-verification bypasses caps — **zero video quota**; wallet meter shows it all.

**Frontend:** `ConformanceBoard`/`ShotCard` (assertion checklist, tier badges, evidence lightbox, take tabs) · `ReviewBar` · `VerdictButtons` · `WalletMeter` (persistent) · `ChartsPanel` (heatmap as stacked bars, stat tiles, frontier scatter = first cut) · `FinalCut`.

**Hour-zero probes (before anything else):** `scripts/smoke_vl.py` — qwen-vl via BOTH shapes (OpenAI-compatible `image_url` parts; native `multimodal-generation` endpoint) × models (qwen-vl-plus/max), brightness-pair test → GO pins `VL_MODEL`/`VL_SHAPE` in `.env`; NO-GO wires the human-verdict fallback. `scripts/probe_models.py` — zero-cost invalid-request probe of the t2i endpoint, then 1 real still.

## Task list (~11.5h vs 17–19h honest — cut-lines are load-bearing)

**Tonight Jul 6 (~2.5h)**
- [ ] (20m) Hygiene: `.gitignore` (`.env`, `data/`…) **BEFORE `git init`** → verify `git status` omits `.env` → first commit → public GitHub repo **`dailies`** → MIT chip visible in About. Fix `pyproject.toml` (`packages.find` → `"server*"`, add deps, delete `poetry.lock`). Reconcile `.env.example` to verified roster. Write `docs/hackathon.md` (all source links).
- [ ] (40m) `smoke_vl.py` + `probe_models.py`, run, log in `docs/verification.md` → **Tier-B GO/NO-GO decided tonight**.
- [ ] (60m) `specs.py` + `metrics.py` (LedgerEntry+wallet) + `store.py` + `packs/short_drama.yaml`.
- [ ] (30m) `wan.py` cache + t2i (slip-allowed → Jul 7).

**Jul 7 (~5h)**
- [ ] (90m) Pipeline thread: `script_and_specs` (one qwen-plus JSON call) → compiler → tier0 → review Event → draft loop.
- [ ] (75m) `tier_a.py` all 6 checks + evidence frames + synthetic-shift flow test (zero quota).
- [ ] (45m) `tier_b.py` if GO; else NO-GO wiring only.
- [ ] (60m) `repair.py` + promote (Tier-A re-verify on finals — free) + ffmpeg assemble.
- [ ] (30m) `app.py` routes + report serialization → **kick hero run #1 via curl** (generation overlaps).

**Jul 8 (~4h)**
- [ ] (100m) Frontend: board/card/review/wallet + stacked-bar heatmap + stat tiles.
- [ ] (45m) Dockerfile + compose up on SAS + rsync `data/cache/` + **Workbench screenshot** (eligibility!).
- [ ] (30m) Hero run #2 on deployed box incl. planted kill-shot (pre-validated from run #1 cache).
- [ ] (75m) Demo video <3min off cached artifacts + redraw `docs/architecture.md` (fix Python 3.11→3.12).
- [ ] Devpost form + blog draft → **Jul 9 AM: final checks vs SUBMISSION.md, submit ~10:00am PDT.**

**Cut-line order (drop top-first):** 1 frontier scatter → 2 retake-diff styling → 3 Tier-B integration even on GO (verdict buttons carry it; kill-shot is Tier A) → 4 Tier-0 stills (most expensive cut: loses the 1/25th-cost beat + transfer metric) → 5 `brand_rules.yaml`. **Never cut:** Tier A, repair loop, planted kill-shot, wallet meter, deploy, demo video.

## Quota ledger (hard caps: pre-demo drafts ≤24/40, finals ≤7/10)

| activity | drafts | finals | images | tokens |
|---|---|---|---|---|
| Hour-zero probes | 0 | 0 | 1 | ~2k |
| Dev smoke (1 e2e + promote path) | 3 | 1 | 4 | ~10k |
| Hero run #1 (6 shots + ≤3 retakes, `final_cap=4`) | 9 | 4 | 12 | ~80k |
| Hero run #2 on deploy (cache-seeded + planted failure) | 5 | 0 | 6 | ~40k |
| Demo-recording spare | 0 | 1 | 2 | ~10k |
| **Pre-demo total** | **17** | **6** | **25** | **~140k** |
| Judge reserve (Jul 10–31; judge mode 2 fresh/session, replays free) | 23 | 4 | ~475 | ~860k |

## Productization surface (MCP)
`server/mcp_server.py` ships the **`run_shot_tests`** tool now (deterministic Tier-A, zero-token, any mp4 — install with `pip install -e ".[mcp]"`), proving the packs-as-data path. `compile_shot` / `get_conformance_report` remain roadmap.

## Post-deadline (fork only — repo freezes at submission boundary)
`compile_shot` / `get_conformance_report` MCP tools, CosyVoice TTS, Wanform-style plan/apply layer, day-job brand packs — all in a clean fork per FAQ rule.

## UI overhaul — Jul 18 (T-2): production-SaaS structure, cutting-room identity

The SPA reads as an ops dashboard; shipped chat-to-video products read as products. Two
structural patterns from the market survey are worth adopting — the prompt-box-as-hero
(ngram: one big prompt card with the controls inside it, starting-point pills, the
subject's vernacular as faint background texture) and staged progressive disclosure
(one surveyed showrunner: a five-word phase stepper with a single active pill and a quiet
mono status caption; content mounts only once it has data). Their *skin* (light candy
gradients) is exactly the field-default look, so the dark cutting-room identity stays.

**Decisions:** keep `theme.ts` tokens/status colors/mono conceit; adopt structure only.
Fonts become real and self-hosted (`@fontsource-variable/instrument-sans` +
`@fontsource/ibm-plex-mono` — zero external requests from the built page). Signature
element: an ambient assertion-DSL field behind the hero (the actual closed vocabulary as
faint mono texture — honest, and only possible with a DSL).

**The three acts, by run status:**
1. *Hero* — display headline ("Turn a premise into a certified episode."), one prompt
   card (premise + pack + shots + collapsible custom checks + CTA), sample-premise pills.
2. *Run* — 10 internal stages grouped into 5 phase pills (Script · Stills · Review ·
   Takes · Cut), active pill pulsing, existing per-stage captions beneath in mono; at
   `awaiting_review` the gate is the dominant panel; charts stay unmounted until they
   carry data (the e2e only queries charts after the final cut — verified safe).
3. *Done* — unchanged order (tiles/charts → board → certified episode) + mono footer
   naming the model roster on Alibaba Cloud.

**Steps (one commit each):** fonts foundation → hero → run-view acts + chart gating →
refreshed README screenshots → *gated stretch:* `server/demo.py` designed slate clips
(vertical two-tone gradient for pan-invariant luma + seeded grain so Farneback still
reads the pan + label baked into the panning texture; version-salt `_DemoGen._key` so
stale caches can't serve old clips). Every e2e testid keeps identical semantics;
custom-checks stays default-expanded (the e2e fills it). Verify per commit: pytest,
`tsc --noEmit`, `vite build` (+ grep dist CSS for external URLs), Playwright e2e,
`e2e:shots` + eyeball both PNGs.

## Node-graph pipeline editor — Jul 19 (T-1): agent-authored verification graph

A visual differentiator layered on the shipped chassis: the pipeline becomes a **node graph
a Qwen agent wires up**, where every node is a real capability we built — a deterministic CV
check, a VLM verdict, the human review gate, a repair, an assemble. The chat-to-video
generators in the market survey own "prompt in, clip out"; none exposes a verification/CI
graph, so this is uncopyable by a pure generator. Maps onto Innovation (30%) +
Technical-Depth (30%). Feasibility: a React-Flow graph over the *existing* pipeline (reuses
the whole chassis, no GPU, no new executor).

**Decisions (with operator):**
1. **Hero canvas, existing panels kept mounted below** — the graph and the e2e-covered flow
   coexist, so all `data-testid`s and both Playwright tests stay green.
2. **The agent wires the graph** — a request → Qwen tool-call → the pipeline materializes
   node-by-node → runs live. This is the headline demo moment.

**Load-bearing principle — the graph drives and visualizes the existing `Pipeline`, it never
replaces it.** A from-scratch DAG executor would have to re-host what `Pipeline` owns beyond
the bare stages (ledger/spend accounting, evidence dirs, the review `Event`, the draft→final
promotion fallback) — and the e2e asserts on that accounting (`wallet`, `metrics.frontier`).
Two choices keep it safe:
- **The agent emits run *parameters*, not graph topology.** The tool `build_pipeline_graph`
  takes only `{premise, pack, max_shots, custom_checks}`; the *server* deterministically
  expands them into the canonical layout. The model cannot emit a malformed graph because it
  never emits a graph — the standard "LLM hallucinates the graph" integration risk is gone by
  construction, while "the agent authored the pipeline" stays fully truthful.
- **One canonical id scheme** (`script, stills, review, gen-{i}, check-{i}, assemble,
  episode`) shared by the server expander and the client deriver, so the pre-run canvas (from
  the plan) and the running canvas (from the 2.5s poll) are the *same nodes* — live status
  merges in. No SSE on the critical path.

Zero-quota demo preserved: stages already inherit demo-mode + cache via injected `Deps`
(synthetic gens + real CV + real ffmpeg); the agent planner is stubbed deterministically when
`DAILIES_DEMO` (real qwen-plus otherwise) — the whole demo, agent authoring included, spends
no video/image quota.

**Canonical graph:**
```
script -> stills -> review -+- gen-0 -> check-0 -+
                            +- gen-1 -> check-1 -+-> assemble -> episode
                            +- gen-2 -> check-2 -+
```
Node status derives from `Project` (client-side, pure): script done once shots exist · stills
done once every shot has tier0 results · review active at `awaiting_review` (amber) · gen-{i}
from shot/take status (model + first-evidence-frame thumb) · check-{i} from take results
(Tier-A/Tier-B pass/fail/inconclusive chips) · assemble at `assembling` · episode when
`episode_path` is set.

**Steps — a fallback ladder, each tier independently demoable (Tier 1 alone yields a live
canvas):**
- **Tier 1 (live graph view, no backend, e2e-safe — ship first):** add `@xyflow/react`
  (**commit the lockfile** — Docker `npm ci`); `web/src/graph.ts` (derive nodes/edges from
  `Project`); `web/src/nodes.tsx` (custom nodes on `theme.ts` tokens); `web/src/
  PipelineGraph.tsx` (`data-testid="graph"`); mount as hero in `App.tsx`, existing panels
  kept below unchanged.
- **Tier 2 (agent authoring — headline):** `server/agent_plan.py` (Pydantic `PipelinePlan` +
  `expand_plan` + a `build_pipeline_graph` tool-call loop mirroring
  `qwen_tools.py:call_with_function_calling`, demo-stubbed); `POST /api/agent/plan`;
  `AgentPrompt.tsx` (node-by-node reveal → existing `onCreate`), kept *above* the existing
  `NewProject` form so the current e2e path is untouched.
- **Tier 3 (tangible edit):** per-shot node "re-render" → existing `POST /shots/{i}/patch`;
  the tool-call transcript shown as judge-facing evidence.
- **Stretch:** SSE for sub-poll animation; an agent-path e2e test (deterministic via the demo
  stub); a Remotion `@remotion/player` preview node (free for a solo dev).

**Verify per tier:** pytest (existing 118 + new `agent_plan` units), `tsc --noEmit`, `vite
build` (+ grep dist CSS for external `url(https:` — React-Flow CSS is self-hosted), Playwright
e2e (both existing tests green), `e2e:shots` + eyeball. `git check-ignore .env`; a demo run
bills zero video seconds.

**Risks:** uncommitted lockfile breaking Docker `npm ci` (commit it in Tier 1) · a canvas
node intercepting clicks the e2e needs (the canvas sits above, not overlaying, the panels) ·
React-Flow CSS pulling a remote asset (the grep step catches it) · scope overrun (mitigated by
the tier ladder — Tier 1 alone demos).

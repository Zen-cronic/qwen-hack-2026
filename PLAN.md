# ClipCrew → Dailies build plan — Jul 5–9, 2026

Deadline: **Jul 9, 2:00pm PDT** (submit by ~10:00am PDT — Alibaba's own X post said "Jul 8"; ambiguity = buffer).
Demo video is a first-class deliverable, not an afterthought.

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
- **Prior-art improvement statement (say it before judges do):** Genflow Ad Studio (arXiv 2605.16748) / VideoRepair = unshipped research on VLM-critique loops; VBench grades *models* on benchmark suites, not *your shots* against *your spec*; LTX Studio locks storyboards on the authoring side but never verifies rendered output. Dailies is the first shipped per-shot conformance harness with a cost-tiered cascade and budget-bounded auto-repair.

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

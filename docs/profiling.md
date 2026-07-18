# Performance profiling — per-tier cost & latency

The Technical-Depth axis names "performance profiling" explicitly. This is that artifact:
where a batch's spend actually goes, why the cascade is ordered the way it is, and what the
metrics ledger (`server/metrics.py`) measures at runtime. Every number below is labelled
**measured (demo run)** or **modeled (cost design)** — we never present a list-price estimate
as a benchmark.

## Methodology & honesty

- **Measured (demo run)** numbers come from running the *real* pipeline
  (`server/pipeline.py` — the real cost-tiered cascade, the real ledger, the real bounded
  repair loop) over demo-mode fakes at **zero video quota**. The generators are synthetic, but
  the orchestration, the ledger, the reject-before-spend gate, and the repair convergence are
  the production code path. Reproduce with `~/.pyenv/versions/.qwen-hack/bin/python
  scripts/profile_demo.py` (or run the workbench under `DAILIES_DEMO=1` and read
  `data/demo/ledger.jsonl` + `state.json`).
- **Modeled (cost design)** numbers are structural: model tiers, free-tier ratios, and the
  nominal list prices in `server/metrics.py` (`_PRICE_PER_*`). They describe the *shape* of
  cost, not a cash benchmark.
- **What we do NOT measure:** absolute model latency and dollars. The demo returns fixed
  synthetic clips, so per-call model latency is not real and is omitted. The one wall-clock
  measurement we *can* honestly make is the deterministic Tier-A CV stage, which runs the same
  on real and synthetic mp4s — reported below.

## The cost hierarchy (modeled — cost design)

The cascade is deliberately ordered cheapest-and-most-certain first, so the expensive,
probabilistic work only runs on candidates the cheap deterministic work already blessed.

| Tier / stage | Model | Cost basis | When it runs | Class |
|---|---|---|---|---|
| Tier-0 still | `wan2.1-t2i-plus` | ~**1/25** of a 5s draft ($0.02 vs $0.50) | once per shot, **before any video spend** | modeled |
| Tier-0 subject check | `qwen-vl-plus` | **325 in / ~32 out** tokens per shot | on that still, **before any video spend** | measured |
| Human gate | — | zero compute (a `threading.Event`) | once per batch, pre-video | — |
| Draft | `wan2.1-t2v-turbo` | free tier **40 × 5s**; list $0.10/s | per take (incl. retakes) | modeled |
| **Tier-A CV** | OpenCV | **ZERO tokens**; ~0.3s CPU/clip | **every take** (drafts + finals) | measured |
| Tier-B VLM | `qwen-vl-plus` | advisory tokens (strided frames) | **drafts only**, never finals | modeled |
| Bounded auto-repair | `qwen-plus` | chat tokens | only on a blocking Tier-A FAIL | modeled |
| Final (promote) | `wan2.2-t2v-plus` | free tier **10 × 5s**; list $0.30/s | per certified shot, up to `final_cap` | modeled |

Two ratios are load-bearing and both are encoded in `server/metrics.py`: a Tier-0 still is
**1/25** the price of a 5s draft (`$0.02 / ($0.10 × 5)`), and a premium final second costs
**3×** a draft second (`$0.30 / $0.10`). Free-tier quota mirrors the intent — 40 cheap turbo
takes to iterate against, 10 premium plus finals to certify (`.env.example`).

The cascade only pays off if each rung is genuinely cheaper than the one it guards, and that
is a property you can get wrong by accident: the t2i models return 1024×1024, VLM image
tokens scale with pixel count, and a Tier-0 check on the full-res still would cost more than
the seven downscaled frames Tier-B sends for the *whole video* — a pre-screen more expensive
than the screen it precedes. `server/tier0.py` downscales to `STILL_WIDTH = 512` first, which
holds the measured cost at 325 tokens/shot (27% of the full-res payload). Measured both
directions on a real still — present subject PASS, absent subject FAIL — in
[verification §5.2](verification.md#52-live-measurement--qwen-vl-plus-on-a-real-cached-still).

## Measured (demo run) — one 3-shot batch

The default lighthouse premise, `short_drama` pack, 3 shots, run end-to-end. The ledger the
pipeline actually wrote:

| Stage / resource | Calls | Billed units | Runs |
|---|---|---|---|
| `scripting` / chat (`qwen-plus`) | 1 | 180 in + 60 out tokens | once per batch |
| `tier0` / image (`wan2.1-t2i-plus`) | 3 | 3 stills | once per shot, pre-video |
| `drafting` / video_draft (`wan2.1-t2v-turbo`) | 4 | 20 video-s | per take (1 was a retake) |
| `repairing` / chat (`qwen-plus`) | 1 | 90 in + 30 out tokens | per blocking failure |
| `promoting` / video_final (`wan2.2-t2v-plus`) | 3 | 15 video-s | per certified shot |

Batch totals (wallet): **4 draft clips, 3 finals, 3 stills, 360 tokens, 35 billed video-seconds**,
which the nominal list prices model at **~$6.56**. All 3 shots certified.

Read the `tier0` row precisely: demo mode substitutes a deterministic zero-token stand-in for
the subject check, so this batch bills 3 stills and no VLM tokens for that stage. It is not
evidence that Tier-0 checks are free — in real mode the same stage adds ~325 tokens/shot
(the row above). Demo mode exists to make the *control flow* free to re-run, and a number a
fake produced is not a measurement of the thing it replaces.

Note: in demo mode Tier-B runs offline (a deterministic stub), so the `verifying`/VLM token
line is **0** in this run. In production it logs `qwen-vl-plus` tokens — on **drafts only**.

## Tier-A vs Tier-B spend curve

This is the core cost design, and the measured batch makes it concrete:

- **Tier-A CV ran 31 check executions across the batch at zero tokens** — it re-runs on every
  draft *and* every promoted final because it is free to run. It never appears in the ledger's
  billed columns because there is nothing to meter.
- **Tier-B VLM ran 3 advisory check executions**, only on drafts, never on finals (by cost
  design — the final re-runs only the deterministic tier; see `docs/demo.md`).

So the deterministic, always-on tier absorbs the bulk of the verification volume for free, and
the token-metered VLM tier only touches draft candidates. The ledger (`server/metrics.py`)
tags every entry with `stage` + `kind`, so `server/report.py` derives the **cost–quality
frontier** (per-shot cost vs pass-rate), the **pass-rate heatmap** (per assertion type), and
**cost-per-passing-second** — all charted live in the dashboard (`web/src/charts.tsx`).

### Tier-A wall-clock (measured — deterministic CV)

The one honest latency number, timed over 25 iterations on a 5s synthetic clip (all six Tier-A
checks, including optical-flow camera motion and k-means palette ΔE):

| Checks | Median | Mean | Min–Max |
|---|---|---|---|
| 6 | ~317 ms | ~323 ms | 303–367 ms |

Zero tokens, machine-dependent CPU only (dominated by optical flow + k-means). This is why
Tier-A can run on **every** take without a budget conversation.

## Repair-loop convergence (measured — demo run)

Shot 2 is the planted kill-shot: it asserts a rightward camera pan, the first synthetic draft
is static, and the loop is expected to converge in one retake.

- Takes per shot: **[2, 3, 2]** — shot 2 has an extra draft (take 0 FAIL → take 1 PASS) plus
  its promoted final; the other two pass on the first draft.
- **1 shot repaired, 1 certified** — a single `repairing`/chat call (90 in + 30 out tokens)
  fed only the blocking Tier-A `camera_motion` failure back to `qwen-plus`, which convergence
  fixed on the next take.

The ledger's per-shot `repairing` entries plus each take's pass/fail are exactly what the
dashboard's **repair-convergence** view reads.

## Re-verify from cache (measured — demo run)

Re-running the *identical* spec against the content-addressed cache:

| | Cold run | Warm run (cache hits) |
|---|---|---|
| Billed video-seconds | 35 | **0** |
| Modeled list cost | ~$6.56 | **~$0.0002** (residual chat tokens only) |
| Shots certified | 3 | 3 |

Identical `(model, prompt, seed)` requests replay from disk with `video_seconds = 0`, so the
whole video bill collapses to zero on re-verification. This is the mechanism that lets the live
demo URL survive the judging window at no video quota — the same certification, re-run for free.

One honest bookkeeping consequence: the ledger records both numbers. `video_seconds` is what
*this run* billed (0 on replays — the wallet's number above), and `cached_seconds` is what a
replay *represents* (billed on a prior run). The dashboard's frontier charts the second —
per-shot **production** cost — because on a warm run the first is uniformly zero and a chart of
it says nothing; the replay is disclosed in a caption under the chart.

## Reproduce

```bash
# Measured numbers above (real pipeline + ledger, zero quota):
~/.pyenv/versions/.qwen-hack/bin/python scripts/profile_demo.py

# Or run the workbench in demo mode and read the ledger it writes:
DAILIES_DEMO=1 SPA_DIST=web/dist uvicorn server.app:create_production_app --factory --port 8099
#   -> data/demo/ledger.jsonl   (append-only spend audit)
#   -> data/demo/projects/<id>/state.json   (per-take results)
```

Prices are the nominal list-price constants in `server/metrics.py`; the hackathon runs on
free-tier quota where cash cost is $0 and quota *units* (clips, images, tokens) are what the
wallet rations.

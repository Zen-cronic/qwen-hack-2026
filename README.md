# ClipCrew

A token-budgeted short-drama pipeline agent, built on Qwen Cloud for the Global AI Hackathon Series (Track 2 — AI Showrunner).

ClipCrew takes a one-line premise and autonomously runs the full short-drama pipeline — script → storyboard/shot-list → video generation (Wan) → edit/assembly — with a human-in-the-loop checkpoint at the storyboard stage.

## What's new here (novelty statement)

Agentic video pipelines exist (ViMax, OpenMontage, Open-AI-Micro-Drama-Generator, Toonflow). ClipCrew's improvement is that it treats the **cost-quality frontier as a first-class, measured feature**:

- Every pipeline step logs per-call token spend and latency to a metrics ledger.
- Each generated shot gets a quality rating; the retry/upscale policy is tuned against the measured cost-quality curve, not vibes.
- The dashboard shows exactly what a minute of finished video costs — and where the next token is best spent.

Existing tools maximize output; ClipCrew maximizes output **under an explicit token budget** — which is also Track 2's stated judging constraint.

## Architecture

See [docs/architecture.md](docs/architecture.md) (diagram is a required submission deliverable).

Backend runs on Alibaba Cloud (SAS). Qwen models are called via the Qwen Cloud OpenAI-compatible endpoint (`dashscope-intl.aliyuncs.com/compatible-mode/v1`).

## Setup

```bash
cp .env.example .env    # add your QWEN_API_KEY
pip install -e .
python scripts/verify_quota.py   # day-1 gate: API access + video-gen quota
```

System dependency: `ffmpeg` (assembly step).

## Status

Hackathon build, Jul 5–9 2026. See PLAN.md for the day-by-day schedule and SUBMISSION.md for the deliverables checklist.

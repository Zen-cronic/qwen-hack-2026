# Dailies architecture

> A rendered version of this is a REQUIRED submission deliverable: "how Qwen Cloud connects to your backend, database, and frontend."

## Pipeline & data flow

```
  ┌───────────────────────────┐         ┌──────────────────────────────────────────┐
  │  Frontend (React+Vite+TS) │         │              Qwen Cloud                    │
  │  nginx :80 serves SPA     │         │  compatible-mode/v1 :  qwen-plus (chat)    │
  │  polls GET /api/... 2.5s  │         │                        qwen-vl-plus (VLM)  │
  └────────────┬──────────────┘         │  api/v1 async tasks :  wan2.1-t2v-turbo    │
               │ /api  (nginx proxy)    │                        wan2.2-t2v-plus     │
               ▼                        │                        wan2.1-t2i-plus     │
  ┌───────────────────────────┐         └───────────────▲──────────────────────────┘
  │  Backend — FastAPI (app)  │                         │ OpenAI-compat + native REST
  │  uvicorn :8099            │─────────────────────────┘
  │                           │
  │  POST /api/projects  ─────┼──► pipeline thread (state machine):
  │  GET  /api/projects/{id}  │      script+specs ─ compiler ─ tier0 still
  │  POST .../review          │        └─[review gate: threading.Event]─┐
  │  POST .../verdict         │                                         ▼
  │  POST .../assemble        │      draft ─ Tier-A CV (opencv, 0 tok) + Tier-B VLM
  │  GET  /api/wallet /packs  │        └─ repair (qwen-plus) ─ promote ─ ffmpeg assemble
  │  GET  /api/media/...      │
  │  budget governor (judge)  │      every call ─► metrics ledger (cost-quality frontier)
  └────────────┬──────────────┘
               │ atomic snapshots + content-addressed media cache
               ▼
  ┌───────────────────────────────────────────────────────────┐
  │  Storage — local volume /data (bind-mounted, rsync-seeded) │
  │  data/cache/{sha1}.mp4|.png   ← replay cache = free reverify│
  │  data/projects/{id}/state.json ← atomic run snapshots      │
  │  data/ledger.jsonl             ← append-only spend audit   │
  └───────────────────────────────────────────────────────────┘
```

The **in-memory `Store` + atomic JSON snapshots** are the "database": a single background
pipeline thread mutates a project's state under a lock and writes an atomic snapshot after
each change; the SPA polls a deep-copied read every 2.5s, so a poll never observes a
half-written state. The **content-addressed cache** is the persistence that matters for
judging — identical (model, prompt, seed) requests return the cached file for free.

## Deployment topology (Alibaba Cloud SAS)

```
  Alibaba Cloud SAS instance (Canada region, Python 3.12)
  └── docker compose  (one multi-stage Dockerfile)
        ├── web  : nginx:alpine  — serves web/dist, proxies /api  →  :80 (public)
        └── app  : python:3.12-slim + ffmpeg — uvicorn --factory  →  :8099 (internal)
              volume ./data:/data   (cache + state persist across restarts)
              JUDGE_MODE=1          (fresh-clip cap; cached replays free)
```

Proof-of-deployment: the sanctioned Qwen Cloud base URL is visible in code
(`.env.example`, `server/wan.py`, `server/app.py`), plus the Alibaba Cloud Workbench
screenshot showing running resources. Backend compute runs on the SAS box, not just API
calls from elsewhere.

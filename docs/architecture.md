# ClipCrew architecture

> A rendered diagram of this is a REQUIRED submission deliverable: "how Qwen Cloud connects to your backend, database, and frontend". Draw it Jul 8 (PLAN.md).

```
premise
   │
   ▼
script agent ──────────► Qwen Cloud (chat, dashscope-intl compatible-mode)
   │
   ▼
storyboard agent ──────► Qwen Cloud (chat)
   │
   ▼
HITL checkpoint  ◄────── human approves shot-list before video spend
   │
   ▼
shot generator ────────► Wan video generation (dashscope-intl, verified Jul 6 — docs/verification.md)
   │                          │
   ▼                          ▼
ffmpeg assembly          metrics ledger (JSONL) ──► cost-quality dashboard
   │
   ▼
finished cut
```

Runtime: Alibaba Cloud SAS instance (Canada-provisioned account), Python 3.11.
Proof-of-deployment: Workbench screenshot + this repo's visible base URL usage.

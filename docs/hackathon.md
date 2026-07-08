# Hackathon reference

**Event:** Global AI Hackathon Series with Qwen Cloud
**Devpost:** https://qwencloud-hackathon.devpost.com/
**Track:** 2 — AI Showrunner (video generation: Wan)
**Sponsor:** Alibaba Cloud (Qwen Cloud) · **Administrator:** Devpost

## Official links & sources

- **Build Session FAQ** (Notion) — https://devpost.notion.site/Qwen-Cloud-Global-AI-Hackathon-Build-Session-FAQ-38fbf3c6a91d8038bd64d00459edbb19
- **Proof of deployment** (Google Doc) — https://docs.google.com/document/d/1XsiewMDMOGKxWGp7PRlaEnB7hN5n2JNIUho7cDIV8Vo/
- **Resources** (Devpost) — https://qwencloud-hackathon.devpost.com/resources
- **Judging rubric** — 4 weighted categories from the Build Session FAQ, mapped to this project in [judging.md](judging.md)

## Deadlines

- Submission: **2026-07-09, 2:00pm PDT** (Devpost is authoritative; submit by ~10am PDT)
- Judging: 2026-07-10 → 2026-07-31 · Results: ~2026-08-07

## Sanctioned Qwen Cloud base URLs (must be visible in the repo)

- `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` (OpenAI-compatible; used here)
- `https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` (OpenAI-compatible)
- `https://token-plan.ap-southeast-1.maas.aliyuncs.com/apps/anthropic` (Anthropic-compatible)

Native async video/image task API shares the `dashscope-intl.aliyuncs.com` host under `/api/v1/...`.

## Mandatory deliverables (see SUBMISSION.md for the full checklist)

- Public open-source repo, MIT license chip visible at the top of the repo page
- Code file with the Qwen Cloud base URL clearly visible
- **Screenshot of running resources from the Alibaba Cloud Workbench** ("No proof = not eligible") — requirements in the [Proof of deployment](https://docs.google.com/document/d/1XsiewMDMOGKxWGp7PRlaEnB7hN5n2JNIUho7cDIV8Vo/) doc
- Architecture diagram (`docs/architecture.md`)
- Demo video < 3 min, public (YouTube/Vimeo/Youku), "real working app"
- English text description; track identified; testing-access link (credentials if private)
- (Optional, stacks) Blog/social post on the build journey — separate prize

## Verified model roster (this project)

Chat `qwen-plus` · VLM `qwen-vl-plus` · draft video `wan2.1-t2v-turbo` ·
final video `wan2.2-t2v-plus` · stills `wan2.1-t2i-plus`. Live-tested — see
[verification.md](verification.md). The console roster governs over the FAQ doc IDs.

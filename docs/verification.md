# Day-1 verification log (Jul 6, 2026)

Evidence for the PLAN.md verify-or-abort gate. Decision: **PASS — no abort, ClipCrew proceeds.**

## 1. Chat API smoke test — PASS

`scripts/verify_quota.py` against the sanctioned OpenAI-compatible endpoint:

- Endpoint: `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`, model `qwen-plus`
- Minimal completion succeeded; usage reporting works (prompt=15, completion=1, total=16 tokens)

## 2. Video-gen quota — PASS (abort rule not triggered)

Console snapshot Jul 6; all quotas unused, free tier, expire **2026-10-05** (well past the Jul 9 deadline). Wan 2.1/2.2 clips are fixed at 5 s, so seconds ÷ 5 = generation cycles:

| Model | Free quota | Cycles | Planned role |
|---|---|---|---|
| wan2.1-t2v-turbo | 200 s | 40 | draft/iteration workhorse |
| wan2.2-t2v-plus | 50 s | 10 | final-quality renders only |
| wan2.1-kf2v-plus | 200 s | 40 | keyframe→video fallback |
| wan2.2-i2v-flash | 50 s | 10 | image→video fallback |
| wan2.2-animate-mix / -move | 50 s each | 10 each | unused |
| qwen-image / -edit / -edit-plus | 100 images each | — | storyboard frames |
| wan2.1-t2i-plus | 200 images | — | storyboard frames |

Abort threshold was ~12 cycles; turbo alone covers 40. Total video budget: 600 s.

## 3. Wan endpoint + task lifecycle — VERIFIED LIVE, zero quota spent

Method: POSTed an intentionally invalid request (empty `input`) to the legacy host with the
real key. Billing happens at generation, not admission, so a validation failure exercises
auth + routing + queueing for free.

- `POST https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis`
  with `X-DashScope-Async: enable` → **HTTP 200**, `task_id`, `task_status: PENDING`
- Poll `GET /api/v1/tasks/{task_id}` → `FAILED` ~100 ms later with
  `InvalidParameter: "prompt must contain words"` — no generation, no spend
- Confirms the classic `dashscope-intl.aliyuncs.com` host serves Wan video with the same
  `QWEN_API_KEY` as chat; the new workspace-scoped `maas.aliyuncs.com` URLs are not needed

### Findings that shape the retry policy (Jul 7)

1. **HTTP 200 ≠ valid request.** Validation is asynchronous: bad requests are accepted,
   then fail on the first poll with `output.code`/`output.message`. Retries must branch on
   polled task status, never on the POST's HTTP status.
2. **Every wan2.1/2.2 call costs exactly 5 s of quota** — duration is fixed, no parameter.
3. **`video_url` expires 24 h after completion.** Download the MP4 immediately; persist the
   file, not the URL.
4. Cancel (`POST /api/v1/tasks/{task_id}/cancel`) only works while `PENDING`.

Machine-facing constants and request/response shapes live in `server/pipeline.py`.

## 4. Remaining eligibility items (manual)

- [ ] Alibaba Cloud Workbench screenshot showing running SAS resources ("no proof = not eligible")
- [ ] Public GitHub repo with MIT badge visible

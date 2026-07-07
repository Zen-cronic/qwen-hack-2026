"""Pipeline stages. Each stage is a pure-ish function: inputs + budget in, artifacts + ledger entries out.

Build order (PLAN.md):
  Jul 6: script_agent, storyboard_agent, one generate_shot call end-to-end
  Jul 7: multi-shot loop w/ retry policy, assemble, HITL checkpoint

Wan video-generation API surface — VERIFIED live Jul 6 2026 (docs/verification.md
has the full evidence log; no quota was spent verifying):

  POST WAN_VIDEO_SYNTHESIS_URL
    headers: Authorization: Bearer <QWEN_API_KEY>
             Content-Type: application/json
             X-DashScope-Async: enable          <- required
    body:
      {
        "model": "wan2.1-t2v-turbo",
        "input": {"prompt": "<shot description>", "negative_prompt": "<optional>"},
        "parameters": {"size": "1280*720", "prompt_extend": true,
                       "watermark": false, "seed": 12345}
      }
    -> 200 {"output": {"task_id": ..., "task_status": "PENDING"}}

  GET WAN_TASK_URL_TEMPLATE.format(task_id=...)   (poll ~every 15s)
    -> {"output": {"task_status": "PENDING|RUNNING|SUCCEEDED|FAILED|CANCELED|UNKNOWN",
                   "video_url": "<mp4 — EXPIRES 24H after completion>",
                   "code"/"message": ...  (only on FAILED)},
        "usage": {...}}

Retry-policy gotchas (from the live probe):
  * HTTP 200 on the POST does NOT mean the request was valid — validation is
    async and surfaces as task_status=FAILED with output.code on the poll.
  * wan2.1/wan2.2 duration is fixed at 5s; every call costs exactly 5s of quota.
  * Persist the downloaded MP4, never the video_url.
"""

import os

WAN_VIDEO_SYNTHESIS_URL = (
    "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"
)
WAN_TASK_URL_TEMPLATE = "https://dashscope-intl.aliyuncs.com/api/v1/tasks/{task_id}"
WAN_TASK_CANCEL_URL_TEMPLATE = "https://dashscope-intl.aliyuncs.com/api/v1/tasks/{task_id}/cancel"

# Iterate cheap, render expensive: turbo has 4x the free quota of plus (see docs/verification.md).
DRAFT_MODEL = os.environ.get("WAN_DRAFT_MODEL", "wan2.1-t2v-turbo")
FINAL_MODEL = os.environ.get("WAN_FINAL_MODEL", "wan2.2-t2v-plus")

CLIP_SECONDS = 5  # fixed for wan2.1/wan2.2 — every generation call costs exactly this
POLL_INTERVAL_SECONDS = 15

TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"}

# TODO(Jul 6): script_agent(premise: str, budget: TokenBudget) -> Script
#   Qwen chat completion via QWEN_BASE_URL (OpenAI-compatible). Scenes with
#   beats, characters, tone. Log ledger entry per call.

# TODO(Jul 6): storyboard_agent(script: Script, budget: TokenBudget) -> ShotList
#   Scenes -> ordered shots, each with a generation prompt, target duration,
#   and an estimated token cost (feeds the frontier before any video spend).

# TODO(Jul 7): hitl_checkpoint(shot_list: ShotList) -> ShotList
#   Human approves/edits the shot list before video tokens are spent —
#   the single most expensive downstream commitment.

# TODO(Jul 6, one shot; Jul 7, loop): generate_shot(shot: Shot, budget: TokenBudget) -> Clip
#   Wan video generation against the verified surface above. Retry policy
#   consults metrics.frontier(): retry only when expected quality gain per
#   token beats the current frontier slope, and branch on the POLLED task
#   status/code — not the POST's HTTP status.

# TODO(Jul 7): assemble(clips: list[Clip]) -> Path
#   ffmpeg concat + crossfade; burn title card. Pure local, zero tokens.

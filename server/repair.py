"""Repair agent — turn measured assertion failures into a revised prompt (qwen-plus).

Bounded auto-repair is the loop that makes unattended generation deployable: a shot
that fails QC gets ONE revised prompt informed by exactly what was measured, then a
single retake. Creative intent is held fixed (same subject/scene/action); only the
render-controlling details change. Returns (new_prompt, usage) — the pipeline logs
the usage and regenerates.
"""

from __future__ import annotations

from server.script import _extract_json
from server.specs import AssertionResult, ShotSpec

_SYSTEM = (
    "You revise text-to-video prompts to fix specific, measured failures from an "
    "automated QC pass. You are given the original prompt and the assertions that "
    "FAILED on the rendered clip, each with what was measured. Rewrite the prompt so "
    "the next render is likely to satisfy those assertions WITHOUT changing the creative "
    "intent (same subject, scene, and action). Be concrete and visual; keep it one "
    'continuous ~5-second shot. Output STRICT JSON only: {"prompt": "<revised prompt>"}.'
)


def _failures_block(failures: list[AssertionResult]) -> str:
    lines = []
    for r in failures:
        measured = ", ".join(f"{k}={v}" for k, v in (r.measured or {}).items())
        lines.append(f"- {r.type.value} FAILED: {r.detail}" + (f" ({measured})" if measured else ""))
    return "\n".join(lines) or "- (unspecified failure)"


class RepairAgent:
    def __init__(self, client, model: str = "qwen-plus", max_tokens: int = 400):
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

    def __call__(self, spec: ShotSpec, failures: list[AssertionResult]):
        user = (
            f"Original prompt:\n{spec.prompt}\n\n"
            f"Failed assertions:\n{_failures_block(failures)}\n\n"
            "Return the revised prompt."
        )
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.4,
            max_tokens=self.max_tokens,
        )
        data = _extract_json(resp.choices[0].message.content or "{}")
        new_prompt = (data.get("prompt") or "").strip() or spec.prompt  # fall back to original
        return new_prompt, resp.usage

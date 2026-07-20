"""Repair agent — turn measured assertion failures into a revised prompt (qwen-plus).

Returns (new_prompt, usage); creative intent is held fixed, only render details change.
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
    "continuous ~5-second shot. When a failure names a time window, direct the fix at "
    "what happens during THAT part of the shot — say what the camera or subject should "
    "be doing then — instead of restating the whole shot. "
    'Output STRICT JSON only: {"prompt": "<revised prompt>"}.'
)

# Locus keys are phrased in prose by _locus_phrase, so they are excluded from `measured`.
_LOCUS_KEYS = ("fail_window_s", "worst_frame", "worst_frame_s", "fail_span_frames")


def _locus_phrase(measured: dict) -> str:
    """Human phrasing for where the failure sits, when the check localized it."""
    w = measured.get("fail_window_s")
    if not (isinstance(w, (list, tuple)) and len(w) == 2):
        return ""
    lo, hi = w
    return f" — worst from {lo:.1f}s to {hi:.1f}s" if hi > lo else f" — at {lo:.1f}s"


def _failures_block(failures: list[AssertionResult]) -> str:
    lines = []
    for r in failures:
        m = dict(r.measured or {})
        measured = ", ".join(f"{k}={v}" for k, v in m.items() if k not in _LOCUS_KEYS)
        lines.append(f"- {r.type.value} FAILED: {r.detail}"
                     + (f" ({measured})" if measured else "") + _locus_phrase(m))
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

"""Tier-B — qwen-vl semantic verdicts on strided frames. ADVISORY only.

GO per the hour-zero smoke test (qwen-vl-plus reads pixels). Tier-B answers the
questions deterministic CV can't: is this the SAME character across the clip
(identity_consistent), did the described ACTION actually complete (action_completed),
is a title card visible (title_card_present). Every Tier-B assertion is advisory — a
FAIL is surfaced to the human but never blocks promotion, because a VLM judgment
is softer evidence than a pixel measurement.

subject_present is NOT here: it is Tier-0, asked of the pre-render still by tier0.py,
where a rejection is still cheap. This module once carried a _question branch for it
that ASSERTION_META made unreachable — the tier filter below never selects it — which
is precisely what disguised the check as wired while nothing ran it.

NO-GO fallback (if the smoke test had failed): swap this stage for one that returns
INCONCLUSIVE for every Tier-B assertion, and the UI shows human verdict buttons.
"""

from __future__ import annotations

import base64

import cv2
import numpy as np

from server.script import _extract_json
from server.specs import Assertion, AssertionResult, AssertionType, ShotSpec, Status, Tier
from server.tier_a import extract_clip

_INSTRUCT = (
    ' Respond with STRICT JSON only: '
    '{"verdict": "pass" | "fail" | "inconclusive", "reason": "<one short sentence>"}.'
)


def _question(a: Assertion) -> str:
    if a.type is AssertionType.ACTION_COMPLETED:
        return (f'These are ordered frames from one short video clip. Does this action '
                f'occur AND visibly complete within the clip: "{a.params["action"]}"?')
    if a.type is AssertionType.IDENTITY_CONSISTENT:
        return (f'These are ordered frames from one short video clip. Is the subject '
                f'"{a.params["subject"]}" visually consistent — the same identity and '
                f'appearance — across all frames, with no morphing, duplication, or drift?')
    if a.type is AssertionType.TITLE_CARD_PRESENT:
        return ('These are ordered frames from one short video clip. Is a conspicuous on-screen '
                'title or text card (a title, caption, or lower-third graphic) clearly visible '
                'anywhere in the clip?')
    return "Describe this clip."


def _frames_to_data_uris(clip, n: int) -> list[str]:
    if clip.n == 0:
        return []
    idx = np.linspace(0, clip.n - 1, min(n, clip.n)).astype(int)
    uris: list[str] = []
    for i in idx:
        ok, buf = cv2.imencode(".png", clip.frames_bgr[int(i)])
        if ok:
            uris.append("data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii"))
    return uris


_VERDICT_MAP = {"pass": Status.PASS, "fail": Status.FAIL, "inconclusive": Status.INCONCLUSIVE}


class TierBVerifier:
    """Injected as the pipeline's tier_b_fn. Exposes pop_last_usage() so the
    pipeline can log VLM tokens without changing the stage's return shape."""

    def __init__(self, client, model: str = "qwen-vl-plus", n_frames: int = 7, max_tokens: int = 200):
        self.client = client
        self.model = model
        self.n_frames = n_frames
        self.max_tokens = max_tokens
        self._in = 0
        self._out = 0

    def pop_last_usage(self) -> tuple[int, int]:
        v = (self._in, self._out)
        self._in = self._out = 0
        return v

    def _ask(self, question: str, uris: list[str]) -> tuple[str, str]:
        content = [{"type": "text", "text": question + _INSTRUCT}]
        content += [{"type": "image_url", "image_url": {"url": u}} for u in uris]
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": content}],
            max_tokens=self.max_tokens,
            temperature=0,
        )
        usage = getattr(resp, "usage", None)
        self._in += getattr(usage, "prompt_tokens", 0) or 0
        self._out += getattr(usage, "completion_tokens", 0) or 0
        data = _extract_json(resp.choices[0].message.content or "{}")
        return str(data.get("verdict", "inconclusive")).lower(), str(data.get("reason", ""))

    def __call__(self, video_path: str, spec: ShotSpec) -> list[AssertionResult]:
        self._in = self._out = 0  # per-shot accumulation
        tier_b = [a for a in spec.assertions if a.tier is Tier.TIER_B]
        if not tier_b:
            return []
        clip = extract_clip(video_path)
        uris = _frames_to_data_uris(clip, self.n_frames)

        results: list[AssertionResult] = []
        for a in tier_b:
            if not uris:
                results.append(AssertionResult.for_assertion(a, Status.INCONCLUSIVE, detail="no frames"))
                continue
            try:
                verdict, reason = self._ask(_question(a), uris)
                status = _VERDICT_MAP.get(verdict, Status.INCONCLUSIVE)
                results.append(AssertionResult.for_assertion(a, status, detail=reason))
            except Exception as exc:  # noqa: BLE001 — advisory: degrade, don't crash the run
                results.append(AssertionResult.for_assertion(a, Status.INCONCLUSIVE, detail=f"vl error: {exc}"))
        return results


def inconclusive_verifier(video_path: str, spec: ShotSpec) -> list[AssertionResult]:
    """NO-GO fallback: every Tier-B assertion -> inconclusive (human decides in UI)."""
    return [
        AssertionResult.for_assertion(a, Status.INCONCLUSIVE, detail="Tier-B disabled — awaiting human verdict")
        for a in spec.assertions
        if a.tier is Tier.TIER_B
    ]

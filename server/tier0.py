"""Tier-0 — a VLM screen of the pre-render still, before any video spend.

Nothing gates on tier0_results: they are evidence at the human review gate, not an automatic
block. Errors degrade to INCONCLUSIVE, never FAIL — never fabricate a rejection.
"""

from __future__ import annotations

import base64
from pathlib import Path

import cv2

from server.script import _extract_json
from server.specs import Assertion, AssertionResult, AssertionType, ShotSpec, Status, Tier

# VLM image tokens scale with pixel count, so the ~1024px still must be downscaled or the
# pre-screen costs more than the Tier-B batch it exists to avoid.
STILL_WIDTH = 512

_INSTRUCT = (
    ' Respond with STRICT JSON only: '
    '{"verdict": "pass" | "fail" | "inconclusive", "reason": "<one short sentence>"}.'
)

_VERDICT_MAP = {"pass": Status.PASS, "fail": Status.FAIL, "inconclusive": Status.INCONCLUSIVE}


def _question(a: Assertion) -> str:
    """Phrased for ONE still, not a clip — Tier-B asks the motion questions."""
    if a.type is AssertionType.SUBJECT_PRESENT:
        return (f'This is a single still frame previewing a video shot. Is '
                f'"{a.params["subject"]}" clearly present and recognizable in this image?')
    return "Describe this image."


def still_to_data_uri(path: str, width: int = STILL_WIDTH) -> str | None:
    """The still, downscaled to `width`, as a PNG data URI; None if missing or unreadable."""
    p = Path(path)
    if not p.is_file() or p.stat().st_size == 0:
        return None
    im = cv2.imread(str(p))
    if im is None:
        return None
    h, w = im.shape[:2]
    if w > width:
        im = cv2.resize(im, (width, max(1, round(h * width / w))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", im)
    if not ok:
        return None
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


class Tier0Verifier:
    """Injected as the pipeline's tier0_fn; pop_last_usage() is the contract Pipeline._pop_usage reads."""

    def __init__(self, client, model: str = "qwen-vl-plus", max_tokens: int = 200):
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self._in = 0
        self._out = 0

    def pop_last_usage(self) -> tuple[int, int]:
        v = (self._in, self._out)
        self._in = self._out = 0
        return v

    def _ask(self, question: str, uri: str) -> tuple[str, str]:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": question + _INSTRUCT},
                {"type": "image_url", "image_url": {"url": uri}},
            ]}],
            max_tokens=self.max_tokens,
            temperature=0,
        )
        usage = getattr(resp, "usage", None)
        self._in += getattr(usage, "prompt_tokens", 0) or 0
        self._out += getattr(usage, "completion_tokens", 0) or 0
        data = _extract_json(resp.choices[0].message.content or "{}")
        return str(data.get("verdict", "inconclusive")).lower(), str(data.get("reason", ""))

    def __call__(self, spec: ShotSpec, still_path: str) -> list[AssertionResult]:
        self._in = self._out = 0  # per-shot accumulation
        tier0 = [a for a in spec.assertions if a.tier is Tier.TIER0]
        if not tier0:
            return []

        uri = still_to_data_uri(still_path) if still_path else None
        if uri is None:
            return [AssertionResult.for_assertion(a, Status.INCONCLUSIVE, detail="no still")
                    for a in tier0]

        results: list[AssertionResult] = []
        for a in tier0:
            try:
                verdict, reason = self._ask(_question(a), uri)
                status = _VERDICT_MAP.get(verdict, Status.INCONCLUSIVE)
                results.append(AssertionResult.for_assertion(a, status, detail=reason,
                                                             evidence=[still_path]))
            except Exception as exc:  # noqa: BLE001 — degrade to INCONCLUSIVE, never fabricate a FAIL
                results.append(AssertionResult.for_assertion(
                    a, Status.INCONCLUSIVE, detail=f"vl error: {exc}", evidence=[still_path]))
        return results


def inconclusive_verifier(spec: ShotSpec, still_path: str) -> list[AssertionResult]:
    """NO-GO fallback: every Tier-0 assertion -> inconclusive. Must never return [] — an
    empty list silently certifies, a verdict does not."""
    return [
        AssertionResult.for_assertion(a, Status.INCONCLUSIVE,
                                      detail="Tier-0 disabled — awaiting human verdict",
                                      evidence=[still_path] if still_path else [])
        for a in spec.assertions
        if a.tier is Tier.TIER0
    ]

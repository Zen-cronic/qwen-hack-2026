"""Tier-0 — the pre-render still screen. The cheapest rejection the pipeline can make.

The pipeline already pays for one t2i still per shot before any video spend. Tier-0 is
what makes that spend worth making: it asks a VLM whether the shot's subject actually
survived the prompt, on the still, while a rejection still costs ~1/25th of a clip and
the human gate is one step away. A prompt that cannot even render its subject as a
single frame will not render it as motion, and finding that out here is the difference
between spending an image and spending a premium clip.

Why this module exists at all: the still was being generated and billed while tier0_fn
was `lambda spec, still: []` in every production path, so subject_present -- a BLOCKING
assertion -- was evaluated by nothing. Nothing failed loudly, because at
`take.passed = not [r for r in results if not r.advisory and r.status is Status.FAIL]`
a check that returns no result and a check that passes are the same empty list.

What a FAIL here does, precisely: nothing gates on tier0_results. The pipeline stores them
and the UI renders them at the one human checkpoint, where a person decides whether to
release video budget -- so a Tier-0 verdict is EVIDENCE AT THAT GATE, not an automatic
block. subject_present carries advisory=False, which is blocking-class and would block if
it ever reached a take's results; it does not today. Saying more than that here would
repeat the mistake this module was written to fix.

Errors therefore degrade to INCONCLUSIVE, never FAIL: a broken VL call must not fabricate
a rejection, and an undecidable shot belongs in front of the human rather than in a verdict.
"""

from __future__ import annotations

import base64
from pathlib import Path

import cv2

from server.script import _extract_json
from server.specs import Assertion, AssertionResult, AssertionType, ShotSpec, Status, Tier

# The t2i models return ~1024x1024. VLM image tokens scale with pixel count, so sending
# the still at source resolution would make the "1/25th of a clip" pre-screen cost more
# than the seven frames Tier-B sends for the whole video — inverting the entire reason
# Tier-0 runs first. Tier-B judges identity at FRAME_WIDTH=320; one still can afford more
# detail than one of seven frames and still cost a fraction of that batch.
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
    """The still, downscaled to `width`, as a PNG data URI. None if it is missing or
    unreadable — the pipeline hands us a path the generator wrote, and a t2i failure
    leaves that path absent rather than raising here."""
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
    """Injected as the pipeline's tier0_fn. Exposes pop_last_usage() so the pipeline
    logs the VLM tokens this stage spends — the same contract TierBVerifier uses, so
    _pop_usage picks it up with no pipeline special-casing."""

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
    """NO-GO fallback, mirroring tier_b's: every Tier-0 assertion -> inconclusive.

    Used when no VL model is available. Returning INCONCLUSIVE rather than [] is the
    whole lesson of this module: an empty list silently certifies, a verdict does not.
    """
    return [
        AssertionResult.for_assertion(a, Status.INCONCLUSIVE,
                                      detail="Tier-0 disabled — awaiting human verdict",
                                      evidence=[still_path] if still_path else [])
        for a in spec.assertions
        if a.tier is Tier.TIER0
    ]

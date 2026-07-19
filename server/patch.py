"""Targeted repair — re-render one shot anchored to its own footage.

The retake loop in pipeline.py answers a failure by re-prompting the WHOLE shot and
generating five fresh seconds from noise. That discards everything the take already got
right — the composition Tier-0 approved, the palette that passed, the subject that was
recognizable — and it spends the t2v draft/final quota the judge reserve protects.

A patch does the narrow thing instead. Tier-A localizes the failure to a frame window
(server/tier_a.py), the last good frame BEFORE that window becomes the anchor, and a
frame-anchored model (wan i2v / kf2v, its own free-tier pool) regenerates from there on
a locus-aware corrected prompt. Then Tier-A re-verifies, and a passing patch becomes the
shot's final so the episode re-concats for free.

Deliberately scoped: no script call, no Tier-0, no review gate, and no other shot is
touched. That is the whole point — editing the episode without re-running the pipeline.

A patch is never silently accepted. If the patched clip fails re-verification the
original clip stays the final, and the failed attempt is still recorded as a take, so
the trail shows what was tried.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from server.metrics import ResourceKind
from server.specs import AssertionResult, ShotSpec, Status
from server.store import ShotStatus, Store, Take, TakeStatus

# Step back slightly from the window edge: the measured boundary is where the defect is
# already visible, so the frame just before it is the last one worth keeping.
ANCHOR_LEAD_S = 0.2


@dataclass
class PatchOutcome:
    ok: bool
    reason: str
    shot_index: int
    anchor_s: float | None = None
    anchor_frame: str | None = None
    video_path: str | None = None
    certified: bool = False
    billed_seconds: int = 0
    results: list[AssertionResult] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "reason": self.reason, "shot_index": self.shot_index,
            "anchor_s": self.anchor_s, "anchor_frame": self.anchor_frame,
            "video_path": self.video_path, "certified": self.certified,
            "billed_seconds": self.billed_seconds,
            "checks": [{"type": r.type.value, "status": r.status.value, "detail": r.detail,
                        "measured": r.measured} for r in self.results],
        }


def localized_failure(results: list[AssertionResult]) -> AssertionResult | None:
    """The first blocking failure that Tier-A could place in time.

    Advisory failures are excluded on purpose: Tier-B flags, it never blocks, so
    spending a generation to chase one would invert the tier contract.
    """
    for r in results:
        if r.advisory or r.status is not Status.FAIL:
            continue
        w = r.measured.get("fail_window_s")
        if isinstance(w, (list, tuple)) and len(w) == 2:
            return r
    return None


def anchor_second(r: AssertionResult) -> float:
    lo = float(r.measured["fail_window_s"][0])
    return max(0.0, lo - ANCHOR_LEAD_S)


def extract_frame(video_path: str, at_s: float, out_path: str | Path) -> str | None:
    """Full-resolution frame at `at_s`. Not from the Tier-A Clip: that one is decimated
    to 320px wide for analysis, and a 320px anchor would re-render the shot at 320px."""
    cap = cv2.VideoCapture(str(video_path))
    cap.set(cv2.CAP_PROP_POS_MSEC, at_s * 1000.0)
    ok, frame = cap.read()
    if not ok:  # seek landed past the end, or the container lies — fall back to frame 0
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return None
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), frame)
    return str(out)


def patch_shot(store: Store, pid: str, shot_index: int, deps, cfg, *, model: str) -> PatchOutcome:
    """Re-render one shot from its last good frame and re-verify. See module docstring."""
    p = store.get(pid)
    if p is None:
        return PatchOutcome(False, "no such project", shot_index)
    if not 0 <= shot_index < len(p.shots):
        return PatchOutcome(False, f"no shot {shot_index}", shot_index)
    if deps.patch_video_fn is None:
        return PatchOutcome(False, "this runtime has no frame-anchored generator", shot_index)

    st = p.shots[shot_index]
    take = st.latest_take
    source = (take.video_path if take else None) or st.final_path
    if not source or not Path(source).exists():
        return PatchOutcome(False, "shot has no rendered clip to patch", shot_index)

    failure = localized_failure(take.results if take else [])
    if failure is None:
        return PatchOutcome(False, "no blocking failure with a located window", shot_index)

    at = anchor_second(failure)
    patch_no = len(st.takes)
    ev_dir = Path(cfg.data_dir) / pid / "evidence" / f"shot{shot_index}" / f"patch{patch_no}"
    anchor = extract_frame(source, at, ev_dir / "anchor.png")
    if anchor is None:
        return PatchOutcome(False, f"could not read a frame at {at:.2f}s", shot_index, at)

    # Reuse the repair agent: it already phrases the locus and holds creative intent fixed.
    spec: ShotSpec = st.spec
    prompt, usage = deps.repair_fn(spec, [failure])
    deps.ledger.record(stage="patching", kind=ResourceKind.CHAT, model=cfg.chat_model,
                       shot_index=shot_index,
                       tokens_in=getattr(usage, "prompt_tokens", 0),
                       tokens_out=getattr(usage, "completion_tokens", 0))

    res = deps.patch_video_fn(prompt, model, anchor)
    billed = 0 if getattr(res, "from_cache", False) else getattr(res, "seconds", 0)
    deps.ledger.record(stage="patching", kind=ResourceKind.VIDEO_PATCH, model=model,
                       shot_index=shot_index, video_seconds=billed,
                       cached_seconds=getattr(res, "cached_seconds", 0),
                       latency_ms=getattr(res, "latency_ms", 0),
                       note="cache" if getattr(res, "from_cache", False) else "")

    tk = Take(take_no=patch_no, tier="patch", model=model, prompt=prompt,
              status=TakeStatus.DONE if res.ok else TakeStatus.FAILED,
              video_path=res.local_path if res.ok else None)
    if not res.ok:
        store.update(pid, lambda pr: pr.shots[shot_index].takes.append(tk))
        return PatchOutcome(False, f"generation failed: {getattr(res, 'message', '')}",
                            shot_index, at, anchor, billed_seconds=billed)

    results = list(deps.tier_a_fn(res.local_path, spec, str(ev_dir)))
    tk.results = results
    tk.passed = not [r for r in results if not r.advisory and r.status is Status.FAIL]

    def mut(pr) -> None:
        s = pr.shots[shot_index]
        s.takes.append(tk)
        if tk.passed:
            # The patch earned the slot; the original clip stays in the take history.
            s.final_path = tk.video_path
            s.certified = True
            s.status = ShotStatus.CERTIFIED

    store.update(pid, mut)

    if tk.passed:
        paths = [s.final_path for s in store.get(pid).shots if s.certified and s.final_path]
        if paths:
            out = str(Path(cfg.data_dir) / pid / "episode.mp4")
            episode = deps.assemble_fn(paths, out)  # free re-concat, no tokens
            store.update(pid, lambda pr: setattr(pr, "episode_path", episode))

    return PatchOutcome(
        ok=bool(tk.passed),
        reason="patched and re-verified" if tk.passed else "patch still fails its contract",
        shot_index=shot_index, anchor_s=round(at, 2), anchor_frame=anchor,
        video_path=tk.video_path, certified=bool(tk.passed),
        billed_seconds=billed, results=results)

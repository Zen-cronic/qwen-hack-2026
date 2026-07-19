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


def _spend(store: Store, pid: str, deps, **kw) -> None:
    """Record to the process-wide ledger AND the project's own copy, mirroring
    Pipeline._spend. The wallet meter reads the project copy, so recording only to the
    writer leaves a patch invisible in the UI even though the audit trail has it."""
    entry = deps.ledger.record(**kw)

    def mut(p) -> None:
        p.ledger.append(entry)
        p.recompute_wallet()

    store.update(pid, mut)


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
        return PatchOutcome(False, "That run no longer exists.", shot_index)
    if not 0 <= shot_index < len(p.shots):
        return PatchOutcome(False, f"This run has no shot {shot_index}.", shot_index)
    if deps.patch_video_fn is None:
        return PatchOutcome(False, "Patching is not available in this mode.", shot_index)

    st = p.shots[shot_index]
    spec: ShotSpec = st.spec
    take = st.latest_take
    source = (take.video_path if take else None) or st.final_path
    if not source or not Path(source).exists():
        return PatchOutcome(False, "This shot has not been rendered yet — there is nothing to patch.", shot_index)

    patch_no = len(st.takes)
    ev_dir = Path(cfg.data_dir) / pid / "evidence" / f"shot{shot_index}" / f"patch{patch_no}"

    # Re-measure the clip rather than trusting the results stored beside it. Tier-A gained
    # failure localization after runs were already on disk, and those takes carry no window
    # at all — re-verifying is deterministic CV on a file we already have, so it costs
    # nothing and it is the only way to patch a run that predates the feature. It also
    # keeps a patch honest if the checks themselves have changed since the take was cut.
    fresh = list(deps.tier_a_fn(source, spec, str(ev_dir / "reverify")))
    # A fresh measurement is authoritative WHENEVER it produced one. Falling back to the
    # stored results on a clean re-verify would let a stale recorded failure justify
    # patching a clip that now passes. Stored results are only for the case where Tier-A
    # returned nothing at all — an unreadable clip, or a spec with no Tier-A assertions.
    failure = localized_failure(fresh) if fresh else localized_failure(take.results if take else [])
    if failure is None:
        return PatchOutcome(False, "Nothing to patch — every blocking check on this shot passes.", shot_index)

    at = anchor_second(failure)
    anchor = extract_frame(source, at, ev_dir / "anchor.png")
    if anchor is None:
        return PatchOutcome(False, f"Could not read a frame at {at:.2f}s to anchor the re-render.", shot_index, at)

    # Reuse the repair agent: it already phrases the locus and holds creative intent fixed.
    prompt, usage = deps.repair_fn(spec, [failure])
    _spend(store, pid, deps, stage="patching", kind=ResourceKind.CHAT, model=cfg.chat_model,
           shot_index=shot_index,
           tokens_in=getattr(usage, "prompt_tokens", 0),
           tokens_out=getattr(usage, "completion_tokens", 0))

    res = deps.patch_video_fn(prompt, model, anchor)
    billed = 0 if getattr(res, "from_cache", False) else getattr(res, "seconds", 0)
    _spend(store, pid, deps, stage="patching", kind=ResourceKind.VIDEO_PATCH, model=model,
           shot_index=shot_index, video_seconds=billed,
           cached_seconds=getattr(res, "cached_seconds", 0),
           latency_ms=getattr(res, "latency_ms", 0),
           note="cache" if getattr(res, "from_cache", False) else "")

    tk = Take(take_no=patch_no, tier="patch", model=model, prompt=prompt,
              status=TakeStatus.DONE if res.ok else TakeStatus.FAILED,
              video_path=res.local_path if res.ok else None)
    if not res.ok:
        store.update(pid, lambda pr: pr.shots[shot_index].takes.append(tk))
        return PatchOutcome(False, f"The re-render did not complete: {getattr(res, 'message', '') or res.status}",
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
        reason="Patched, re-verified, and back under contract." if tk.passed
               else "The re-render still does not pass — the original clip was kept.",
        shot_index=shot_index, anchor_s=round(at, 2), anchor_frame=anchor,
        video_path=tk.video_path, certified=bool(tk.passed),
        billed_seconds=billed, results=results)

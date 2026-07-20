"""Targeted repair — re-render one shot anchored to its own footage, without re-running the pipeline.

Anchor to preserve, re-roll to change: a failure window opening at t=0 has no good frame, so
the patch re-rolls and `anchor_s` is None. A failed re-verification never replaces the original.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from server.metrics import ResourceKind
from server.specs import AssertionResult, ShotSpec, Status
from server.store import ShotStatus, Store, Take, TakeStatus

# Step back from the window edge: the boundary is where the defect is already visible.
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
    """Record to the process-wide ledger AND the project's own copy (the wallet reads the copy)."""
    entry = deps.ledger.record(**kw)

    def mut(p) -> None:
        p.ledger.append(entry)
        p.recompute_wallet()

    store.update(pid, mut)


def localized_failure(results: list[AssertionResult]) -> AssertionResult | None:
    """The first blocking failure Tier-A could place in time; advisory ones never qualify."""
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
    """Full-resolution frame at `at_s`. Never source this from the Tier-A Clip — it is
    decimated to 320px, and a 320px anchor re-renders the shot at 320px."""
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

    # Re-measure rather than trust stored results: free deterministic CV, and old takes carry
    # no failure window at all.
    fresh = list(deps.tier_a_fn(source, spec, str(ev_dir / "reverify")))
    # A fresh measurement is authoritative WHENEVER it produced one; stored results are only
    # for the case where Tier-A returned nothing at all.
    failure = localized_failure(fresh) if fresh else localized_failure(take.results if take else [])
    if failure is None:
        return PatchOutcome(False, "Nothing to patch — every blocking check on this shot passes.", shot_index)

    at = anchor_second(failure)
    # Anchor to PRESERVE, re-roll to CHANGE: a window opening at t=0 has no good frame, and
    # anchoring would pin the defect. Mirrors Pipeline._anchor_for_retake.
    anchored = at > 0.0
    anchor = extract_frame(source, at, ev_dir / "anchor.png") if anchored else None
    if anchored and anchor is None:
        return PatchOutcome(False, f"Could not read a frame at {at:.2f}s to anchor the re-render.", shot_index, at)

    # Reuse the repair agent: it already phrases the locus and holds creative intent fixed.
    prompt, usage = deps.repair_fn(spec, [failure])
    _spend(store, pid, deps, stage="patching", kind=ResourceKind.CHAT, model=cfg.chat_model,
           shot_index=shot_index,
           tokens_in=getattr(usage, "prompt_tokens", 0),
           tokens_out=getattr(usage, "completion_tokens", 0))

    if anchored:
        res = deps.patch_video_fn(prompt, model, anchor)
        used_model = model
    else:
        # Whole-clip re-roll — this draws the t2v draft pool, not the i2v pool.
        res = deps.gen_video_fn(prompt, cfg.draft_model)
        used_model = cfg.draft_model
    billed = 0 if getattr(res, "from_cache", False) else getattr(res, "seconds", 0)
    # Recorded as VIDEO_PATCH however it was rendered — the role, not the endpoint.
    _spend(store, pid, deps, stage="patching", kind=ResourceKind.VIDEO_PATCH, model=used_model,
           shot_index=shot_index, video_seconds=billed,
           cached_seconds=getattr(res, "cached_seconds", 0),
           latency_ms=getattr(res, "latency_ms", 0),
           note="cache" if getattr(res, "from_cache", False) else "")

    tk = Take(take_no=patch_no, tier="patch", model=used_model, prompt=prompt,
              status=TakeStatus.DONE if res.ok else TakeStatus.FAILED,
              video_path=res.local_path if res.ok else None)
    if not res.ok:
        store.update(pid, lambda pr: pr.shots[shot_index].takes.append(tk))
        return PatchOutcome(False, f"The re-render did not complete: {getattr(res, 'message', '') or res.status}",
                            shot_index, at if anchored else None, anchor, billed_seconds=billed)

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
        shipped = [s for s in store.get(pid).shots if s.certified and s.final_path]
        paths = [s.final_path for s in shipped]
        if paths:
            out = str(Path(cfg.data_dir) / pid / "episode.mp4")
            # Must re-narrate through the pipeline's path, or the re-cut silently ships silent.
            from server.pipeline import Pipeline
            audio = Pipeline(store, pid, deps, cfg)._narrate(shipped)
            episode = (deps.assemble_fn(paths, out, audio_paths=audio) if audio
                       else deps.assemble_fn(paths, out))
            store.update(pid, lambda pr: setattr(pr, "episode_path", episode))

    return PatchOutcome(
        ok=bool(tk.passed),
        reason="Patched, re-verified, and back under contract." if tk.passed
               else "The re-render still does not pass — the original clip was kept.",
        shot_index=shot_index, anchor_s=round(at, 2) if anchored else None, anchor_frame=anchor,
        video_path=tk.video_path, certified=bool(tk.passed),
        billed_seconds=billed, results=results)

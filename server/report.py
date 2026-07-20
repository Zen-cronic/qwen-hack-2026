"""Derived conformance metrics — pure aggregation over takes + the ledger, returned as the
`metrics` block of GET /api/projects/{id}.
"""

from __future__ import annotations

from server.specs import Status
from server.store import ProjectState, ShotState, Take


def _quality(take: Take | None) -> float:
    if take is None:
        return 0.0
    blocking = [r for r in take.results if not r.advisory]
    if not blocking:
        return 1.0 if take.passed else 0.0
    return round(sum(1 for r in blocking if r.status is Status.PASS) / len(blocking), 3)


def _drafts(s: ShotState) -> list[Take]:
    return [t for t in s.takes if t.tier == "draft"]


def _repair_attempts(s: ShotState) -> list[Take]:
    """Every attempt after the first draft: retake-loop drafts plus targeted patches."""
    return _drafts(s)[1:] + [t for t in s.takes if t.tier == "patch"]


def _first_draft_passed(s: ShotState) -> bool:
    d = _drafts(s)
    return bool(d) and d[0].passed is True


def build_report_metrics(p: ProjectState) -> dict:
    shots = p.shots
    certified = sum(1 for s in shots if s.certified)
    failed = sum(1 for s in shots if s.status.value == "failed")

    heatmap: dict[str, dict] = {}
    for s in shots:
        for t in s.takes:
            for r in t.results:
                d = heatmap.setdefault(r.type.value, {"pass": 0, "fail": 0, "inconclusive": 0, "total": 0})
                d["total"] += 1
                d[r.status.value] = d.get(r.status.value, 0) + 1
    for d in heatmap.values():
        d["pass_rate"] = round(d["pass"] / d["total"], 3) if d["total"] else 0.0

    # Two cost views per shot: what THIS run billed, and what the artifacts cost to PRODUCE
    # (billed + cache-replayed). The frontier charts production cost.
    sec_by_shot: dict[int, int] = {}
    usd_by_shot: dict[int, float] = {}
    prod_sec_by_shot: dict[int, int] = {}
    prod_usd_by_shot: dict[int, float] = {}
    for e in p.ledger:
        if e.shot_index is None:
            continue
        sec_by_shot[e.shot_index] = sec_by_shot.get(e.shot_index, 0) + e.video_seconds
        usd_by_shot[e.shot_index] = usd_by_shot.get(e.shot_index, 0.0) + e.est_usd
        prod_sec_by_shot[e.shot_index] = (prod_sec_by_shot.get(e.shot_index, 0)
                                          + e.video_seconds + e.cached_seconds)
        prod_usd_by_shot[e.shot_index] = prod_usd_by_shot.get(e.shot_index, 0.0) + e.modeled_usd

    # Only shots with at least one take — before drafting there is no cost or quality to plot.
    frontier = [{
        "shot": s.spec.index,
        "cost_seconds": sec_by_shot.get(s.spec.index, 0),
        "cost_usd": round(usd_by_shot.get(s.spec.index, 0.0), 4),
        "production_seconds": prod_sec_by_shot.get(s.spec.index, 0),
        "production_usd": round(prod_usd_by_shot.get(s.spec.index, 0.0), 4),
        "replayed": prod_sec_by_shot.get(s.spec.index, 0) > sec_by_shot.get(s.spec.index, 0),
        "quality": _quality(s.takes[-1]),
        "certified": s.certified,
    } for s in shots if s.takes]

    # Every take, in order, as one point — a shot's row is the repair loop's trajectory.
    convergence = [{
        "shot": s.spec.index,
        "take": t.take_no,
        "tier": t.tier,
        "passed": bool(t.passed),
        "quality": _quality(t),
    } for s in shots for t in s.takes]

    repaired = [s for s in shots if _repair_attempts(s)]
    retakes_total = sum(len(_repair_attempts(s)) for s in shots)

    passing_seconds = certified * 5
    with_still = [s for s in shots if s.still_path]
    transfer = sum(1 for s in with_still if _first_draft_passed(s))

    return {
        "summary": {"shots_total": len(shots), "certified": certified, "failed": failed},
        "heatmap": heatmap,
        "frontier": frontier,
        "convergence": convergence,
        "repair": {"retakes_total": retakes_total, "shots_repaired": len(repaired),
                   "repair_successes": sum(1 for s in repaired if s.certified)},
        "cost_per_passing_second": (round(p.wallet.est_usd / passing_seconds, 4)
                                    if passing_seconds else None),
        "transfer_rate": (round(transfer / len(with_still), 3) if with_still else None),
    }

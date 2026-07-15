"""Derived conformance metrics — the dashboard's numbers, computed from ProjectState.

GET /api/projects/{id} returns the raw project plus this `metrics` block. Nothing
here spends anything; it's pure aggregation over takes + the ledger:
  * heatmap        — pass/fail/inconclusive per assertion type = an empirical
                     capability map of the draft model
  * frontier       — per-shot (cost, quality) scatter points
  * convergence    — every take as a point, so the repair loop's trajectory per shot is
                     readable: a failing take followed by a passing one is a convergence
  * repair         — retakes and how many repaired shots then certified
  * transfer_rate  — of shots with a Tier-0 still, how many passed on the FIRST
                     draft (image -> video transfer)
  * cost_per_passing_second — the headline unit-economics number
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

    sec_by_shot: dict[int, int] = {}
    usd_by_shot: dict[int, float] = {}
    for e in p.ledger:
        if e.shot_index is None:
            continue
        sec_by_shot[e.shot_index] = sec_by_shot.get(e.shot_index, 0) + e.video_seconds
        usd_by_shot[e.shot_index] = usd_by_shot.get(e.shot_index, 0.0) + e.est_usd

    frontier = [{
        "shot": s.spec.index,
        "cost_seconds": sec_by_shot.get(s.spec.index, 0),
        "cost_usd": round(usd_by_shot.get(s.spec.index, 0.0), 4),
        "quality": _quality(s.takes[-1] if s.takes else None),
        "certified": s.certified,
    } for s in shots]

    # Every take, in order, as one point. Reading a shot's row left to right gives the
    # repair loop's trajectory: a failing take followed by a passing one is a convergence.
    convergence = [{
        "shot": s.spec.index,
        "take": t.take_no,
        "tier": t.tier,
        "passed": bool(t.passed),
        "quality": _quality(t),
    } for s in shots for t in s.takes]

    repaired = [s for s in shots if len(_drafts(s)) > 1]
    retakes_total = sum(max(0, len(_drafts(s)) - 1) for s in shots)

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

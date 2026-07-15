"""Derived report metrics over a hand-built ProjectState."""

from server.metrics import LedgerEntry, ResourceKind
from server.report import build_report_metrics
from server.specs import AssertionResult, AssertionType, ShotSpec, Status, Tier
from server.store import ProjectState, ShotState, ShotStatus, Take, TakeStatus


def _res(status):
    return AssertionResult(type=AssertionType.SCENE_CUTS, tier=Tier.TIER_A, advisory=False, status=status)


def _take(no, tier, prompt, res, passed):
    return Take(take_no=no, tier=tier, model="m", prompt=prompt, status=TakeStatus.DONE,
                results=[res], passed=passed)


def test_convergence_traces_every_take_per_shot():
    """One point per take, tagged with its shot — the repair loop's trajectory.

    Shot 0 converges (draft FAIL -> draft PASS -> final); shot 1 never does. Reading a
    shot's row in take order is exactly what the dashboard's convergence chart draws.
    """
    p = ProjectState(id="p", premise="x", pack="short_drama", max_shots=2)
    p.shots = [
        ShotState(spec=ShotSpec(index=0, prompt="a"), status=ShotStatus.CERTIFIED, certified=True,
                  takes=[_take(0, "draft", "a", _res(Status.FAIL), False),
                         _take(1, "draft", "a2", _res(Status.PASS), True),
                         _take(2, "final", "a2", _res(Status.PASS), True)]),
        ShotState(spec=ShotSpec(index=1, prompt="b"), status=ShotStatus.FAILED, certified=False,
                  takes=[_take(0, "draft", "b", _res(Status.FAIL), False)]),
    ]

    conv = build_report_metrics(p)["convergence"]

    assert [(c["shot"], c["take"], c["passed"]) for c in conv] == [
        (0, 0, False), (0, 1, True), (0, 2, True), (1, 0, False),
    ]
    assert [c["tier"] for c in conv if c["shot"] == 0] == ["draft", "draft", "final"]
    # (shot, take) must be unique or the scatter overplots and the trajectory is unreadable.
    keys = [(c["shot"], c["take"]) for c in conv]
    assert len(keys) == len(set(keys))
    assert all(c["passed"] is False for c in conv if c["shot"] == 1)


def test_report_metrics_end_to_end():
    p = ProjectState(id="p", premise="x", pack="short_drama", max_shots=2)
    s0 = ShotState(spec=ShotSpec(index=0, prompt="a"), status=ShotStatus.CERTIFIED, certified=True,
                   final_path="data/x.mp4", still_path="data/s0.png",
                   takes=[_take(0, "draft", "a", _res(Status.FAIL), False),
                          _take(1, "draft", "a2", _res(Status.PASS), True),
                          _take(2, "final", "a2", _res(Status.PASS), True)])
    s1 = ShotState(spec=ShotSpec(index=1, prompt="b"), status=ShotStatus.FAILED, certified=False,
                   still_path="data/s1.png",
                   takes=[_take(0, "draft", "b", _res(Status.FAIL), False),
                          _take(1, "draft", "b2", _res(Status.FAIL), False)])
    p.shots = [s0, s1]
    p.ledger = [
        LedgerEntry(ts=0, stage="drafting", kind=ResourceKind.VIDEO_DRAFT, model="turbo", video_seconds=5, shot_index=0),
        LedgerEntry(ts=0, stage="promoting", kind=ResourceKind.VIDEO_FINAL, model="plus", video_seconds=5, shot_index=0),
        LedgerEntry(ts=0, stage="drafting", kind=ResourceKind.VIDEO_DRAFT, model="turbo", video_seconds=5, shot_index=1),
    ]
    p.recompute_wallet()

    m = build_report_metrics(p)
    assert m["summary"] == {"shots_total": 2, "certified": 1, "failed": 1}
    assert m["heatmap"]["scene_cuts"] == {"pass": 2, "fail": 3, "inconclusive": 0, "total": 5, "pass_rate": 0.4}
    assert m["repair"] == {"retakes_total": 2, "shots_repaired": 2, "repair_successes": 1}
    assert m["cost_per_passing_second"] == 0.5   # est_usd 2.5 / (1 certified * 5s)
    assert m["transfer_rate"] == 0.0             # neither shot's first draft passed

    f0 = next(f for f in m["frontier"] if f["shot"] == 0)
    assert f0["cost_seconds"] == 10 and f0["quality"] == 1.0 and f0["certified"] is True

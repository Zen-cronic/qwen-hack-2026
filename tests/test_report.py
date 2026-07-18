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
    # Cold run: production cost == billed cost, nothing replayed.
    assert f0["production_seconds"] == 10 and f0["replayed"] is False


def test_frontier_survives_a_fully_cached_rerun():
    """Regression: on a warm re-verify every ledger entry bills 0 seconds, and the
    frontier used to collapse to a single dot at x=0 — blank in exactly the mode
    judges re-run. Production cost (billed + cache-replayed) must survive the replay
    while the wallet keeps billing zero."""
    p = ProjectState(id="p", premise="x", pack="short_drama", max_shots=1)
    p.shots = [
        ShotState(spec=ShotSpec(index=0, prompt="a"), status=ShotStatus.CERTIFIED, certified=True,
                  takes=[_take(0, "draft", "a", _res(Status.PASS), True),
                         _take(1, "final", "a", _res(Status.PASS), True)]),
    ]
    p.ledger = [
        LedgerEntry(ts=0, stage="drafting", kind=ResourceKind.VIDEO_DRAFT, model="turbo",
                    video_seconds=0, cached_seconds=5, shot_index=0, note="cache"),
        LedgerEntry(ts=0, stage="promoting", kind=ResourceKind.VIDEO_FINAL, model="plus",
                    video_seconds=0, cached_seconds=5, shot_index=0, note="cache"),
    ]
    p.recompute_wallet()

    f0 = build_report_metrics(p)["frontier"][0]
    assert f0["cost_seconds"] == 0                    # this run really billed nothing
    assert f0["production_seconds"] == 10             # but the shot cost 10s to produce
    assert f0["production_usd"] == 2.0                # 5s draft @ .10 + 5s final @ .30
    assert f0["replayed"] is True

    # The wallet never counts replayed seconds — the judge-mode "$0.00" stays honest.
    assert p.wallet.video_seconds == 0
    assert p.wallet.draft_clips == 0 and p.wallet.final_clips == 0
    assert p.wallet.est_usd == 0.0

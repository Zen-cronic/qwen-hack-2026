"""Gather MEASURED profiling numbers for docs/profiling.md — zero quota.

Runs the REAL pipeline (server/pipeline.py, the metrics ledger, the cost-tiered
cascade, the bounded repair loop) over demo-mode fakes so nothing hits the network
or spends video quota. Everything printed here is a real structural output of the
production code path — call counts per stage, take/repair structure, Tier-A vs
Tier-B check executions, billed vs cached video-seconds — plus a wall-clock timing
of the deterministic Tier-A CV stage.

It is NOT a benchmark of absolute latency or dollars: the demo generators return
fixed synthetic clips, so per-call model latency and cash cost are modeled in
docs/profiling.md, not measured here. What IS measured: the ledger the pipeline
actually writes, and the CPU cost of run_tier_a on a real (synthetic) mp4.

Run:  ~/.pyenv/versions/.qwen-hack/bin/python scripts/profile_demo.py
"""

from __future__ import annotations

import statistics
import sys
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

from server.demo import _write_clip, build_demo_runtime
from server.specs import Assertion, AssertionType, ShotSpec, Tier
from server.store import ProjectState, ProjectStatus
from server.tier_a import run_tier_a


def _run_project(rt, premise: str, pack: str, max_shots: int, timeout: float = 60.0) -> ProjectState:
    """Drive one project through the real pipeline to a terminal state."""
    from server.pipeline import Pipeline

    pid = f"prof{int(time.time()*1000) % 100000}"
    rt.store.create(ProjectState(id=pid, premise=premise, pack=pack, max_shots=max_shots))
    threading.Thread(target=Pipeline(rt.store, pid, rt.deps, rt.cfg).run, daemon=True).start()

    deadline = time.time() + timeout
    approved = False
    while time.time() < deadline:
        p = rt.store.get(pid)
        if not approved and p.status is ProjectStatus.AWAITING_REVIEW:
            rt.store.signal_review(pid)  # release the one human gate
            approved = True
        if p.status in (ProjectStatus.DONE, ProjectStatus.FAILED):
            return p
        time.sleep(0.05)
    raise TimeoutError(f"project {pid} did not finish; last status={p.status.value}")


def _summarize(p: ProjectState) -> dict:
    stage_kinds = Counter(f"{e.stage}/{e.kind.value}" for e in p.ledger)
    billed_seconds = sum(e.video_seconds for e in p.ledger)
    tier_a_checks = tier_b_checks = 0
    take_counts: list[int] = []
    repaired = 0
    for s in p.shots:
        drafts = [t for t in s.takes if t.tier == "draft"]
        take_counts.append(len(s.takes))
        if len(drafts) > 1:
            repaired += 1
        for t in s.takes:
            for r in t.results:
                if r.tier is Tier.TIER_A:
                    tier_a_checks += 1
                elif r.tier is Tier.TIER_B:
                    tier_b_checks += 1
    return {
        "status": p.status.value,
        "shots": len(p.shots),
        "certified": sum(1 for s in p.shots if s.certified),
        "ledger_entries": len(p.ledger),
        "stage_kinds": dict(stage_kinds),
        "wallet": p.wallet.model_dump(),
        "billed_video_seconds": billed_seconds,
        "tier_a_check_executions": tier_a_checks,
        "tier_b_check_executions": tier_b_checks,
        "takes_per_shot": take_counts,
        "shots_repaired": repaired,
    }


def _time_tier_a(iterations: int = 25) -> dict:
    """Real wall-clock CPU cost of the deterministic Tier-A stage on one 5s clip."""
    with tempfile.TemporaryDirectory() as td:
        clip = Path(td) / "clip.mp4"
        _write_clip(clip, "right")  # 5s synthetic pan, same writer the demo uses
        spec = ShotSpec(
            index=0,
            prompt="(timing clip)",
            assertions=[
                Assertion(type=AssertionType.DURATION_BETWEEN, params={"min_s": 4.0, "max_s": 6.0}),
                Assertion(type=AssertionType.BRIGHTNESS_RANGE, params={"min": 25, "max": 235}),
                Assertion(type=AssertionType.FLICKER_BELOW, params={"max_std": 22.0}),
                Assertion(type=AssertionType.SCENE_CUTS, params={"max": 1}),
                Assertion(type=AssertionType.CAMERA_MOTION, params={"direction": "right"}),
                Assertion(type=AssertionType.PALETTE_DELTAE, params={"palette": ["#1f6feb"], "max_delta": 40}),
            ],
        )
        ev = Path(td) / "ev"
        run_tier_a(str(clip), spec, str(ev))  # warm up decode/caches
        samples = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            run_tier_a(str(clip), spec, str(ev))
            samples.append((time.perf_counter() - t0) * 1000)
    return {
        "checks": 6,
        "iterations": iterations,
        "median_ms": round(statistics.median(samples), 1),
        "mean_ms": round(statistics.mean(samples), 1),
        "min_ms": round(min(samples), 1),
        "max_ms": round(max(samples), 1),
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as root:
        rt = build_demo_runtime(data_dir=root)
        premise = "a lonely lighthouse keeper who discovers a message in a bottle"

        cold = _summarize(_run_project(rt, premise, "short_drama", 3))
        warm = _summarize(_run_project(rt, premise, "short_drama", 3))  # same cache dir -> replays

        tier_a = _time_tier_a()

    import json

    print("=" * 68)
    print("MEASURED (demo run) — real pipeline, real ledger, zero quota")
    print("=" * 68)
    print("\n[Cold run — first time these clips are generated]")
    print(json.dumps(cold, indent=2))
    print("\n[Warm run — identical spec, content-addressed cache hits]")
    print(json.dumps(warm, indent=2))
    print("\n[Tier-A CV wall-clock — deterministic, zero-token, per 5s clip]")
    print(json.dumps(tier_a, indent=2))


if __name__ == "__main__":
    main()

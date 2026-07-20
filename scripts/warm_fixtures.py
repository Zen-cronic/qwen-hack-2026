"""Warm the real-video fixture cache (COLD, real quota ~100s per clip), then re-run the
identical pinned prompts to prove the replay bills ZERO video seconds.

Run: ~/.pyenv/versions/.qwen-hack/bin/python scripts/warm_fixtures.py
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

from server.fixtures import PREMISE, build_fixture_runtime
from server.store import ProjectState, ProjectStatus


def _run(rt, label: str, timeout: float = 1800.0) -> ProjectState:
    from server.pipeline import Pipeline

    pid = f"fix{int(time.time() * 1000) % 100000}"
    rt.store.create(ProjectState(id=pid, premise=PREMISE, pack="short_drama", max_shots=3))
    threading.Thread(target=Pipeline(rt.store, pid, rt.deps, rt.cfg).run, daemon=True).start()

    deadline = time.time() + timeout
    approved = False
    last = None
    while time.time() < deadline:
        p = rt.store.get(pid)
        if p.status.value != last:
            last = p.status.value
            print(f"  [{label}] {last}  (+{time.time() - (deadline - timeout):.0f}s)", flush=True)
        if not approved and p.status is ProjectStatus.AWAITING_REVIEW:
            rt.store.signal_review(pid)  # release the one human gate
            approved = True
        if p.status in (ProjectStatus.DONE, ProjectStatus.FAILED):
            return p
        time.sleep(0.5)
    raise TimeoutError(f"{label} run timed out; last status={last}")


def _report(p: ProjectState, label: str) -> None:
    print(f"\n=== {label} RUN — status={p.status.value} ===")
    for s in p.shots:
        print(f"  shot {s.spec.index}  certified={s.certified}")
        for t in s.takes:
            fails = [r.type.value for r in t.results if not r.advisory and r.status.value == "fail"]
            note = f"  BLOCKING FAIL: {', '.join(fails)}" if fails else ""
            cam = next((f"|v|={r.measured.get('magnitude')} {r.measured.get('detected')!r}"
                        for r in t.results if r.type.value == "camera_motion"), "")
            print(f"    take {t.take_no}  {t.tier:5s}  passed={t.passed}  {cam}{note}")
    w = p.wallet
    print(f"  wallet: drafts={w.draft_clips} finals={w.final_clips} images={w.images} "
          f"video_s={w.video_seconds} tokens={w.tokens_in}+{w.tokens_out} est=${w.est_usd:.2f}")


def main() -> None:
    rt = build_fixture_runtime()

    print("COLD RUN — generating any missing real clips (~100s each, real quota)")
    cold = _run(rt, "cold")
    _report(cold, "COLD")

    print("\nWARM RUN — identical pinned prompts; every clip should replay from cache")
    warm = _run(rt, "warm")
    _report(warm, "WARM")

    print("\n" + "=" * 64)
    print(f"billed video-seconds   cold={cold.wallet.video_seconds}   warm={warm.wallet.video_seconds}")
    print(f"shots certified        cold={sum(1 for s in cold.shots if s.certified)}   "
          f"warm={sum(1 for s in warm.shots if s.certified)}")
    if warm.wallet.video_seconds == 0 and cold.wallet.video_seconds >= 0:
        print("CACHE PROOF: the warm run re-certified real video for ZERO video quota.")
    else:
        print(f"WARNING: warm run still billed {warm.wallet.video_seconds}s — a prompt is not pinned.")


if __name__ == "__main__":
    main()

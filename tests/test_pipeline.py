"""Full pipeline state machine with injected fakes — zero quota, real threading."""

import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace

from server.metrics import LedgerWriter
from server.pipeline import Config, Deps, Pipeline
from server.specs import AssertionResult, AssertionType, ShotSpec, Status, Tier
from server.store import ProjectState, ProjectStatus, Store


@dataclass
class FakeRes:
    ok: bool = True
    local_path: str | None = "x.mp4"
    from_cache: bool = False
    seconds: int = 5
    latency_ms: int = 3
    task_id: str = "t"


def _usage(pin=100, pout=40):
    return SimpleNamespace(prompt_tokens=pin, completion_tokens=pout, total_tokens=pin + pout)


class Harness:
    """Configurable fake stages. tier_a fails while the prompt starts with 'BAD'."""

    def __init__(self, max_shots=2, fail_first_shot0=False):
        self.max_shots = max_shots
        self.fail_first_shot0 = fail_first_shot0
        self.n_video = 0
        self.assembled: list[str] | None = None

    def script_fn(self, premise, pack, max_shots):
        shots = [{"prompt": ("BAD shot 0" if (i == 0 and self.fail_first_shot0) else f"shot {i}"),
                  "assertions": []} for i in range(min(max_shots, self.max_shots))]
        return shots, _usage()

    def gen_image_fn(self, prompt):
        return FakeRes(local_path=f"still::{prompt}.png", seconds=0)

    def gen_video_fn(self, prompt, model):
        self.n_video += 1
        return FakeRes(local_path=f"clip::{model}::{prompt}::{self.n_video}.mp4", seconds=5)

    def tier0_fn(self, spec, still_path):
        return []

    def tier_a_fn(self, video_path, spec, evidence_dir):
        # Real Tier-A inspects the RENDERED clip, not the spec. The fake video path
        # encodes the prompt it was generated from, so a repaired retake (new prompt
        # -> new path without 'BAD') passes where the original failed.
        failing = "BAD" in video_path
        status = Status.FAIL if failing else Status.PASS
        return [AssertionResult(type=AssertionType.SCENE_CUTS, tier=Tier.TIER_A, advisory=False,
                                status=status, detail="fake tier_a")]

    def tier_b_fn(self, video_path, spec):
        return [AssertionResult(type=AssertionType.ACTION_COMPLETED, tier=Tier.TIER_B, advisory=True,
                                status=Status.PASS, detail="advisory")]

    def repair_fn(self, spec, failures):
        # Repaired prompt no longer starts with BAD -> tier_a will pass next take.
        return (f"fixed {spec.prompt[4:].strip()}", _usage(80, 20))

    def assemble_fn(self, paths, out_path):
        self.assembled = list(paths)
        return out_path


def _deps(h: Harness, tmp_path) -> Deps:
    return Deps(
        script_fn=h.script_fn, gen_image_fn=h.gen_image_fn, gen_video_fn=h.gen_video_fn,
        tier0_fn=h.tier0_fn, tier_a_fn=h.tier_a_fn, tier_b_fn=h.tier_b_fn,
        repair_fn=h.repair_fn, assemble_fn=h.assemble_fn,
        ledger=LedgerWriter(tmp_path / "ledger.jsonl"),
    )


def _project(store: Store, max_shots=2) -> str:
    store.create(ProjectState(id="p1", premise="a lonely lighthouse", pack="short_drama", max_shots=max_shots))
    return "p1"


def _wait_status(store, pid, status, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if store.get(pid).status is status:
            return True
        time.sleep(0.01)
    return False


def test_happy_path_reaches_done_with_review_gate(tmp_path):
    store = Store(tmp_path / "projects")
    pid = _project(store, max_shots=2)
    h = Harness(max_shots=2)
    pipe = Pipeline(store, pid, _deps(h, tmp_path), Config(data_dir=str(tmp_path / "projects")))

    thread = threading.Thread(target=pipe.run)
    thread.start()

    # It must park at the human gate before spending any video.
    assert _wait_status(store, pid, ProjectStatus.AWAITING_REVIEW)
    assert h.n_video == 0  # no drafts before review
    assert store.get(pid).wallet.draft_clips == 0

    store.signal_review(pid)
    thread.join(timeout=5)
    assert not thread.is_alive()

    p = store.get(pid)
    assert p.status is ProjectStatus.DONE
    assert p.episode_path is not None
    assert all(s.certified for s in p.shots)
    assert h.assembled is not None and len(h.assembled) == 2
    # 2 drafts + 2 finals billed; 2 tier0 stills
    assert (p.wallet.draft_clips, p.wallet.final_clips, p.wallet.images) == (2, 2, 2)


def test_failing_shot_is_repaired_then_certified(tmp_path):
    store = Store(tmp_path / "projects")
    pid = _project(store, max_shots=1)
    h = Harness(max_shots=1, fail_first_shot0=True)
    pipe = Pipeline(store, pid, _deps(h, tmp_path), Config(data_dir=str(tmp_path / "projects")))

    store.signal_review(pid)  # pre-open the gate; run synchronously
    pipe.run()

    p = store.get(pid)
    assert p.status is ProjectStatus.DONE
    shot = p.shots[0]
    assert shot.certified
    draft_takes = [t for t in shot.takes if t.tier == "draft"]
    assert len(draft_takes) == 2               # original (fail) + repaired (pass)
    assert draft_takes[0].passed is False
    assert draft_takes[1].passed is True
    # a repair chat call was logged
    assert any(e.stage == "repairing" for e in p.ledger)


def test_final_failing_tier_a_never_ships(tmp_path):
    """A premium final that regresses on Tier-A must not be certified or assembled.

    The promise is that a shot failing its checks never reaches the channel. _promote
    re-verifies Tier-A on the final, so that FAIL has to gate certification — recording
    it on the take is not enough. The passing draft carries the shot instead, matching
    the fallback the budget and promotion-failure paths already take.
    """
    store = Store(tmp_path / "projects")
    pid = _project(store, max_shots=1)
    h = Harness(max_shots=1)
    cfg = Config(data_dir=str(tmp_path / "projects"))

    # The draft clears Tier-A; the premium re-render regresses on it. The fake clip path
    # encodes the model that made it, so keying on final_model isolates the final.
    def tier_a_fn(video_path, spec, evidence_dir):
        failing = cfg.final_model in video_path
        return [AssertionResult(type=AssertionType.SCENE_CUTS, tier=Tier.TIER_A, advisory=False,
                                status=Status.FAIL if failing else Status.PASS, detail="fake tier_a")]
    h.tier_a_fn = tier_a_fn

    pipe = Pipeline(store, pid, _deps(h, tmp_path), cfg)
    store.signal_review(pid)
    pipe.run()

    p = store.get(pid)
    shot = p.shots[0]

    final_takes = [t for t in shot.takes if t.tier == "final"]
    assert len(final_takes) == 1
    assert final_takes[0].passed is False       # the final really did fail Tier-A

    assert shot.certified                       # the shot still certifies, on the passing draft
    assert shot.final_path is not None
    assert cfg.final_model not in shot.final_path      # the FAILING final is not what ships
    assert cfg.draft_model in shot.final_path          # the passing draft is
    assert h.assembled == [shot.final_path]            # and the episode contains only that


def test_cache_hit_clips_are_free(tmp_path):
    store = Store(tmp_path / "projects")
    pid = _project(store, max_shots=1)
    h = Harness(max_shots=1)
    # Force every video to be a cache hit (seconds=0, from_cache=True).
    h.gen_video_fn = lambda prompt, model: FakeRes(local_path=f"cached::{prompt}.mp4",
                                                   from_cache=True, seconds=0)
    pipe = Pipeline(store, pid, _deps(h, tmp_path), Config(data_dir=str(tmp_path / "projects")))
    store.signal_review(pid)
    pipe.run()

    p = store.get(pid)
    assert p.status is ProjectStatus.DONE
    assert p.wallet.draft_clips == 0 and p.wallet.final_clips == 0  # replays are free
    assert p.wallet.video_seconds == 0

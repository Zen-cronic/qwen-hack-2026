"""Runtime state + thread-safe Store.

Concurrency contract (locked in state.md): a single background pipeline thread
mutates a project's state while the SPA polls `GET /api/projects/{id}` every 2.5s.
So:
  * every mutation runs inside `update()` under an RLock, then writes an ATOMIC
    snapshot (temp file + os.replace) — a poll never sees a half-written state;
  * `get()` returns a deep copy, so a reader can serialize at leisure without the
    pipeline mutating the object under it.

The review gate is a `threading.Event` per project — the ONE human checkpoint,
sitting between tier0 and video spend. Events are runtime-only (not serialized).
"""

from __future__ import annotations

import os
import threading
import time
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from server.metrics import LedgerEntry, Wallet
from server.specs import AssertionResult, ShotSpec


class ProjectStatus(str, Enum):
    QUEUED = "queued"
    SCRIPTING = "scripting"
    TIER0 = "tier0"
    AWAITING_REVIEW = "awaiting_review"  # threading.Event gate — pre-video-spend
    DRAFTING = "drafting"
    VERIFYING = "verifying"
    REPAIRING = "repairing"
    PROMOTING = "promoting"
    ASSEMBLING = "assembling"
    DONE = "done"
    FAILED = "failed"


class TakeStatus(str, Enum):
    QUEUED = "queued"
    GENERATING = "generating"
    DONE = "done"
    FAILED = "failed"


class ShotStatus(str, Enum):
    PENDING = "pending"
    TIER0 = "tier0"
    DRAFTING = "drafting"
    VERIFYING = "verifying"
    REPAIRING = "repairing"
    CERTIFIED = "certified"
    FAILED = "failed"


class Take(BaseModel):
    """One generation attempt of a shot (a draft retry, or a promoted final)."""

    take_no: int
    tier: str  # "draft" | "final"
    model: str
    seed: int | None = None
    prompt: str
    status: TakeStatus = TakeStatus.QUEUED
    task_id: str | None = None
    video_path: str | None = None
    results: list[AssertionResult] = Field(default_factory=list)
    passed: bool | None = None  # all BLOCKING (non-advisory) assertions passed
    created_ts: float = Field(default_factory=time.time)

    def blocking_failures(self) -> list[AssertionResult]:
        from server.specs import Status
        return [r for r in self.results if not r.advisory and r.status is Status.FAIL]


class ShotState(BaseModel):
    spec: ShotSpec
    status: ShotStatus = ShotStatus.PENDING
    still_path: str | None = None  # tier0 pre-render still
    tier0_results: list[AssertionResult] = Field(default_factory=list)
    takes: list[Take] = Field(default_factory=list)
    certified: bool = False
    final_path: str | None = None  # promoted wan2.2-plus clip

    @property
    def latest_take(self) -> Take | None:
        return self.takes[-1] if self.takes else None


class ProjectState(BaseModel):
    """The whole run. model_dump() of this IS the poll payload / conformance report."""

    id: str
    premise: str
    pack: str
    max_shots: int
    custom_checks: list[str] = Field(default_factory=list)  # user-authored plain-language rules
    status: ProjectStatus = ProjectStatus.QUEUED
    created_ts: float = Field(default_factory=time.time)
    updated_ts: float = Field(default_factory=time.time)
    shots: list[ShotState] = Field(default_factory=list)
    ledger: list[LedgerEntry] = Field(default_factory=list)
    wallet: Wallet = Field(default_factory=Wallet)
    episode_path: str | None = None
    error: str | None = None

    def recompute_wallet(self) -> None:
        self.wallet = Wallet.from_entries(self.ledger)


class Store:
    def __init__(self, data_dir: str | os.PathLike[str] = "data/projects"):
        self._lock = threading.RLock()
        self._projects: dict[str, ProjectState] = {}
        self._review_events: dict[str, threading.Event] = {}
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._restore()

    def _restore(self) -> None:
        """Read the snapshots back at boot.

        They used to be write-only: every change was atomically persisted and then dropped
        on restart, so a finished run 404'd from its own state.json while the deployment
        diagram promised "cache + state persist across restarts". The cache did; state
        didn't — and a push to main redeploys the box, so each release silently discarded
        every run a viewer had made.

        A restored run is inert: the pipeline thread that drove it is gone. Terminal runs
        are the ones worth keeping; anything caught mid-flight can never advance again, so
        it is marked failed rather than left to poll forever. A corrupt or half-written
        snapshot is skipped instead of taking the process down at boot.
        """
        for f in sorted(self._dir.glob("*/state.json")):
            try:
                p = ProjectState.model_validate_json(f.read_text())
            except Exception:  # noqa: BLE001 — one bad snapshot must not stop the boot
                continue
            if p.status not in (ProjectStatus.DONE, ProjectStatus.FAILED):
                p.status = ProjectStatus.FAILED
                p.error = "interrupted by a restart — the pipeline thread did not survive it"
            self._projects[p.id] = p
            self._review_events[p.id] = threading.Event()

    def create(self, project: ProjectState) -> ProjectState:
        with self._lock:
            self._projects[project.id] = project
            self._review_events[project.id] = threading.Event()
            self._snapshot(project)
            return project.model_copy(deep=True)

    def get(self, pid: str) -> ProjectState | None:
        with self._lock:
            p = self._projects.get(pid)
            return p.model_copy(deep=True) if p is not None else None

    def ids(self) -> list[str]:
        with self._lock:
            return list(self._projects)

    def update(self, pid: str, mutate) -> ProjectState:
        """Run `mutate(project)` under the lock, bump updated_ts, snapshot, return a copy."""
        with self._lock:
            p = self._projects[pid]
            mutate(p)
            p.updated_ts = time.time()
            self._snapshot(p)
            return p.model_copy(deep=True)

    def review_event(self, pid: str) -> threading.Event:
        with self._lock:
            return self._review_events[pid]

    def signal_review(self, pid: str) -> None:
        self.review_event(pid).set()

    def _snapshot(self, project: ProjectState) -> None:
        """Atomic write — temp file in the same dir, then os.replace."""
        pdir = self._dir / project.id
        pdir.mkdir(parents=True, exist_ok=True)
        final = pdir / "state.json"
        tmp = pdir / f".state.{os.getpid()}.tmp"
        tmp.write_text(project.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, final)

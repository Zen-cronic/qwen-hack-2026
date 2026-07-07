"""Store concurrency contract: isolated reads, atomic snapshots, review gate."""

import json

from server.specs import ShotSpec
from server.store import ProjectState, ProjectStatus, ShotState, Store


def _new(store: Store, pid: str = "p1", max_shots: int = 3) -> None:
    store.create(ProjectState(id=pid, premise="a lonely lighthouse keeper",
                              pack="short_drama", max_shots=max_shots))


def test_get_returns_isolated_deep_copy(tmp_path):
    store = Store(tmp_path / "projects")
    _new(store)
    got = store.get("p1")
    got.status = ProjectStatus.FAILED  # mutate the copy
    assert store.get("p1").status is ProjectStatus.QUEUED  # store is unaffected


def test_update_mutates_and_writes_valid_snapshot(tmp_path):
    store = Store(tmp_path / "projects")
    _new(store, max_shots=1)

    def add_shot(p: ProjectState) -> None:
        p.shots.append(ShotState(spec=ShotSpec(index=0, prompt="a cat on a fence")))
        p.status = ProjectStatus.DRAFTING

    store.update("p1", add_shot)
    got = store.get("p1")
    assert len(got.shots) == 1
    assert got.status is ProjectStatus.DRAFTING

    snap = json.loads((tmp_path / "projects" / "p1" / "state.json").read_text())
    assert snap["status"] == "drafting"
    assert len(snap["shots"]) == 1


def test_review_event_gate(tmp_path):
    store = Store(tmp_path / "projects")
    _new(store)
    assert not store.review_event("p1").is_set()
    store.signal_review("p1")
    assert store.review_event("p1").is_set()


def test_projectstate_is_json_roundtrippable_as_poll_payload(tmp_path):
    p = ProjectState(id="p1", premise="x", pack="short_drama", max_shots=1)
    p.shots.append(ShotState(spec=ShotSpec(index=0, prompt="a cat")))
    payload = p.model_dump(mode="json")  # exactly what GET /api/projects/{id} returns
    assert payload["id"] == "p1"
    ProjectState.model_validate(payload)  # faithful enough to re-load

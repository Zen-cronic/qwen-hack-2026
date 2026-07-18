"""End-to-end HTTP + pipeline via TestClient with fake stages — zero quota."""

import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from server.app import Runtime, create_app
from server.budget import BudgetGovernor
from server.metrics import LedgerWriter
from server.pipeline import Config, Deps
from server.specs import AssertionResult, AssertionType, Status, Tier
from server.store import Store


@dataclass
class FR:
    ok: bool = True
    local_path: str = "data/cache/x.mp4"
    from_cache: bool = False
    seconds: int = 5
    latency_ms: int = 1
    task_id: str = "t"


def _usage():
    return SimpleNamespace(prompt_tokens=100, completion_tokens=30)


class Fakes:
    def __init__(self):
        self.n = 0

    def script(self, premise, pack, max_shots):
        return [{"prompt": f"shot {i}", "assertions": []} for i in range(max_shots)], _usage()

    def gen_image(self, prompt):
        return FR(local_path=f"data/cache/still_{abs(hash(prompt)) % 999}.png", seconds=0)

    def gen_video(self, prompt, model, negative_prompt=None):
        self.n += 1
        return FR(local_path=f"data/cache/clip_{self.n}.mp4", seconds=5)

    def tier_a(self, video, spec, evidence_dir):
        return [AssertionResult(type=AssertionType.SCENE_CUTS, tier=Tier.TIER_A, advisory=False,
                                status=Status.PASS, detail="ok")]

    def assemble(self, paths, out):
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"EP")
        return out


@pytest.fixture
def client(tmp_path):
    f = Fakes()
    deps = Deps(
        script_fn=f.script, gen_image_fn=f.gen_image, gen_video_fn=f.gen_video,
        tier0_fn=lambda spec, still: [], tier_a_fn=f.tier_a, tier_b_fn=lambda v, s: [],
        repair_fn=lambda spec, failures: ("fixed", _usage()), assemble_fn=f.assemble,
        ledger=LedgerWriter(tmp_path / "ledger.jsonl"),
    )
    cfg = Config(data_dir=str(tmp_path / "projects"))
    rt = Runtime(store=Store(str(tmp_path / "projects")), deps=deps, cfg=cfg,
                 governor=BudgetGovernor(judge_mode=False))
    return TestClient(create_app(rt))


def _poll(client, pid, status, timeout=5.0):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        last = client.get(f"/api/projects/{pid}").json()
        if last["status"] == status:
            return last
        time.sleep(0.02)
    raise AssertionError(f"timeout waiting for {status}; last status={last and last['status']}")


def test_packs_lists_short_drama(client):
    names = [p["name"] for p in client.get("/api/packs").json()["packs"]]
    assert "short_drama" in names


def test_full_flow_create_review_done(client):
    r = client.post("/api/projects", json={"premise": "a lonely lighthouse", "pack": "short_drama", "max_shots": 2})
    assert r.status_code == 200
    pid = r.json()["id"]

    _poll(client, pid, "awaiting_review")  # parks at the human gate
    assert client.post(f"/api/projects/{pid}/review").status_code == 200

    done = _poll(client, pid, "done")
    assert done["episode_path"]
    assert all(s["certified"] for s in done["shots"])
    assert done["metrics"]["summary"]["certified"] == 2

    w = client.get("/api/wallet").json()
    assert w["draft_clips"] == 2 and w["final_clips"] == 2
    assert "governor" in w


def test_verdict_override(client):
    pid = client.post("/api/projects", json={"premise": "x", "max_shots": 1}).json()["id"]
    _poll(client, pid, "awaiting_review")
    client.post(f"/api/projects/{pid}/review")
    _poll(client, pid, "done")

    r = client.post(f"/api/projects/{pid}/verdict",
                    json={"shot_index": 0, "assertion_type": "scene_cuts", "verdict": "fail"})
    assert r.status_code == 200
    last = client.get(f"/api/projects/{pid}").json()["shots"][0]["takes"][-1]
    scene = next(x for x in last["results"] if x["type"] == "scene_cuts")
    assert scene["status"] == "fail" and "human override" in scene["detail"]


def test_unknown_project_404(client):
    assert client.get("/api/projects/nope").status_code == 404


def test_unknown_pack_400(client):
    assert client.post("/api/projects", json={"premise": "x", "pack": "ghost"}).status_code == 400


def test_production_factory_demo_mode(tmp_path, monkeypatch):
    """Boot the EXACT factory the container runs (server.app:create_production_app)
    in the EXACT mode the public URL runs (DAILIES_DEMO=1), and drive the real demo
    pipeline — real Tier-A CV + real ffmpeg on synthetic clips — to a certified
    episode. This is the deploy-proving test: no fakes, zero video quota.
    """
    from server import app as app_mod
    from server import demo as demo_mod
    from server.config import settings

    monkeypatch.setattr(settings, "DAILIES_DEMO", True)
    real_build = demo_mod.build_demo_runtime  # redirect writes into tmp so the test is hermetic
    monkeypatch.setattr(demo_mod, "build_demo_runtime", lambda: real_build(data_dir=str(tmp_path / "demo")))

    client = TestClient(app_mod.create_production_app())

    # Readiness probe the compose healthcheck depends on.
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["mode"] == "demo"

    pid = client.post("/api/projects",
                      json={"premise": "a lonely lighthouse", "pack": "short_drama", "max_shots": 3}).json()["id"]
    _poll(client, pid, "awaiting_review", timeout=30)   # parks at the one human gate, pre-video-spend
    client.post(f"/api/projects/{pid}/review")
    done = _poll(client, pid, "done", timeout=90)        # real cv2 clip writes + ffmpeg assembly

    assert done["episode_path"]
    # Planted kill-shot: shot index 1 asserts a rightward pan; the first synthetic
    # draft is static -> Tier-A camera_motion FAILs -> repair -> retake pans right.
    killshot = done["shots"][1]
    assert len(killshot["takes"]) >= 2, "expected a retake after the planted Tier-A failure"
    first_cam = next(r for r in killshot["takes"][0]["results"] if r["type"] == "camera_motion")
    last_cam = next(r for r in killshot["takes"][-1]["results"] if r["type"] == "camera_motion")
    assert first_cam["status"] == "fail" and last_cam["status"] == "pass"


def test_media_serves_stored_paths_whatever_data_dir_is(client, tmp_path, monkeypatch):
    """Regression: the media route stripped a leading "data/" and rejoined onto
    DATA_ROOT, which 404'd every thumbnail whenever DATA_DIR wasn't literally
    "data" (the e2e suite runs DATA_DIR=data/e2e). The contract now: the client
    sends the stored path verbatim; the route resolves it and only requires the
    result to live under DATA_ROOT."""
    import server.app as app_mod

    root = (tmp_path / "data" / "e2e").resolve()
    still = root / "demo" / "cache" / "still.png"
    still.parent.mkdir(parents=True)
    still.write_bytes(b"\x89PNG fake")
    monkeypatch.setattr(app_mod, "DATA_ROOT", root)

    # Absolute stored path (scratch runs) — served.
    assert client.get(f"/api/media/{still}").status_code == 200

    # CWD-relative stored path, exactly as the pipeline records it when
    # DATA_DIR=data/e2e — "data/e2e/…" is the shape the old prefix-stripping
    # rewrote into data/e2e/e2e/… and 404'd. chdir so relative resolution matches
    # the server process's view.
    monkeypatch.chdir(tmp_path)
    assert client.get("/api/media/data/e2e/demo/cache/still.png").status_code == 200

    # A real file OUTSIDE DATA_ROOT — the traversal guard must refuse it.
    outside = tmp_path / "secret.txt"
    outside.write_text("no")
    assert client.get(f"/api/media/{outside}").status_code == 404

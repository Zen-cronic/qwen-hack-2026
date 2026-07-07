"""FastAPI app — the poll payload IS the conformance report.

create_app(runtime) takes an injected Runtime so tests drive the whole HTTP +
pipeline flow with fakes (zero quota); create_production_app() wires the real
Qwen/Wan stages from the environment. Run in prod with:
    uvicorn server.app:create_production_app --factory
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from server.compiler import available_packs, load_pack
from server.config import settings
from server.metrics import LedgerWriter
from server.pipeline import Config, Deps, Pipeline
from server.report import build_report_metrics
from server.specs import AssertionType, Status
from server.store import ProjectState, Store

DATA_ROOT = Path(settings.DATA_DIR).resolve()


@dataclass
class Runtime:
    store: Store
    deps: Deps
    cfg: Config
    governor: object | None = None


class CreateReq(BaseModel):
    premise: str = Field(min_length=1)
    pack: str = "short_drama"
    max_shots: int = Field(default=6, ge=1, le=12)


class VerdictReq(BaseModel):
    shot_index: int
    assertion_type: AssertionType
    verdict: Status


def create_app(runtime: Runtime) -> FastAPI:
    app = FastAPI(title="Dailies — CI for generated video")
    app.state.runtime = runtime

    def rt() -> Runtime:
        return app.state.runtime

    def _require(pid: str) -> ProjectState:
        p = rt().store.get(pid)
        if p is None:
            raise HTTPException(404, "no such project")
        return p

    @app.get("/api/health")
    def health():
        # Readiness probe for the compose healthcheck: returns 200 only once the
        # runtime (opencv/numpy imports, store, deps) is fully wired. Lets `web`
        # gate on `app` being ready instead of merely started.
        return {"status": "ok", "mode": "demo" if settings.DAILIES_DEMO else "real"}

    @app.post("/api/projects")
    def create_project(req: CreateReq):
        try:
            load_pack(req.pack, rt().cfg.packs_dir)
        except Exception:
            raise HTTPException(400, f"unknown pack: {req.pack}")
        pid = uuid.uuid4().hex[:12]
        rt().store.create(ProjectState(id=pid, premise=req.premise, pack=req.pack, max_shots=req.max_shots))
        threading.Thread(target=Pipeline(rt().store, pid, rt().deps, rt().cfg).run, daemon=True).start()
        return {"id": pid}

    @app.get("/api/projects/{pid}")
    def get_project(pid: str):
        p = _require(pid)
        return {**p.model_dump(mode="json"), "metrics": build_report_metrics(p)}

    @app.post("/api/projects/{pid}/review")
    def review(pid: str):
        _require(pid)
        rt().store.signal_review(pid)  # release the one human gate
        return {"ok": True}

    @app.post("/api/projects/{pid}/verdict")
    def verdict(pid: str, req: VerdictReq):
        _require(pid)

        def mut(p: ProjectState) -> None:
            st = p.shots[req.shot_index]
            take = st.takes[-1] if st.takes else None
            if take:
                for r in take.results:
                    if r.type is req.assertion_type:
                        r.status = req.verdict
                        r.detail = (r.detail + " [human override]").strip()

        rt().store.update(pid, mut)
        return {"ok": True}

    @app.post("/api/projects/{pid}/assemble")
    def reassemble(pid: str):
        p = _require(pid)
        paths = [s.final_path for s in p.shots if s.certified and s.final_path]
        if not paths:
            raise HTTPException(400, "no certified shots to assemble")
        out = str(Path(rt().cfg.data_dir) / pid / "episode.mp4")
        episode = rt().deps.assemble_fn(paths, out)  # free re-concat, no tokens
        rt().store.update(pid, lambda pr: setattr(pr, "episode_path", episode))
        return {"episode": episode}

    @app.get("/api/packs")
    def packs():
        out = []
        for name in available_packs(rt().cfg.packs_dir):
            try:
                pk = load_pack(name, rt().cfg.packs_dir)
                out.append({"name": pk.name, "description": pk.description, "defaults": len(pk.defaults)})
            except Exception:
                continue
        return {"packs": out}

    @app.get("/api/wallet")
    def wallet():
        w = rt().deps.ledger.wallet().model_dump()
        if rt().governor is not None:
            w["governor"] = rt().governor.counters()
        return w

    @app.get("/api/media/{path:path}")
    def media(path: str):
        if path.startswith("data/"):
            path = path[len("data/"):]
        fp = (DATA_ROOT / path).resolve()
        try:
            fp.relative_to(DATA_ROOT)  # reject path traversal
        except ValueError:
            raise HTTPException(404)
        if not fp.is_file():
            raise HTTPException(404)
        return FileResponse(str(fp))

    return app


def build_runtime() -> Runtime:
    """Wire the real Qwen/Wan stages from settings."""
    from openai import OpenAI

    from server.assemble import assemble
    from server.budget import BudgetGovernor, governed_gen_video
    from server.repair import RepairAgent
    from server.script import script_and_specs
    from server.tier_a import run_tier_a
    from server.tier_b import TierBVerifier
    from server.wan import WanClient

    api_key = settings.QWEN_API_KEY
    chat_model = settings.QWEN_CHAT_MODEL
    vl_model = settings.VL_MODEL

    llm = OpenAI(api_key=api_key, base_url=settings.QWEN_BASE_URL)
    wan = WanClient(api_key, cache_dir=str(DATA_ROOT / "cache"))
    governor = BudgetGovernor()
    ledger = LedgerWriter(DATA_ROOT / "ledger.jsonl")
    cfg = Config(chat_model=chat_model, vl_model=vl_model, data_dir=str(DATA_ROOT / "projects"))
    tier_b = TierBVerifier(llm, model=vl_model)
    repair = RepairAgent(llm, model=chat_model)

    deps = Deps(
        script_fn=lambda premise, pack, max_shots: script_and_specs(
            premise, pack=pack, max_shots=max_shots, client=llm, model=chat_model),
        gen_image_fn=lambda prompt: wan.generate_image(prompt),
        gen_video_fn=governed_gen_video(wan, governor, final_model=cfg.final_model),
        tier0_fn=lambda spec, still: [],  # Tier-0 still checks are a cut-line item
        tier_a_fn=run_tier_a,
        tier_b_fn=tier_b,
        repair_fn=repair,
        assemble_fn=assemble,
        ledger=ledger,
    )
    return Runtime(store=Store(str(DATA_ROOT / "projects")), deps=deps, cfg=cfg, governor=governor)


def _mount_spa(app: FastAPI) -> None:
    """Serve the built SPA at / if present (single-origin local run; prod uses nginx)."""
    dist = Path(settings.SPA_DIST)
    if dist.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="spa")


def create_production_app() -> FastAPI:
    if settings.DAILIES_DEMO:
        from server.demo import build_demo_runtime
        app = create_app(build_demo_runtime())
    else:
        app = create_app(build_runtime())
    _mount_spa(app)  # mounted AFTER /api routes so it doesn't shadow them
    return app

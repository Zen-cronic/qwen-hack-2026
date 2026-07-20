"""FastAPI app — the poll payload IS the conformance report.

Prod entrypoint: uvicorn server.app:create_production_app --factory
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from server.agent_plan import plan_from_message
from server.compiler import available_packs, load_pack
from server.config import catalog_available, settings
from server.metrics import LedgerWriter
from server.patch import patch_shot
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
    custom_checks: list[str] = Field(default_factory=list)


class VerdictReq(BaseModel):
    shot_index: int
    assertion_type: AssertionType
    verdict: Status


class PlanReq(BaseModel):
    message: str = Field(min_length=1)


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
        # Readiness probe for the compose healthcheck — 200 only once the runtime is wired.
        mode = "demo" if settings.DAILIES_DEMO else "fixtures" if settings.DAILIES_FIXTURES else "real"
        payload = {"status": "ok", "mode": mode, "catalog": "off"}
        if catalog_available():
            # Bounded: a dead DB costs one 5s stall per db.RETRY_COOLDOWN_S window.
            from server import db
            payload["catalog"] = "ok" if db.catalog_ready() else "unreachable"
        return payload

    @app.post("/api/projects")
    def create_project(req: CreateReq):
        try:
            load_pack(req.pack, rt().cfg.packs_dir)
        except Exception:
            raise HTTPException(400, f"unknown pack: {req.pack}")
        pid = uuid.uuid4().hex[:12]
        rt().store.create(ProjectState(id=pid, premise=req.premise, pack=req.pack,
                                       max_shots=req.max_shots, custom_checks=req.custom_checks))
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

    @app.post("/api/projects/{pid}/shots/{shot_index}/patch")
    def patch(pid: str, shot_index: int):
        # Edit one shot without re-running the pipeline.
        _require(pid)
        out = patch_shot(rt().store, pid, shot_index, rt().deps, rt().cfg,
                         model=rt().cfg.patch_model)
        if not out.ok and out.video_path is None and out.anchor_frame is None:
            raise HTTPException(400, out.reason)  # nothing to patch — a client error
        return out.as_dict()

    @app.post("/api/projects/{pid}/assemble")
    def reassemble(pid: str):
        p = _require(pid)
        shipped = [s for s in p.shots if s.certified and s.final_path]
        if not shipped:
            raise HTTPException(400, "no certified shots to assemble")
        out = str(Path(rt().cfg.data_dir) / pid / "episode.mp4")
        # Must narrate through the pipeline's path, or a re-cut silently ships without sound.
        pipe = Pipeline(rt().store, pid, rt().deps, rt().cfg)
        audio = pipe._narrate(shipped)
        paths = [s.final_path for s in shipped]
        episode = (rt().deps.assemble_fn(paths, out, audio_paths=audio) if audio
                   else rt().deps.assemble_fn(paths, out))
        rt().store.update(pid, lambda pr: setattr(pr, "episode_path", episode))
        return {"episode": episode}

    @app.post("/api/agent/plan")
    def agent_plan(req: PlanReq):
        # The agent calls build_pipeline_graph with run params; the server expands the graph.
        demo = settings.DAILIES_DEMO or settings.DAILIES_FIXTURES
        packs = available_packs(rt().cfg.packs_dir)
        plan, transcript = plan_from_message(req.message, demo=demo, packs=packs)
        return {"plan": plan.model_dump(mode="json"), "transcript": transcript}

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
        # The client sends the stored path verbatim; the DATA_ROOT containment check below is
        # the one real security boundary. Local first, then a 302 to a presigned OSS URL.
        fp = Path(path).resolve()
        local_ok = False
        try:
            fp.relative_to(DATA_ROOT)  # reject path traversal
            local_ok = fp.is_file()
        except ValueError:
            pass
        if local_ok:
            return FileResponse(str(fp))
        if catalog_available():
            from server import catalog
            url = catalog.presigned_url_for_path(path)
            if url:
                # max-age must stay well under the presign TTL.
                return RedirectResponse(url, status_code=302,
                                        headers={"Cache-Control": "private, max-age=600"})
        raise HTTPException(404)

    if catalog_available():
        # Import inside the branch so the app boots without psycopg/OSS when the flag is off.
        from server.catalog_api import router as catalog_router
        app.include_router(catalog_router)

    return app


def build_runtime() -> Runtime:
    """Wire the real Qwen/Wan stages from settings."""
    from openai import OpenAI

    from server.assemble import assemble
    from server.budget import BudgetGovernor, governed_gen_video
    from server.repair import RepairAgent
    from server.script import compile_custom_rules, script_and_specs
    from server.tier_a import run_tier_a
    from server.tier_b import TierBVerifier
    from server.tier0 import Tier0Verifier
    from server.tts import TTSClient
    from server.wan import WanClient

    api_key = settings.QWEN_API_KEY
    chat_model = settings.QWEN_CHAT_MODEL
    vl_model = settings.VL_MODEL

    llm = OpenAI(api_key=api_key, base_url=settings.QWEN_BASE_URL)
    wan = WanClient(api_key, cache_dir=str(DATA_ROOT / "cache"))
    tts = TTSClient(api_key, cache_dir=str(DATA_ROOT / "cache"))
    governor = BudgetGovernor()
    ledger = LedgerWriter(DATA_ROOT / "ledger.jsonl")
    cfg = Config(chat_model=chat_model, vl_model=vl_model, data_dir=str(DATA_ROOT / "projects"))
    tier_b = TierBVerifier(llm, model=vl_model)
    tier0 = Tier0Verifier(llm, model=vl_model)
    repair = RepairAgent(llm, model=chat_model)

    deps = Deps(
        script_fn=lambda premise, pack, max_shots: script_and_specs(
            premise, pack=pack, max_shots=max_shots, client=llm, model=chat_model),
        gen_image_fn=lambda prompt: wan.generate_image(prompt),
        gen_video_fn=governed_gen_video(wan, governor, final_model=cfg.final_model),
        tier0_fn=tier0,
        tier_a_fn=run_tier_a,
        tier_b_fn=tier_b,
        repair_fn=repair,
        assemble_fn=assemble,
        ledger=ledger,
        custom_rule_fn=lambda rules: compile_custom_rules(rules, client=llm, model=chat_model),
        # Ungoverned on purpose: frame-anchored repair spends a pool the judge cap doesn't ration.
        patch_video_fn=lambda prompt, model, frame: wan.generate_video_from_frame(
            prompt, frame, model=model),
        # Narration is a finish, not a contract: a failed voice call yields silence.
        narrate_fn=tts.synthesize,
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
    elif settings.DAILIES_FIXTURES:
        # Must be checked before the live runtime — it IS the live runtime with pinned text stages.
        from server.fixtures import build_fixture_runtime
        app = create_app(build_fixture_runtime())
    else:
        app = create_app(build_runtime())
    _mount_spa(app)  # mounted AFTER /api routes so it doesn't shadow them
    return app

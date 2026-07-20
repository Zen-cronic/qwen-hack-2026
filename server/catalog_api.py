"""Catalog read surface + explicit publish knob. Included by create_app only when CATALOG_ENABLED."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from server import catalog, db

router = APIRouter(prefix="/api", tags=["catalog"])


def _require_pool() -> None:
    if db.get_pool() is None:
        raise HTTPException(503, "catalog unavailable (database unreachable)")


@router.get("/catalog/projects")
def catalog_projects():
    _require_pool()
    rows = catalog.list_projects()
    if rows is None:
        raise HTTPException(503, "catalog unavailable (database unreachable)")
    return {"projects": rows}


@router.get("/catalog/projects/{pid}")
def catalog_project(pid: str):
    _require_pool()
    out = catalog.get_project(pid)
    if out is None:
        raise HTTPException(404, "not in the catalog")
    return out


@router.post("/projects/{pid}/publish")
def publish(pid: str, request: Request):
    """Publish (or republish) a live project into the catalog."""
    _require_pool()
    store = request.app.state.runtime.store
    if store.get(pid) is None:
        raise HTTPException(404, "no such project")
    from server.config import settings
    source = ("demo" if settings.DAILIES_DEMO
              else "fixtures" if settings.DAILIES_FIXTURES else "live")
    summary = catalog.safe_publish(store, pid, source=source)
    if summary is None or not summary.get("published"):
        raise HTTPException(503, "publish failed (see server logs)")
    return summary

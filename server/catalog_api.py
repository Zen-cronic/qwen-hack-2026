"""Catalog read surface + explicit publish knob.

Included by create_app ONLY when CATALOG_ENABLED — with the flag off these
routes don't exist (404), and the import never runs. The existing live-run poll
endpoint (GET /api/projects/{pid}) is untouched; the catalog detail endpoint
returns the same poll-payload shape (raw_state verbatim) plus publish metadata,
so anything that can render a live run can render a published one.
"""

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
    """Publish (or republish) a live project into the catalog — the operator
    knob for post-DONE mutations: verdict overrides, patches, re-assembly."""
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

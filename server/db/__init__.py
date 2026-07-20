"""Catalog database access — one lazy psycopg pool, degraded-by-default.

The contract mirrors the demo-cannot-break rule: get_pool() returns None (never
raises) when the catalog is disabled, DATABASE_URL is blank, or Postgres is
unreachable — callers treat None as "catalog unavailable" and no-op. The pool is
sync (psycopg 3): every route in server/app.py is a plain def and the pipeline
runs on a threading.Thread, so an async driver would only add loop-bridging.

Schema is authored as SQLAlchemy models (server/db/models.py) and versioned by
Alembic (`alembic revision --autogenerate`); the first successful pool open runs
`upgrade head` programmatically, so a fresh sidecar becomes usable without a
manual migration step. `alembic upgrade head` from the repo root does the same
by hand. SQLAlchemy stays a schema/migration concern only — runtime queries go
through this psycopg pool.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from psycopg_pool import ConnectionPool

from server.config import settings

log = logging.getLogger("dailies.db")

REPO_ROOT = Path(__file__).resolve().parents[2]
RETRY_COOLDOWN_S = 30.0  # after a failed open, fail fast instead of re-stalling every caller

_lock = threading.Lock()
_pool: ConnectionPool | None = None
_pool_failed = False       # remember a failed open so we warn once, not per call
_last_failure_ts = 0.0


def get_pool() -> ConnectionPool | None:
    """The shared pool, or None when the catalog is off or the DB is unreachable."""
    global _pool, _pool_failed, _last_failure_ts
    if not settings.CATALOG_ENABLED or not settings.DATABASE_URL:
        return None
    if _pool is not None:
        return _pool
    if _pool_failed and (time.monotonic() - _last_failure_ts) < RETRY_COOLDOWN_S:
        return None
    with _lock:
        if _pool is not None:
            return _pool
        if _pool_failed and (time.monotonic() - _last_failure_ts) < RETRY_COOLDOWN_S:
            return None
        try:
            pool = ConnectionPool(
                settings.DATABASE_URL,
                min_size=1,
                max_size=4,
                open=False,
                # A dead DB costs one bounded stall on the first catalog call,
                # never a boot failure and never an unbounded hang.
                timeout=5,
            )
            pool.open(wait=True, timeout=5)
            migrate_to_head()
        except Exception as exc:  # noqa: BLE001 — degrade, never break the app
            if not _pool_failed:
                log.warning("catalog DB unavailable, catalog disabled for now: %s", exc)
            _pool_failed = True
            _last_failure_ts = time.monotonic()
            return None
        _pool = pool
        _pool_failed = False
        log.info("catalog DB pool open (%s)", _redact(settings.DATABASE_URL))
        return _pool


def migrate_to_head() -> None:
    """Programmatic `alembic upgrade head` — idempotent (no-op when current)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    # Keep alembic.ini's [loggers] section from reconfiguring app logging when
    # this runs inside the server process (see alembic/env.py).
    cfg.attributes["skip_logging_setup"] = True
    cfg.attributes["database_url"] = settings.DATABASE_URL
    command.upgrade(cfg, "head")


def catalog_ready() -> bool:
    """Cheap liveness probe for /api/health."""
    pool = get_pool()
    if pool is None:
        return False
    try:
        with pool.connection() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False


def reset_for_tests() -> None:
    """Drop the cached pool so tests can flip settings between cases."""
    global _pool, _pool_failed, _last_failure_ts
    with _lock:
        if _pool is not None:
            _pool.close()
        _pool = None
        _pool_failed = False
        _last_failure_ts = 0.0


def _redact(url: str) -> str:
    """postgresql://user:***@host/db — keep logs credential-free."""
    if "@" in url and "//" in url:
        head, tail = url.split("//", 1)
        if "@" in tail:
            creds, host = tail.rsplit("@", 1)
            user = creds.split(":", 1)[0]
            return f"{head}//{user}:***@{host}"
    return url

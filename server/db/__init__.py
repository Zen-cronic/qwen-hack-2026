"""Catalog database access — one lazy psycopg pool, degraded-by-default (get_pool() never raises).

Schema is authored in server/db/models.py and versioned by Alembic; the first pool open runs
`upgrade head`. Runtime queries go through this psycopg pool, never SQLAlchemy.
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
                # Bounded: a dead DB must never hang a caller or fail boot.
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

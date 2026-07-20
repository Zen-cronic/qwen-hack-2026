"""Catalog publishing — completed runs land in Postgres, media lands in OSS.

The catalog is additive: live runs stay on the in-memory Store + atomic
state.json; publish_project() mirrors a finished ProjectState into relational
rows (media referenced by content sha1 + OSS key) so the fleet of runs is
queryable and its media durable. safe_publish() is the only symbol the pipeline
or API call — it checks the flag, tolerates a dead DB/OSS, and never raises.

Path discipline: state.json stores media paths VERBATIM (CWD-relative like
"data/cache/ab.mp4", or absolute from a foreign machine in old snapshots).
normalize_media_path() maps any of those onto one canonical DATA_ROOT-relative
form, which is what media_paths keys on and what the media route looks up when
the local file is gone. Paths are many-to-one against media_objects: byte-identical
episodes from deterministic runs share one content hash across ~40 project paths,
so the path->hash mapping needs its own table, not a column on the object.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from server import db, oss
from server.config import catalog_available, settings
from server.store import ProjectState, Store

log = logging.getLogger("dailies.catalog")

DATA_ROOT = Path(settings.DATA_DIR).resolve()  # same expression as server/app.py

MIME_BY_EXT = oss.MIME_BY_EXT


def normalize_media_path(p: str | None) -> str | None:
    """Verbatim stored path -> canonical DATA_ROOT-relative posix form, or None.

    Handles the three shapes found in real snapshots: CWD-relative
    ("data/cache/ab.mp4"), absolute under this machine's DATA_ROOT, and absolute
    under a FOREIGN machine's data dir (old snapshots) — mapped via the last
    "/data/" segment. Traversal attempts fail both branches and return None.
    """
    if not p:
        return None
    try:
        return Path(p).resolve().relative_to(DATA_ROOT).as_posix()
    except ValueError:
        pass
    marker = "/data/"
    if marker in p:
        tail = p.rsplit(marker, 1)[1]
        if tail and ".." not in tail.split("/"):
            return tail
    return None


def local_file_for(path: str | None) -> Path | None:
    """The existing local file behind a stored path, or None."""
    norm = normalize_media_path(path)
    if norm is None:
        return None
    fp = DATA_ROOT / norm
    return fp if fp.is_file() else None


def publish_project(state: ProjectState, *, source: str = "live",
                    upload_media: bool = True, media_scope: str = "full") -> dict[str, Any]:
    """Upsert one project into the catalog. Idempotent: republish bumps
    publish_rev and replaces child rows; content-addressed uploads are skipped
    when the object already exists. Missing local files never fail a publish —
    their rows simply carry no sha1/OSS link."""
    pool = db.get_pool()
    if pool is None:
        return {"published": False, "reason": "catalog db unavailable"}

    media = _collect_media(state, media_scope)
    sha_by_path, uploaded, missing = _register_media(pool, media, upload_media)

    raw_state = state.model_dump(mode="json")
    with pool.connection() as conn, conn.transaction():
        conn.execute(
            """
            INSERT INTO projects (id, premise, pack, max_shots, custom_checks,
                                  style_descriptor, status, error, source,
                                  episode_sha1, episode_path, created_at, updated_at, raw_state)
            VALUES (%(id)s, %(premise)s, %(pack)s, %(max_shots)s, %(custom_checks)s,
                    %(style_descriptor)s, %(status)s, %(error)s, %(source)s,
                    %(episode_sha1)s, %(episode_path)s, %(created_at)s, %(updated_at)s, %(raw_state)s)
            ON CONFLICT (id) DO UPDATE SET
                premise = EXCLUDED.premise, pack = EXCLUDED.pack,
                max_shots = EXCLUDED.max_shots, custom_checks = EXCLUDED.custom_checks,
                style_descriptor = EXCLUDED.style_descriptor, status = EXCLUDED.status,
                error = EXCLUDED.error, source = EXCLUDED.source,
                episode_sha1 = EXCLUDED.episode_sha1, episode_path = EXCLUDED.episode_path,
                created_at = EXCLUDED.created_at, updated_at = EXCLUDED.updated_at,
                raw_state = EXCLUDED.raw_state,
                published_at = now(), publish_rev = projects.publish_rev + 1
            """,
            {
                "id": state.id, "premise": state.premise, "pack": state.pack,
                "max_shots": state.max_shots, "custom_checks": Jsonb(state.custom_checks),
                "style_descriptor": state.style_descriptor, "status": state.status.value,
                "error": state.error, "source": source,
                "episode_sha1": sha_by_path.get(state.episode_path),
                "episode_path": state.episode_path,
                "created_at": _dt(state.created_ts), "updated_at": _dt(state.updated_ts),
                "raw_state": Jsonb(raw_state),
            },
        )
        # Children: delete + reinsert under the one transaction is the honest
        # idempotency mechanism — no multi-table conflict-target gymnastics.
        conn.execute("DELETE FROM shots WHERE project_id = %s", (state.id,))
        conn.execute("DELETE FROM cast_members WHERE project_id = %s", (state.id,))
        conn.execute("DELETE FROM ledger_entries WHERE project_id = %s", (state.id,))

        with conn.cursor() as cur:
            for shot in state.shots:
                spec = shot.spec
                cur.execute(
                    """
                    INSERT INTO shots (project_id, shot_index, prompt, negative_prompt,
                                       duration_s, subject, narration, speaker, assertions,
                                       status, certified, still_sha1, still_path,
                                       final_sha1, final_path)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (state.id, spec.index, spec.prompt, spec.negative_prompt,
                     spec.duration_s, spec.subject, spec.narration, spec.speaker,
                     Jsonb([a.model_dump(mode="json") for a in spec.assertions]),
                     shot.status.value, shot.certified,
                     sha_by_path.get(shot.still_path), shot.still_path,
                     sha_by_path.get(shot.final_path), shot.final_path),
                )
                for pos, r in enumerate(shot.tier0_results):
                    _insert_result(cur, state.id, spec.index, None, pos, r, sha_by_path)
                for take in shot.takes:
                    cur.execute(
                        """
                        INSERT INTO takes (project_id, shot_index, take_no, tier, model,
                                           seed, prompt, status, task_id, video_sha1,
                                           video_path, passed, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (state.id, spec.index, take.take_no, take.tier, take.model,
                         take.seed, take.prompt, take.status.value, take.task_id,
                         sha_by_path.get(take.video_path), take.video_path,
                         take.passed, _dt(take.created_ts)),
                    )
                    for pos, r in enumerate(take.results):
                        _insert_result(cur, state.id, spec.index, take.take_no, pos, r, sha_by_path)

            # dict order IS first-appearance order (build_cast, server/tts.py)
            for pos, (speaker, voice) in enumerate(state.cast.items()):
                cur.execute(
                    "INSERT INTO cast_members (project_id, speaker, voice, position)"
                    " VALUES (%s, %s, %s, %s)",
                    (state.id, speaker, voice, pos),
                )
            cur.executemany(
                """
                INSERT INTO ledger_entries (project_id, ts, stage, kind, model, tokens_in,
                                            tokens_out, images, video_seconds, cached_seconds,
                                            latency_ms, shot_index, note)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [(state.id, e.ts, e.stage, e.kind.value, e.model, e.tokens_in,
                  e.tokens_out, e.images, e.video_seconds, e.cached_seconds,
                  e.latency_ms, e.shot_index, e.note) for e in state.ledger],
            )

    summary = {
        "published": True, "project_id": state.id, "source": source,
        "media_seen": len(media), "media_hashed": len(sha_by_path),
        "media_uploaded": uploaded, "media_missing": missing,
        "shots": len(state.shots), "ledger_entries": len(state.ledger),
    }
    log.info("published %s: %s", state.id, summary)
    return summary


def safe_publish(store: Store, pid: str, *, source: str = "live") -> dict[str, Any] | None:
    """The ONLY publish entrypoint for pipeline/API callers: flag-gated,
    swallows everything, never raises into the caller."""
    if not catalog_available():
        return None
    try:
        state = store.get(pid)
        if state is None:
            return None
        return publish_project(state, source=source)
    except Exception as exc:  # noqa: BLE001 — a publish failure must never hurt a run
        log.warning("catalog publish failed for %s: %s", pid, exc)
        return None


def list_projects() -> list[dict[str, Any]] | None:
    pool = db.get_pool()
    if pool is None:
        return None
    with pool.connection() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.premise, p.pack, p.status, p.source, p.error,
                   p.published_at, p.publish_rev, p.created_at,
                   p.episode_sha1 IS NOT NULL OR p.episode_path IS NOT NULL AS has_episode,
                   p.raw_state -> 'wallet' AS wallet,
                   (SELECT count(*) FROM shots s WHERE s.project_id = p.id) AS shots_total,
                   (SELECT count(*) FROM shots s WHERE s.project_id = p.id AND s.certified)
                       AS shots_certified,
                   (SELECT s.still_path FROM shots s WHERE s.project_id = p.id
                        AND s.still_path IS NOT NULL ORDER BY s.shot_index LIMIT 1) AS thumb
            FROM projects p
            ORDER BY p.published_at DESC
            """,
        ).fetchall()
    cols = ("id", "premise", "pack", "status", "source", "error", "published_at",
            "publish_rev", "created_at", "has_episode", "wallet", "shots_total",
            "shots_certified", "thumb")
    return [
        {**dict(zip(cols, r)),
         "published_at": r[6].isoformat(), "created_at": r[8].isoformat()}
        for r in rows
    ]


def get_project(pid: str) -> dict[str, Any] | None:
    """The verbatim published state (poll-payload shape) + publish metadata."""
    pool = db.get_pool()
    if pool is None:
        return None
    with pool.connection() as conn:
        conn.row_factory = dict_row
        row = conn.execute(
            "SELECT raw_state, source, published_at, publish_rev FROM projects WHERE id = %s",
            (pid,),
        ).fetchone()
    if row is None:
        return None
    out = dict(row["raw_state"])
    out["catalog"] = {
        "source": row["source"],
        "published_at": row["published_at"].isoformat(),
        "publish_rev": row["publish_rev"],
    }
    return out


def presigned_url_for_path(path: str) -> str | None:
    """Stored-path -> presigned OSS GET, for media whose local file is gone."""
    norm = normalize_media_path(path)
    if norm is None:
        return None
    pool = db.get_pool()
    if pool is None:
        return None
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT m.oss_key, m.mime FROM media_paths p"
            " JOIN media_objects m ON m.sha1 = p.sha1"
            " WHERE p.local_path = %s AND m.oss_key IS NOT NULL",
            (norm,),
        ).fetchone()
    if row is None:
        return None
    oss_key, mime = row
    return oss.presign_get(oss_key, mime=mime, filename=Path(norm).name)


def _collect_media(state: ProjectState, media_scope: str) -> list[tuple[str, str]]:
    """(verbatim_path, kind) for every media reference in the state.
    media_scope="minimal" drops draft-take videos (the first cut when upload
    time matters); episode/finals/stills/evidence always ship."""
    out: list[tuple[str, str]] = []
    if state.episode_path:
        out.append((state.episode_path, "episode"))
    for shot in state.shots:
        if shot.still_path:
            out.append((shot.still_path, "image"))
        if shot.final_path:
            out.append((shot.final_path, "video"))
        for r in shot.tier0_results:
            out.extend((e, "evidence") for e in r.evidence)
        for take in shot.takes:
            if take.video_path and not (media_scope == "minimal" and take.tier == "draft"):
                out.append((take.video_path, "video"))
            for r in take.results:
                out.extend((e, "evidence") for e in r.evidence)
    return out


def _register_media(pool, media: list[tuple[str, str]],
                    upload_media: bool) -> tuple[dict[str, str], int, int]:
    """Hash + upsert media_objects (+ optional OSS upload) for every existing
    file. Returns ({verbatim_path: sha1}, uploaded_count, missing_count)."""
    sha_by_path: dict[str, str] = {}
    sha_by_norm: dict[str, str] = {}
    uploaded = 0
    missing = 0
    with pool.connection() as conn:
        for verbatim, kind in media:
            norm = normalize_media_path(verbatim)
            if norm is None:
                missing += 1
                continue
            if norm in sha_by_norm:
                sha_by_path[verbatim] = sha_by_norm[norm]
                continue
            fp = DATA_ROOT / norm
            if not fp.is_file():
                missing += 1
                continue
            data = fp.read_bytes()
            sha1 = hashlib.sha1(data).hexdigest()
            mime = MIME_BY_EXT.get(fp.suffix.lower(), "application/octet-stream")
            oss_key = oss.upload(sha1, fp, mime=mime) if upload_media else None
            if oss_key:
                uploaded += 1
            conn.execute(
                """
                INSERT INTO media_objects (sha1, kind, mime, size_bytes, oss_key, uploaded_at)
                VALUES (%s, %s, %s, %s, %s, CASE WHEN %s::text IS NULL THEN NULL ELSE now() END)
                ON CONFLICT (sha1) DO UPDATE SET
                    oss_key = COALESCE(media_objects.oss_key, EXCLUDED.oss_key),
                    uploaded_at = COALESCE(media_objects.uploaded_at, EXCLUDED.uploaded_at)
                """,
                (sha1, kind, mime, len(data), oss_key, oss_key),
            )
            # Every path that resolves to these bytes gets its own row: byte-identical
            # episodes across deterministic runs share one object but keep their paths.
            conn.execute(
                "INSERT INTO media_paths (local_path, sha1) VALUES (%s, %s)"
                " ON CONFLICT (local_path) DO UPDATE SET sha1 = EXCLUDED.sha1",
                (norm, sha1),
            )
            sha_by_norm[norm] = sha1
            sha_by_path[verbatim] = sha1
    return sha_by_path, uploaded, missing


def _insert_result(cur, pid: str, shot_index: int, take_no: int | None, position: int,
                   r, sha_by_path: dict[str, str]) -> None:
    cur.execute(
        """
        INSERT INTO assertion_results (project_id, shot_index, take_no, position, type,
                                       tier, advisory, status, detail, measured, params, evidence)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (pid, shot_index, take_no, position, r.type.value, r.tier.value, r.advisory,
         r.status.value, r.detail, Jsonb(r.measured), Jsonb(r.params),
         Jsonb([{"path": e, "sha1": sha_by_path.get(e)} for e in r.evidence])),
    )


def _dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)

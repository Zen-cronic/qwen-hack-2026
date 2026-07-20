"""Backfill the catalog from existing state.json snapshots (plan step 5).

Walks data/projects (source=live) and data/demo/projects (source=demo), parses
each state.json with the same Pydantic model + terminal rule as Store._restore
(old drifted snapshots backfill missing fields like cast/speaker; non-terminal
statuses become failed), then publishes each project — media uploads included
unless --no-media.

Idempotent by construction: publish_project upserts (publish_rev climbs) and
OSS uploads are content-addressed skip-if-exists. Re-running converges.

Usage:
    CATALOG_ENABLED=1 python scripts/seed_catalog.py --dry-run
    CATALOG_ENABLED=1 python scripts/seed_catalog.py
    ... --only fix96788        one project id
    ... --no-media             rows only, no OSS uploads
    ... --dirs data/projects   restrict the walk
    ... --global-ledger        also import unattributable data/ledger.jsonl strays

On the box (DB has no public port): docker compose exec app python scripts/seed_catalog.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import catalog, db
from server.config import settings
from server.store import ProjectState, ProjectStatus

DEFAULT_DIRS = {
    "data/projects": "live",
    "data/demo/projects": "demo",
}


def load_state(f: Path) -> ProjectState | None:
    try:
        p = ProjectState.model_validate_json(f.read_text())
    except Exception as exc:  # noqa: BLE001 — one bad snapshot must not stop the seed
        print(f"  SKIP {f}: {exc.__class__.__name__}: {exc}")
        return None
    # Mirror Store._restore's terminal rule: a restored run is inert.
    if p.status not in (ProjectStatus.DONE, ProjectStatus.FAILED):
        p.status = ProjectStatus.FAILED
        p.error = "interrupted by a restart — the pipeline thread did not survive it"
    return p


def seed_global_ledger(dry_run: bool) -> int:
    """Optional: import global ledger.jsonl rows with project_id NULL, deduped
    on the float ts (effectively unique). Embedded per-project ledgers are the
    attributable record — this only preserves unattributed history."""
    from server.metrics import LedgerEntry

    src = Path(settings.DATA_DIR) / "ledger.jsonl"
    if not src.is_file():
        print(f"global ledger: {src} not found, skipping")
        return 0
    entries = []
    for line in src.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entries.append(LedgerEntry.model_validate(json.loads(line)))
        except Exception:  # noqa: BLE001
            continue
    if dry_run:
        print(f"global ledger: {len(entries)} parseable rows (dry-run, not written)")
        return 0
    pool = db.get_pool()
    if pool is None:
        return 0
    inserted = 0
    with pool.connection() as conn, conn.transaction():
        existing = {r[0] for r in conn.execute(
            "SELECT ts FROM ledger_entries WHERE project_id IS NULL").fetchall()}
        for e in entries:
            if e.ts in existing:
                continue
            conn.execute(
                """
                INSERT INTO ledger_entries (project_id, ts, stage, kind, model, tokens_in,
                                            tokens_out, images, video_seconds, cached_seconds,
                                            latency_ms, shot_index, note)
                VALUES (NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (e.ts, e.stage, e.kind.value, e.model, e.tokens_in, e.tokens_out,
                 e.images, e.video_seconds, e.cached_seconds, e.latency_ms,
                 e.shot_index, e.note),
            )
            inserted += 1
    print(f"global ledger: {inserted} new rows (of {len(entries)} parsed)")
    return inserted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="parse + report only; no DB writes, no uploads")
    ap.add_argument("--no-media", action="store_true", help="skip OSS uploads")
    ap.add_argument("--only", metavar="PID", help="seed a single project id")
    ap.add_argument("--dirs", nargs="*", metavar="DIR",
                    help=f"project dirs to walk (default: {list(DEFAULT_DIRS)})")
    ap.add_argument("--global-ledger", action="store_true",
                    help="also import unattributable data/ledger.jsonl strays")
    args = ap.parse_args()

    dirs = {d: DEFAULT_DIRS.get(d, "seed") for d in args.dirs} if args.dirs else DEFAULT_DIRS

    if not settings.CATALOG_ENABLED:
        print("CATALOG_ENABLED is off — set CATALOG_ENABLED=1 (and DATABASE_URL) to seed")
        return 2
    if not args.dry_run and db.get_pool() is None:
        print(f"cannot reach the catalog DB at DATABASE_URL — is the sidecar up?")
        return 2

    totals = {"seen": 0, "published": 0, "skipped": 0, "media_uploaded": 0, "media_missing": 0}
    for d, source in dirs.items():
        root = Path(d)
        if not root.is_dir():
            print(f"{d}: not a directory, skipping")
            continue
        snapshots = sorted(root.glob("*/state.json"))
        print(f"{d} ({source}): {len(snapshots)} snapshots")
        for f in snapshots:
            state = load_state(f)
            if state is None:
                totals["skipped"] += 1
                continue
            if args.only and state.id != args.only:
                continue
            totals["seen"] += 1
            media = catalog._collect_media(state, "full")
            missing = sum(1 for p, _ in media if catalog.local_file_for(p) is None)
            if args.dry_run:
                print(f"  {state.id}: status={state.status.value} shots={len(state.shots)} "
                      f"ledger={len(state.ledger)} media={len(media)} (missing {missing})")
                totals["media_missing"] += missing
                continue
            summary = catalog.publish_project(
                state, source=source, upload_media=not args.no_media)
            if summary.get("published"):
                totals["published"] += 1
                totals["media_uploaded"] += summary["media_uploaded"]
                totals["media_missing"] += summary["media_missing"]
                print(f"  {state.id}: rev={summary['shots']} shots, "
                      f"{summary['media_uploaded']} uploaded, {summary['media_missing']} missing")
            else:
                totals["skipped"] += 1
                print(f"  {state.id}: NOT published ({summary.get('reason')})")

    if args.global_ledger:
        seed_global_ledger(args.dry_run)

    print(f"\ntotals: {totals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

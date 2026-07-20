"""Catalog schema as SQLAlchemy models — the source Alembic autogenerates from.

Schema/migration definition only; runtime queries go through the psycopg pool in
server/db/__init__.py. The project_wallets VIEW below is applied by the initial migration.
"""

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, Double, ForeignKey,
    ForeignKeyConstraint, Identity, Index, Integer, Text, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()

PROJECT_STATUSES = ("queued", "scripting", "tier0", "awaiting_review", "drafting",
                    "verifying", "repairing", "promoting", "assembling", "done", "failed")
SHOT_STATUSES = ("pending", "tier0", "drafting", "verifying", "repairing", "certified", "failed")
TAKE_STATUSES = ("queued", "generating", "done", "failed")
TAKE_TIERS = ("draft", "final", "repair", "patch")
RESULT_STATUSES = ("pending", "pass", "fail", "inconclusive")
TIERS = ("tier0", "tier_a", "tier_b")
SOURCES = ("live", "demo", "fixtures", "seed")
MEDIA_KINDS = ("video", "image", "audio", "episode", "evidence")
ASSERTION_TYPES = ("duration_between", "brightness_range", "flicker_below", "scene_cuts",
                   "camera_motion", "palette_deltae", "subject_present", "identity_consistent",
                   "action_completed", "title_card_present")


def _in(values: tuple[str, ...], col: str) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{col} IN ({quoted})"


class MediaObject(Base):
    """One row per distinct CONTENT hash; paths live in media_paths (many-to-one)."""

    __tablename__ = "media_objects"

    sha1 = Column(Text, primary_key=True)
    kind = Column(Text, nullable=False)
    mime = Column(Text, nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    oss_key = Column(Text, unique=True, nullable=True)
    uploaded_at = Column(DateTime(True), nullable=True)

    __table_args__ = (
        CheckConstraint("sha1 ~ '^[0-9a-f]{40}$'", name="ck_media_sha1_hex"),
        CheckConstraint(_in(MEDIA_KINDS, "kind"), name="ck_media_kind"),
    )


class MediaPath(Base):
    """Normalized DATA_ROOT-relative path -> content hash; what the media route resolves against."""

    __tablename__ = "media_paths"

    local_path = Column(Text, primary_key=True)
    sha1 = Column(Text, ForeignKey("media_objects.sha1", ondelete="CASCADE"), nullable=False)

    __table_args__ = (Index("ix_media_paths_sha1", "sha1"),)


class Project(Base):
    __tablename__ = "projects"

    id = Column(Text, primary_key=True)
    premise = Column(Text, nullable=False)
    pack = Column(Text, nullable=False)
    max_shots = Column(Integer, nullable=False)
    custom_checks = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    style_descriptor = Column(Text, nullable=False, server_default=text("''"))
    status = Column(Text, nullable=False)
    error = Column(Text, nullable=True)
    source = Column(Text, nullable=False, server_default=text("'live'"))
    episode_sha1 = Column(Text, ForeignKey("media_objects.sha1"), nullable=True)
    episode_path = Column(Text, nullable=True)
    created_at = Column(DateTime(True), nullable=False)
    updated_at = Column(DateTime(True), nullable=False)
    published_at = Column(DateTime(True), nullable=False, server_default=text("now()"))
    publish_rev = Column(Integer, nullable=False, server_default=text("1"))
    raw_state = Column(JSONB, nullable=False)

    __table_args__ = (
        CheckConstraint(_in(PROJECT_STATUSES, "status"), name="ck_projects_status"),
        CheckConstraint(_in(SOURCES, "source"), name="ck_projects_source"),
    )


class Shot(Base):
    __tablename__ = "shots"

    project_id = Column(Text, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    shot_index = Column(Integer, primary_key=True)
    prompt = Column(Text, nullable=False)
    negative_prompt = Column(Text, nullable=True)
    duration_s = Column(Integer, nullable=False, server_default=text("5"))
    subject = Column(Text, nullable=True)
    narration = Column(Text, nullable=True)
    speaker = Column(Text, nullable=True)
    assertions = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    status = Column(Text, nullable=False)
    certified = Column(Boolean, nullable=False, server_default=text("false"))
    still_sha1 = Column(Text, ForeignKey("media_objects.sha1"), nullable=True)
    still_path = Column(Text, nullable=True)
    final_sha1 = Column(Text, ForeignKey("media_objects.sha1"), nullable=True)
    final_path = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(_in(SHOT_STATUSES, "status"), name="ck_shots_status"),
    )


class Take(Base):
    __tablename__ = "takes"

    project_id = Column(Text, primary_key=True)
    shot_index = Column(Integer, primary_key=True)
    take_no = Column(Integer, primary_key=True)
    tier = Column(Text, nullable=False)
    model = Column(Text, nullable=False)
    seed = Column(BigInteger, nullable=True)
    prompt = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    task_id = Column(Text, nullable=True)
    video_sha1 = Column(Text, ForeignKey("media_objects.sha1"), nullable=True)
    video_path = Column(Text, nullable=True)
    passed = Column(Boolean, nullable=True)
    created_at = Column(DateTime(True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(["project_id", "shot_index"],
                             ["shots.project_id", "shots.shot_index"], ondelete="CASCADE"),
        CheckConstraint(_in(TAKE_TIERS, "tier"), name="ck_takes_tier"),
        CheckConstraint(_in(TAKE_STATUSES, "status"), name="ck_takes_status"),
    )


class AssertionResult(Base):
    __tablename__ = "assertion_results"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    project_id = Column(Text, nullable=False)
    shot_index = Column(Integer, nullable=False)
    take_no = Column(Integer, nullable=True)  # NULL = shot-level tier0 result
    position = Column(Integer, nullable=False)
    type = Column(Text, nullable=False)
    tier = Column(Text, nullable=False)
    advisory = Column(Boolean, nullable=False)
    status = Column(Text, nullable=False)
    detail = Column(Text, nullable=False, server_default=text("''"))
    measured = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    params = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    evidence = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))

    __table_args__ = (
        ForeignKeyConstraint(["project_id", "shot_index"],
                             ["shots.project_id", "shots.shot_index"], ondelete="CASCADE"),
        CheckConstraint(_in(ASSERTION_TYPES, "type"), name="ck_ar_type"),
        CheckConstraint(_in(TIERS, "tier"), name="ck_ar_tier"),
        CheckConstraint(_in(RESULT_STATUSES, "status"), name="ck_ar_status"),
        Index("ix_ar_lookup", "project_id", "shot_index", "take_no"),
        Index("ix_ar_type_status", "type", "status"),
    )


class CastMember(Base):
    __tablename__ = "cast_members"

    project_id = Column(Text, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    speaker = Column(Text, primary_key=True)
    voice = Column(Text, nullable=False)  # closed roster (server/tts.py) but env-tunable — no CHECK
    position = Column(Integer, nullable=False)  # order of first appearance (build_cast contract)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id = Column(BigInteger, Identity(always=True), primary_key=True)
    # NULL only for unattributable strays imported from the global ledger.jsonl
    project_id = Column(Text, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    ts = Column(Double, nullable=False)  # raw epoch, as recorded; query via to_timestamp(ts)
    stage = Column(Text, nullable=False)
    kind = Column(Text, nullable=False)
    model = Column(Text, nullable=False)
    tokens_in = Column(Integer, nullable=False, server_default=text("0"))
    tokens_out = Column(Integer, nullable=False, server_default=text("0"))
    images = Column(Integer, nullable=False, server_default=text("0"))
    video_seconds = Column(Integer, nullable=False, server_default=text("0"))
    cached_seconds = Column(Integer, nullable=False, server_default=text("0"))
    latency_ms = Column(Integer, nullable=False, server_default=text("0"))
    shot_index = Column(Integer, nullable=True)
    note = Column(Text, nullable=False, server_default=text("''"))

    __table_args__ = (
        CheckConstraint(
            _in(("chat", "vlm", "image", "video_draft", "video_final", "video_patch", "audio"),
                "kind"),
            name="ck_ledger_kind"),
        Index("ix_ledger_project_ts", "project_id", "ts"),
    )


# Must mirror Wallet.from_entries (server/metrics.py): a clip counts only when
# video_seconds > 0. Applied by the initial migration via op.execute.
PROJECT_WALLETS_VIEW = """
CREATE VIEW project_wallets AS
SELECT project_id,
       sum(tokens_in)     AS tokens_in,
       sum(tokens_out)    AS tokens_out,
       sum(images)        AS images,
       sum(video_seconds) AS video_seconds,
       count(*) FILTER (WHERE kind = 'video_draft' AND video_seconds > 0) AS draft_clips,
       count(*) FILTER (WHERE kind = 'video_final' AND video_seconds > 0) AS final_clips,
       count(*) FILTER (WHERE kind = 'video_patch' AND video_seconds > 0) AS patch_clips
FROM ledger_entries
WHERE project_id IS NOT NULL
GROUP BY project_id;
"""

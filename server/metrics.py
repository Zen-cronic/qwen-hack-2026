"""Metrics ledger — every Qwen/Wan call appends a LedgerEntry (stage, model, spend, latency).

Prices here are NOMINAL list-price estimates, not free-tier cost; the wallet rations quota units.
"""

from __future__ import annotations

import json
import os
import threading
import time
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class ResourceKind(str, Enum):
    CHAT = "chat"            # qwen-plus scripting / repair
    VLM = "vlm"              # qwen-vl tier_b verdicts
    IMAGE = "image"          # tier0 t2i still
    VIDEO_DRAFT = "video_draft"   # wan2.1-t2v-turbo
    VIDEO_FINAL = "video_final"   # wan2.2-t2v-plus
    VIDEO_PATCH = "video_patch"   # wan i2v/kf2v targeted repair — its own free-tier pool
    AUDIO = "audio"          # qwen3-tts narration for the episode


# Nominal $/unit (list-price estimates, NOT free-tier cost). Tune freely.
_PRICE_PER_1K_IN = {ResourceKind.CHAT: 0.0004, ResourceKind.VLM: 0.0008}
_PRICE_PER_1K_OUT = {ResourceKind.CHAT: 0.0012, ResourceKind.VLM: 0.0020}
_PRICE_PER_IMAGE = 0.02
_PRICE_PER_VIDEO_SECOND = {ResourceKind.VIDEO_DRAFT: 0.10, ResourceKind.VIDEO_FINAL: 0.30,
                           ResourceKind.VIDEO_PATCH: 0.10}


class LedgerEntry(BaseModel):
    ts: float
    stage: str                       # scripting | tier0 | drafting | verifying | repairing | promoting | ...
    kind: ResourceKind
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    images: int = 0
    video_seconds: int = 0
    cached_seconds: int = 0          # billed on a prior run; never counted by the wallet
    latency_ms: int = 0
    shot_index: int | None = None
    note: str = ""

    @property
    def est_usd(self) -> float:
        c = 0.0
        c += _PRICE_PER_1K_IN.get(self.kind, 0.0) * self.tokens_in / 1000
        c += _PRICE_PER_1K_OUT.get(self.kind, 0.0) * self.tokens_out / 1000
        c += _PRICE_PER_IMAGE * self.images
        c += _PRICE_PER_VIDEO_SECOND.get(self.kind, 0.0) * self.video_seconds
        return round(c, 6)

    @property
    def modeled_usd(self) -> float:
        """est_usd plus this entry's cache-replayed seconds — production cost, not marginal.
        The frontier charts this; the wallet never does."""
        c = self.est_usd + _PRICE_PER_VIDEO_SECOND.get(self.kind, 0.0) * self.cached_seconds
        return round(c, 6)


class Wallet(BaseModel):
    """Aggregate quota consumption — the persistent meter + frontier denominator."""

    draft_clips: int = 0
    final_clips: int = 0
    patch_clips: int = 0     # i2v/kf2v repairs — a separate free-tier pool from t2v
    images: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    video_seconds: int = 0
    est_usd: float = 0.0

    @classmethod
    def from_entries(cls, entries: list[LedgerEntry]) -> "Wallet":
        w = cls()
        for e in entries:
            w.tokens_in += e.tokens_in
            w.tokens_out += e.tokens_out
            w.images += e.images
            w.video_seconds += e.video_seconds
            # A clip counts against quota only if it was actually billed (seconds > 0).
            if e.video_seconds > 0:
                if e.kind is ResourceKind.VIDEO_DRAFT:
                    w.draft_clips += 1
                elif e.kind is ResourceKind.VIDEO_FINAL:
                    w.final_clips += 1
                elif e.kind is ResourceKind.VIDEO_PATCH:
                    w.patch_clips += 1
            w.est_usd += e.est_usd
        w.est_usd = round(w.est_usd, 6)
        return w


class LedgerWriter:
    """Thread-safe recorder — the lock guards both the in-memory list and the JSONL append."""

    def __init__(self, jsonl_path: str | os.PathLike[str] | None = None):
        self._lock = threading.Lock()
        self._entries: list[LedgerEntry] = []
        self._path = Path(jsonl_path) if jsonl_path else None
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        stage: str,
        kind: ResourceKind,
        model: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        images: int = 0,
        video_seconds: int = 0,
        cached_seconds: int = 0,
        latency_ms: int = 0,
        shot_index: int | None = None,
        note: str = "",
    ) -> LedgerEntry:
        entry = LedgerEntry(
            ts=time.time(),
            stage=stage,
            kind=kind,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            images=images,
            video_seconds=video_seconds,
            cached_seconds=cached_seconds,
            latency_ms=latency_ms,
            shot_index=shot_index,
            note=note,
        )
        with self._lock:
            self._entries.append(entry)
            if self._path:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(entry.model_dump_json() + "\n")
        return entry

    def entries(self) -> list[LedgerEntry]:
        with self._lock:
            return list(self._entries)

    def wallet(self) -> Wallet:
        return Wallet.from_entries(self.entries())

"""The assertion compiler: pack defaults + per-shot dynamic assertions -> ShotSpecs.

Merge rule: a shot-specific assertion overrides a pack default of the SAME type. Everything
runs through the closed-vocabulary validator here, before any video spend.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from server.config import settings
from server.specs import Assertion, ShotSpec, parse_assertions


@dataclass
class Pack:
    name: str
    description: str
    defaults: list[Assertion]


def _packs_dir(packs_dir: str | os.PathLike[str] | None) -> Path:
    return Path(packs_dir or settings.PACKS_DIR)


def available_packs(packs_dir: str | os.PathLike[str] | None = None) -> list[str]:
    d = _packs_dir(packs_dir)
    return sorted(p.stem for p in d.glob("*.yaml")) if d.is_dir() else []


def load_pack(name: str, packs_dir: str | os.PathLike[str] | None = None) -> Pack:
    path = _packs_dir(packs_dir) / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"pack not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = parse_assertions(data.get("defaults", []))  # rejects a malformed pack at load
    return Pack(name=data.get("name", name), description=(data.get("description") or "").strip(), defaults=defaults)


def merge_assertions(defaults: list[Assertion], dynamic: list[Assertion]) -> list[Assertion]:
    overridden = {a.type for a in dynamic}
    kept_defaults = [d for d in defaults if d.type not in overridden]
    return kept_defaults + dynamic


def compile_shots(
    raw_shots: list[dict], pack: Pack, extra_defaults: list[Assertion] | None = None
) -> list[ShotSpec]:
    """Validate + merge raw shot dicts into ShotSpecs. Precedence: shot-specific >
    `extra_defaults` (user-authored, every shot) > pack default."""
    base_defaults = merge_assertions(pack.defaults, extra_defaults or [])
    specs: list[ShotSpec] = []
    for i, rs in enumerate(raw_shots):
        if "prompt" not in rs:
            raise ValueError(f"shot[{i}] missing prompt")
        try:
            dynamic = parse_assertions(rs.get("assertions", []) or [])
        except ValueError as exc:
            raise ValueError(f"shot[{i}] {exc}") from exc
        specs.append(
            ShotSpec(
                index=i,
                prompt=rs["prompt"],
                negative_prompt=rs.get("negative_prompt"),
                subject=rs.get("subject"),
                narration=rs.get("narration"),
                speaker=rs.get("speaker"),
                assertions=merge_assertions(base_defaults, dynamic),
            )
        )
    return specs

"""Narration track — qwen3-tts-flash on the SYNCHRONOUS multimodal-generation route, cached
by sha1(model|voice|text).

`voice` is REQUIRED (omitting it is a 400), and the result URL expires, so download at once.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from server.config import settings

TTS_URL = f"{settings.DASHSCOPE_BASE_URL}/api/v1/services/aigc/multimodal-generation/generation"
DEFAULT_VOICE = "Cherry"
DEFAULT_MODEL = "qwen3-tts-flash"

# Closed roster: an unlicensed voice is a 400. Every name below was probed live against
# this account — do not add one unverified.
NARRATOR_VOICE = DEFAULT_VOICE
CAST_VOICES = ("Ethan", "Serena", "Dylan", "Jada", "Ryan", "Katerina", "Elias", "Chelsie")


def build_cast(specs) -> dict[str, str]:
    """Map each speaking character to a voice by order of first appearance — deterministic,
    so a re-run casts identically and every narration cache key still hits."""
    cast: dict[str, str] = {}
    for spec in specs:
        who = (getattr(spec, "speaker", None) or "").strip()
        if who and who not in cast:
            cast[who] = CAST_VOICES[len(cast) % len(CAST_VOICES)]
    return cast


def voice_for(spec, cast: dict[str, str] | None) -> str:
    """The voice this shot is spoken in — the character's, or the narrator's."""
    who = (getattr(spec, "speaker", None) or "").strip()
    return (cast or {}).get(who, NARRATOR_VOICE)


@dataclass
class TTSResult:
    status: str
    local_path: str | None = None
    from_cache: bool = False
    latency_ms: int = 0
    chars: int = 0
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "SUCCEEDED" and self.local_path is not None


def narration_key(model: str, voice: str, text: str) -> str:
    return hashlib.sha1(f"{model}|{voice}|{text}".encode("utf-8")).hexdigest()


class TTSClient:
    def __init__(self, api_key: str, *, cache_dir: str | os.PathLike[str] = "data/cache",
                 model: str = DEFAULT_MODEL, voice: str = DEFAULT_VOICE,
                 http: httpx.Client | None = None, timeout: float = 90.0):
        if not api_key:
            raise ValueError("TTSClient needs an api_key")
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.voice = voice
        self._http = http or httpx.Client(timeout=timeout)

    def synthesize(self, text: str, *, voice: str | None = None) -> TTSResult:
        text = (text or "").strip()
        if not text:
            return TTSResult(status="FAILED", message="nothing to say")
        voice = voice or self.voice

        dest = self.cache_dir / f"{narration_key(self.model, voice, text)}.wav"
        if dest.exists():
            return TTSResult(status="SUCCEEDED", local_path=str(dest), from_cache=True,
                             chars=len(text))

        t0 = time.monotonic()
        try:
            r = self._http.post(
                TTS_URL,
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json={"model": self.model, "input": {"text": text, "voice": voice}},
            )
        except Exception as exc:  # noqa: BLE001 — a silent episode beats a failed run
            return TTSResult(status="FAILED", message=f"{type(exc).__name__}: {exc}")

        latency = int((time.monotonic() - t0) * 1000)
        payload = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code != 200:
            return TTSResult(status="FAILED", latency_ms=latency,
                             message=f"{payload.get('code')}: {payload.get('message')}")

        url = ((payload.get("output") or {}).get("audio") or {}).get("url")
        if not url:
            return TTSResult(status="FAILED", latency_ms=latency,
                             message=f"no audio url in output: {str(payload)[:180]}")

        try:
            audio = self._http.get(url)
            audio.raise_for_status()
            dest.write_bytes(audio.content)
        except Exception as exc:  # noqa: BLE001
            return TTSResult(status="FAILED", latency_ms=latency,
                             message=f"download failed: {exc}")

        return TTSResult(status="SUCCEEDED", local_path=str(dest), latency_ms=latency,
                         chars=len(text))


# The assembler truncates audio at the clip length, so anything over this budget is cut
# off mid-word in the finished episode.
WORDS_PER_SECOND = 2.6


def _fit(text: str, budget: int) -> str:
    """Trim to the word budget and close the sentence."""
    words = text.split()
    if len(words) > budget:
        text = " ".join(words[:budget])
    return text if text.endswith((".", "!", "?", "…")) else f"{text.rstrip(',;:—-')}."


def narration_for(spec) -> str:
    """What this shot says out loud, budget-trimmed: the agent's `narration`, else a spoken slate."""
    budget = max(4, int(getattr(spec, "duration_s", 5) * WORDS_PER_SECOND))
    explicit = (getattr(spec, "narration", None) or "").strip()
    if explicit:
        return _fit(explicit, budget)
    prompt = (getattr(spec, "prompt", "") or "").strip()
    if not prompt:
        return ""
    first = prompt.split(". ")[0].strip().rstrip(".")
    slate = f"Shot {getattr(spec, 'index', 0)}."
    words = first.split()
    slate_budget = max(4, budget - len(slate.split()))
    if len(words) > slate_budget:
        first = " ".join(words[:slate_budget])
    return f"{slate} {first}." if first else ""

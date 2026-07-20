"""Narration track — qwen3-tts-flash, with the same replay cache the video path uses.

Wan's t2v/i2v models return silent clips, so a certified episode was silent too. This
synthesizes one narration line per shot and hands it to the assembler.

The endpoint is the SYNCHRONOUS multimodal-generation route, not the async task API the
video models use (docs/verification.md section 3d):

    POST {DASHSCOPE}/api/v1/services/aigc/multimodal-generation/generation
      body: {"model", "input": {"text", "voice"}}
      -> 200 {"output": {"audio": {"url", "expires_at", ...}}}

`voice` is REQUIRED — omitting it is a 400, not a default. The URL is a signed OSS link
that expires, so it is downloaded immediately and the file persisted, exactly like video.

Cached by sha1(model|voice|text): re-narrating an unchanged line is free, which keeps a
judge-mode replay at zero spend even though narration is a per-run text call.
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

# A closed voice roster, for the same reason assertions have a closed vocabulary: an
# unlicensed voice is a 400 ("does not exist or is not licensed for use"), which would
# degrade that shot to silence. The script agent names a SPEAKER; the server picks the
# voice. The agent cannot emit an invalid one because it never emits one.
# Every name below was probed live against this account (docs/verification.md section 3f).
NARRATOR_VOICE = DEFAULT_VOICE
CAST_VOICES = ("Ethan", "Serena", "Dylan", "Jada", "Ryan", "Katerina", "Elias", "Chelsie")


def build_cast(specs) -> dict[str, str]:
    """Map each speaking character to a distinct voice, by order of first appearance.

    Ordinal assignment rather than a hash of the name: a hash can collide and hand two
    characters the same voice with nothing to signal it. Order of first appearance is
    just as deterministic (the shot list is fixed before narration runs), so a re-run
    casts identically and every narration cache key still hits.

    Past the end of the roster voices repeat — a wrap is honest reuse, and a cast that
    large is not something a ~5-shot dailies reel produces.
    """
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


# Conversational TTS runs ~2.6 words/second, so a 5-second shot holds ~13 words. The
# assembler truncates audio at the clip length, so anything past this budget is not
# "extra" — it is a sentence that gets cut off mid-word in the finished episode.
WORDS_PER_SECOND = 2.6


def _fit(text: str, budget: int) -> str:
    """Trim to the word budget and close the sentence."""
    words = text.split()
    if len(words) > budget:
        text = " ".join(words[:budget])
    return text if text.endswith((".", "!", "?", "…")) else f"{text.rstrip(',;:—-')}."


def narration_for(spec) -> str:
    """What this shot says out loud, trimmed to what fits inside it.

    Prefers an explicit `narration` from the script agent — a written line that carries
    the story — and falls back to describing the shot, which is what a spoken slate does
    on a real dailies reel. Both paths are budget-trimmed: the assembler truncates audio
    at the clip length, so an over-long line is not extra, it is a sentence cut mid-word.
    """
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

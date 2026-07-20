"""Narration: what a shot says out loud, and the replay cache that keeps it free."""

import wave
from types import SimpleNamespace

import httpx
import pytest

from server.specs import ShotSpec
from server.tts import TTSClient, narration_for


def _spec(prompt, **kw):
    return ShotSpec(index=kw.pop("index", 0), prompt=prompt, **kw)


def test_narration_prefers_an_explicit_line():
    s = _spec("a long visual description that should not be read", narration="Roll camera.")
    assert narration_for(s) == "Roll camera."


def test_narration_falls_back_to_a_spoken_slate():
    s = _spec("The keeper climbs the spiral staircase. Then he pauses.", index=2)
    # Only the first sentence — a 5s shot cannot carry a paragraph.
    assert narration_for(s) == "Shot 2. The keeper climbs the spiral staircase."


def test_narration_is_trimmed_to_what_fits_in_the_shot():
    # The assembler truncates audio at the clip length, so an over-long line is not
    # "extra" — it is a sentence cut off mid-word in the finished episode.
    long_prompt = " ".join(["word"] * 60)
    text = narration_for(_spec(long_prompt, duration_s=5))
    assert len(text.split()) <= 14, text
    # A longer shot is allowed to say more.
    assert len(narration_for(_spec(long_prompt, duration_s=10)).split()) > 14


def test_narration_of_an_empty_prompt_is_empty():
    assert narration_for(SimpleNamespace(prompt="", index=0)) == ""


class _FakeHTTP:
    """Serves the documented qwen3-tts shape: sync POST, audio under output.audio.url."""

    def __init__(self, wav_bytes, payload=None, status=200):
        self.wav = wav_bytes
        self.payload = payload
        self.status = status
        self.posts = 0

    def post(self, url, headers=None, json=None):
        self.posts += 1
        body = self.payload if self.payload is not None else {
            "output": {"audio": {"url": "https://oss.example/a.wav"}}}
        return httpx.Response(self.status, json=body, request=httpx.Request("POST", url))

    def get(self, url):
        return httpx.Response(200, content=self.wav, request=httpx.Request("GET", url))


def _wav_bytes(tmp_path) -> bytes:
    p = tmp_path / "src.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x01" * 2400)
    return p.read_bytes()


def test_synthesize_downloads_and_then_replays_free(tmp_path):
    http = _FakeHTTP(_wav_bytes(tmp_path))
    tts = TTSClient("k", cache_dir=str(tmp_path / "cache"), http=http)

    first = tts.synthesize("Shot 0. The keeper waits.")
    assert first.ok and not first.from_cache and first.chars > 0
    assert first.local_path.endswith(".wav")

    # The signed OSS url expires, so the FILE is what persists — a second call must not
    # touch the network at all.
    second = tts.synthesize("Shot 0. The keeper waits.")
    assert second.ok and second.from_cache
    assert http.posts == 1, "a cached line must not re-synthesize"


def test_synthesize_reports_failure_instead_of_raising(tmp_path):
    # Narration is a finish, not a contract: a voice failure must degrade to silence
    # rather than take down a certified run.
    http = _FakeHTTP(b"", payload={"code": "InvalidParameter", "message": "voice required"},
                     status=400)
    tts = TTSClient("k", cache_dir=str(tmp_path / "cache"), http=http)
    r = tts.synthesize("anything")
    assert not r.ok and "voice required" in (r.message or "")


def test_empty_text_never_calls_the_api(tmp_path):
    http = _FakeHTTP(b"")
    tts = TTSClient("k", cache_dir=str(tmp_path / "cache"), http=http)
    assert not tts.synthesize("   ").ok
    assert http.posts == 0


def test_missing_audio_url_is_a_failure_not_a_crash(tmp_path):
    http = _FakeHTTP(b"", payload={"output": {"finish_reason": "stop"}})
    tts = TTSClient("k", cache_dir=str(tmp_path / "cache"), http=http)
    r = tts.synthesize("hello")
    assert not r.ok and "no audio url" in (r.message or "")


def test_an_over_long_explicit_line_is_also_trimmed():
    # The explicit branch used to return the agent's line verbatim while only the
    # fallback was budgeted — so a verbose script agent shipped a sentence that the
    # assembler cut off mid-word.
    s = _spec("a lighthouse at dusk", narration=" ".join(["word"] * 40), duration_s=5)
    text = narration_for(s)
    assert len(text.split()) <= 13, text
    assert text.endswith(".")

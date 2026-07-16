"""Wan video + t2i client with a content-addressed replay cache.

API surface VERIFIED live (docs/verification.md, zero quota spent to verify):

  POST {DASHSCOPE}/api/v1/services/aigc/video-generation/video-synthesis
  POST {DASHSCOPE}/api/v1/services/aigc/text2image/image-synthesis
    headers: Authorization: Bearer <key>, Content-Type: json, X-DashScope-Async: enable
    body: {"model", "input": {"prompt", "negative_prompt"?}, "parameters": {...}}
    -> 200 {"output": {"task_id", "task_status": "PENDING"}}
  GET {DASHSCOPE}/api/v1/tasks/{task_id}   (poll ~15s)
    -> video: output.video_url ; image: output.results[0].url
       both are signed OSS URLs that EXPIRE ~24h -> download immediately.

Gotchas baked in here:
  * HTTP 200 on create does NOT mean valid — validation surfaces as task_status
    FAILED on the poll (output.code / output.message). We branch on POLLED status.
  * wan2.1/2.2 clips are a fixed 5s; every video call costs exactly CLIP_SECONDS.

Replay cache: a clip/still is addressed by sha1(model|prompt|seed|size|negative).
Identical inputs return the cached file for FREE — this is what lets judge-mode
re-verify cached clips at zero video quota, and what makes repair retries (which
change the prompt, hence the key) generate fresh while replays stay free.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from server.config import settings

DASHSCOPE_BASE_URL = settings.DASHSCOPE_BASE_URL
VIDEO_SYNTHESIS_URL = f"{DASHSCOPE_BASE_URL}/api/v1/services/aigc/video-generation/video-synthesis"
T2I_SYNTHESIS_URL = f"{DASHSCOPE_BASE_URL}/api/v1/services/aigc/text2image/image-synthesis"
TASK_URL_TEMPLATE = f"{DASHSCOPE_BASE_URL}/api/v1/tasks/{{task_id}}"
TASK_CANCEL_URL_TEMPLATE = f"{DASHSCOPE_BASE_URL}/api/v1/tasks/{{task_id}}/cancel"

DRAFT_MODEL = settings.WAN_DRAFT_MODEL
FINAL_MODEL = settings.WAN_FINAL_MODEL
T2I_MODEL = settings.WAN_T2I_MODEL

CLIP_SECONDS = 5  # fixed for wan2.1/wan2.2 — every video call costs exactly this
POLL_INTERVAL_SECONDS = 15
POLL_TIMEOUT_SECONDS = 600

TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"}

# Accepted frame sizes differ PER MODEL, and getting it wrong is not a soft failure — the
# task is rejected outright with InvalidParameter. Verified live 2026-07-15: wan2.2-t2v-plus
# refuses 1280*720 and answers "size must be in 1080*1920,1920*1080,1440*1440,1632*1248,
# 1248*1632,480*832,832*480,624*624". Both entries below are 16:9, so the premium tier is
# the same framing at 1080p — not a different crop.
DEFAULT_VIDEO_SIZE = "1280*720"                 # wan2.1-t2v-turbo (drafts)
VIDEO_SIZE_BY_MODEL = {
    "wan2.2-t2v-plus": "1920*1080",             # premium finals; rejects 1280*720
}


def video_size_for(model: str) -> str:
    """The frame size a given video model accepts. Callers must not hardcode this: the size
    is part of the cache key, so a wrong guess both breaks the request and poisons cache
    lookups for that model."""
    return VIDEO_SIZE_BY_MODEL.get(model, DEFAULT_VIDEO_SIZE)


def cache_key(model: str, prompt: str, seed: int | None, size: str, negative_prompt: str | None) -> str:
    raw = f"{model}|{prompt}|{seed}|{size}|{negative_prompt or ''}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass
class WanResult:
    status: str                 # SUCCEEDED | FAILED | CANCELED | UNKNOWN | TIMEOUT
    kind: str                   # "video" | "image"
    local_path: str | None = None
    url: str | None = None
    task_id: str | None = None
    code: str | None = None
    message: str | None = None
    from_cache: bool = False
    latency_ms: int = 0
    seconds: int = 0            # billed video seconds (0 for images / cache hits)

    @property
    def ok(self) -> bool:
        return self.status == "SUCCEEDED" and self.local_path is not None


class WanClient:
    def __init__(
        self,
        api_key: str,
        *,
        cache_dir: str | os.PathLike[str] = "data/cache",
        poll_interval: float = POLL_INTERVAL_SECONDS,
        poll_timeout: float = POLL_TIMEOUT_SECONDS,
        http: httpx.Client | None = None,
    ):
        if not api_key:
            raise ValueError("WanClient needs an api_key")
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self._http = http or httpx.Client(timeout=60)

    def is_cached(self, kind: str, model: str, prompt: str, seed: int | None,
                  size: str, negative_prompt: str | None) -> bool:
        """Whether this exact request already has a cached file — lets the judge-mode
        governor tell a free replay from a fresh (billable) generation before spending."""
        ext = "mp4" if kind == "video" else "png"
        key = cache_key(model, prompt, seed, size, negative_prompt)
        return (self.cache_dir / f"{key}.{ext}").exists()

    def _headers(self, *, async_create: bool = False) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if async_create:
            h["X-DashScope-Async"] = "enable"
        return h

    def _create_task(self, url: str, body: dict) -> dict:
        r = self._http.post(url, headers=self._headers(async_create=True), json=body)
        r.raise_for_status()
        return r.json()

    def _poll(self, task_id: str) -> dict:
        deadline = time.monotonic() + self.poll_timeout
        while True:
            r = self._http.get(TASK_URL_TEMPLATE.format(task_id=task_id), headers=self._headers())
            r.raise_for_status()
            out = r.json().get("output", {})
            if out.get("task_status") in TERMINAL_STATUSES:
                return out
            if time.monotonic() >= deadline:
                return {"task_status": "TIMEOUT", "task_id": task_id}
            time.sleep(self.poll_interval)

    def _download(self, url: str, dest: Path) -> None:
        r = self._http.get(url)
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)

    def _generate(
        self,
        *,
        kind: str,
        endpoint: str,
        model: str,
        prompt: str,
        seed: int | None,
        size: str,
        negative_prompt: str | None,
        ext: str,
        url_from_output,
        billed_seconds: int,
    ) -> WanResult:
        key = cache_key(model, prompt, seed, size, negative_prompt)
        dest = self.cache_dir / f"{key}.{ext}"
        if dest.exists():
            return WanResult(status="SUCCEEDED", kind=kind, local_path=str(dest),
                             from_cache=True, seconds=0)

        body: dict = {"model": model, "input": {"prompt": prompt}}
        if negative_prompt:
            body["input"]["negative_prompt"] = negative_prompt
        params: dict = {"size": size, "prompt_extend": True, "watermark": False}
        if seed is not None:
            params["seed"] = seed
        body["parameters"] = params

        t0 = time.monotonic()
        created = self._create_task(endpoint, body)
        task_id = created.get("output", {}).get("task_id")
        if not task_id:
            return WanResult(status="FAILED", kind=kind, message=f"no task_id: {created}")

        out = self._poll(task_id)
        latency_ms = int((time.monotonic() - t0) * 1000)
        status = out.get("task_status", "UNKNOWN")
        if status != "SUCCEEDED":
            return WanResult(status=status, kind=kind, task_id=task_id, latency_ms=latency_ms,
                             code=out.get("code"), message=out.get("message"))

        url = url_from_output(out)
        if not url:
            return WanResult(status="FAILED", kind=kind, task_id=task_id, latency_ms=latency_ms,
                             message=f"no media url in output: {out}")
        self._download(url, dest)
        return WanResult(status="SUCCEEDED", kind=kind, local_path=str(dest), url=url,
                         task_id=task_id, latency_ms=latency_ms, seconds=billed_seconds)

    def generate_video(
        self,
        prompt: str,
        *,
        model: str | None = None,
        seed: int | None = None,
        size: str | None = None,
        negative_prompt: str | None = None,
    ) -> WanResult:
        # Default the size FROM the model. It used to default to 1280*720 for every model,
        # which meant every wan2.2-t2v-plus promote was rejected with InvalidParameter —
        # silently, because _promote treats a failed promote as "keep the passing draft".
        model = model or DRAFT_MODEL
        return self._generate(
            kind="video",
            endpoint=VIDEO_SYNTHESIS_URL,
            model=model,
            prompt=prompt,
            seed=seed,
            size=size or video_size_for(model),
            negative_prompt=negative_prompt,
            ext="mp4",
            url_from_output=lambda out: out.get("video_url"),
            billed_seconds=CLIP_SECONDS,
        )

    def generate_image(
        self,
        prompt: str,
        *,
        model: str | None = None,
        seed: int | None = None,
        size: str = "1024*1024",
        negative_prompt: str | None = None,
    ) -> WanResult:
        def _first_url(out: dict) -> str | None:
            results = out.get("results") or []
            return results[0].get("url") if results else None

        return self._generate(
            kind="image",
            endpoint=T2I_SYNTHESIS_URL,
            model=model or T2I_MODEL,
            prompt=prompt,
            seed=seed,
            size=size,
            negative_prompt=negative_prompt,
            ext="png",
            url_from_output=_first_url,
            billed_seconds=0,
        )


def default_client(**kwargs) -> WanClient:
    """Build a WanClient from the configured QWEN_API_KEY."""
    return WanClient(settings.QWEN_API_KEY, **kwargs)

"""Wan video + t2i client over the async DashScope task API, with a content-addressed replay cache.

Two invariants: HTTP 200 on create does NOT mean valid (branch on the POLLED status), and
result URLs are signed and expire, so download immediately.
"""

from __future__ import annotations

import base64
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

# Accepted frame sizes differ PER MODEL; a wrong one is rejected with InvalidParameter.
DEFAULT_VIDEO_SIZE = "1280*720"                 # wan2.1-t2v-turbo (drafts)
VIDEO_SIZE_BY_MODEL = {
    "wan2.2-t2v-plus": "1920*1080",             # premium finals; rejects 1280*720
}


def video_size_for(model: str) -> str:
    """The frame size a given video model accepts. Never hardcode this — the size is part of
    the cache key, so a wrong guess breaks the request and poisons cache lookups."""
    return VIDEO_SIZE_BY_MODEL.get(model, DEFAULT_VIDEO_SIZE)


IMAGE2VIDEO_URL = f"{DASHSCOPE_BASE_URL}/api/v1/services/aigc/image2video/video-synthesis"

# Frame-anchored video models: which endpoint serves each, and its input-image field name.
FRAME_ANCHORED: dict[str, tuple[str, str]] = {
    "wan2.2-i2v-flash": (VIDEO_SYNTHESIS_URL, "img_url"),
    "wan2.1-i2v-turbo": (VIDEO_SYNTHESIS_URL, "img_url"),
    "wan2.1-kf2v-plus": (IMAGE2VIDEO_URL, "first_frame_url"),
}


def cache_key(model: str, prompt: str, seed: int | None, size: str,
              negative_prompt: str | None, salt: str = "") -> str:
    # `salt` must stay append-only-when-non-empty, or every pre-existing cache key changes.
    raw = f"{model}|{prompt}|{seed}|{size}|{negative_prompt or ''}"
    if salt:
        raw += f"|{salt}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def frame_data_uri(path: str | os.PathLike[str]) -> str:
    """A local frame as a base64 `data:` URI — the DashScope video endpoints accept these
    in place of an HTTP URL, so a local-only anchor frame needs no upload."""
    p = Path(path)
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")


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
    cached_seconds: int = 0     # seconds a cache replay represents (billed on a prior run);
                                # the wallet ignores this, the frontier uses it

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
        """Whether this exact request already has a cached file (a free replay vs a billable one)."""
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
        extra_input: dict | None = None,
        salt: str = "",
    ) -> WanResult:
        key = cache_key(model, prompt, seed, size, negative_prompt, salt)
        dest = self.cache_dir / f"{key}.{ext}"
        if dest.exists():
            return WanResult(status="SUCCEEDED", kind=kind, local_path=str(dest),
                             from_cache=True, seconds=0, cached_seconds=billed_seconds)

        body: dict = {"model": model, "input": {"prompt": prompt}}
        if negative_prompt:
            body["input"]["negative_prompt"] = negative_prompt
        if extra_input:
            body["input"].update(extra_input)
        params: dict = {"prompt_extend": True, "watermark": False}
        # A frame-anchored call takes its size from the anchor; sending one is InvalidParameter.
        if size:
            params["size"] = size
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
        # The size must be defaulted FROM the model, never to a constant.
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

    def generate_video_from_frame(
        self,
        prompt: str,
        frame_path: str | os.PathLike[str],
        *,
        model: str,
        negative_prompt: str | None = None,
    ) -> WanResult:
        """Re-render a shot anchored to a real frame of its own footage, on the i2v/kf2v quota.
        The anchor's bytes salt the cache key, since two repairs of one shot differ by anchor."""
        try:
            endpoint, field = FRAME_ANCHORED[model]
        except KeyError:
            return WanResult(status="FAILED", kind="video", code="UnsupportedModel",
                             message=f"{model} is not a frame-anchored model; "
                                     f"known: {sorted(FRAME_ANCHORED)}")
        p = Path(frame_path)
        if not p.exists():
            return WanResult(status="FAILED", kind="video", code="NoAnchorFrame",
                             message=f"anchor frame missing: {p}")

        return self._generate(
            kind="video",
            endpoint=endpoint,
            model=model,
            prompt=prompt,
            seed=None,
            size="",  # the anchor image defines the frame size
            negative_prompt=negative_prompt,
            ext="mp4",
            url_from_output=lambda out: out.get("video_url"),
            billed_seconds=CLIP_SECONDS,
            extra_input={field: frame_data_uri(p)},
            salt=hashlib.sha1(p.read_bytes()).hexdigest()[:12],
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

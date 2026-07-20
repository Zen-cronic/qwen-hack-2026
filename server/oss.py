"""Alibaba OSS access — upload published media, presign browser GET URLs.

Two clients on purpose (V4 signing bakes the configured endpoint into the URL):
  * ops client    — OSS_INTERNAL_ENDPOINT when set (free same-region traffic from
                    the SAS box), else the public endpoint. Uploads + existence checks.
  * presign client — always the public endpoint, so presigned URLs resolve from a
                    judge's browser, not just inside Alibaba's network.

Presigned GETs carry response-content-disposition=inline. Two things measured
against this bucket (scripts/check_oss.py), both counter to the obvious guess:

  * response-content-type is REJECTED — OSS answers 400 "Can not override
    response header on content-type". It is also unnecessary: the correct type
    is stored at upload time, so responses already carry content-type: video/mp4.
  * response-content-disposition=inline is silently IGNORED on the default
    bucket domain — post-Oct-2022 accounts always answer attachment. It is kept
    because it costs nothing and does take effect behind a custom CNAME domain.
    Browsers honour Content-Disposition for top-level navigation only, so
    <video>/<img> subresource playback is unaffected (verified in a real browser).

Same degradation contract as server/db.py: misconfiguration or network failure
returns None/False and logs — never raises into the pipeline or a route.
"""

from __future__ import annotations

import datetime
import logging
import threading
from pathlib import Path

import alibabacloud_oss_v2 as oss_sdk

from server.config import settings

log = logging.getLogger("dailies.oss")

_lock = threading.Lock()
_ops_client: oss_sdk.Client | None = None
_presign_client: oss_sdk.Client | None = None

MIME_BY_EXT = {
    ".mp4": "video/mp4",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
}


def enabled() -> bool:
    return bool(
        settings.CATALOG_ENABLED
        and settings.OSS_ACCESS_KEY_ID
        and settings.OSS_ACCESS_KEY_SECRET
        and settings.OSS_BUCKET
    )


def object_key(sha1: str, ext: str) -> str:
    """Content-addressed key: identical bytes republished land on the same object."""
    return f"media/{sha1}{ext}"


def upload(sha1: str, local_path: str | Path, mime: str | None = None) -> str | None:
    """Upload one file (skip if the object already exists). Returns the OSS key or None."""
    client = _client(internal=True)
    if client is None:
        return None
    p = Path(local_path)
    key = object_key(sha1, p.suffix.lower())
    try:
        if client.is_object_exist(settings.OSS_BUCKET, key):
            return key
        client.put_object_from_file(
            oss_sdk.PutObjectRequest(
                bucket=settings.OSS_BUCKET,
                key=key,
                content_type=mime or MIME_BY_EXT.get(p.suffix.lower(), "application/octet-stream"),
            ),
            str(p),
        )
        return key
    except Exception as exc:  # noqa: BLE001 — publish continues without this object
        log.warning("OSS upload failed for %s: %s", key, exc)
        return None


def presign_get(oss_key: str, *, mime: str | None = None, filename: str | None = None,
                ttl_s: int | None = None) -> str | None:
    """Time-limited browser URL for a private object, forced inline for playback."""
    client = _client(internal=False)
    if client is None:
        return None
    disposition = "inline" + (f'; filename="{filename}"' if filename else "")
    try:
        result = client.presign(
            # No response_content_type here — OSS rejects the override outright
            # (400 InvalidRequest); the stored object metadata already carries it.
            oss_sdk.GetObjectRequest(
                bucket=settings.OSS_BUCKET,
                key=oss_key,
                response_content_disposition=disposition,
            ),
            expires=datetime.timedelta(seconds=ttl_s or settings.OSS_PRESIGN_TTL_S),
        )
        return result.url
    except Exception as exc:  # noqa: BLE001
        log.warning("OSS presign failed for %s: %s", oss_key, exc)
        return None


def reset_for_tests() -> None:
    global _ops_client, _presign_client
    with _lock:
        _ops_client = None
        _presign_client = None


def _client(*, internal: bool) -> oss_sdk.Client | None:
    global _ops_client, _presign_client
    if not enabled():
        return None
    cached = _ops_client if internal else _presign_client
    if cached is not None:
        return cached
    with _lock:
        cached = _ops_client if internal else _presign_client
        if cached is not None:
            return cached
        endpoint = settings.OSS_ENDPOINT
        if internal and settings.OSS_INTERNAL_ENDPOINT:
            endpoint = settings.OSS_INTERNAL_ENDPOINT
        try:
            cfg = oss_sdk.config.load_default()
            cfg.region = settings.OSS_REGION
            cfg.endpoint = endpoint
            cfg.credentials_provider = oss_sdk.credentials.StaticCredentialsProvider(
                settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
            client = oss_sdk.Client(cfg)
        except Exception as exc:  # noqa: BLE001
            log.warning("OSS client init failed (%s endpoint): %s", endpoint, exc)
            return None
        if internal:
            _ops_client = client
        else:
            _presign_client = client
        return client

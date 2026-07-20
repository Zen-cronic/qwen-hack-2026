"""One-shot OSS smoke test — credentials, upload, presign, and range support.

`Content-Disposition: attachment` is expected on the default bucket domain (the inline
override is ignored there) and is treated as a pass: <video>/<img> playback is unaffected.

Usage: CATALOG_ENABLED=1 OSS_ACCESS_KEY_ID=... OSS_ACCESS_KEY_SECRET=... OSS_BUCKET=... \
    python scripts/check_oss.py [path/to/file.mp4]
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from server import oss
from server.config import settings


def main() -> int:
    if not oss.enabled():
        print("NOT CONFIGURED: need CATALOG_ENABLED=1 + OSS_ACCESS_KEY_ID/SECRET + OSS_BUCKET")
        return 2

    if len(sys.argv) > 1:
        sample = Path(sys.argv[1])
    else:
        cache = Path(settings.DATA_DIR) / "cache"
        clips = sorted(cache.glob("*.mp4"), key=lambda p: p.stat().st_size)
        if not clips:
            print(f"no .mp4 found under {cache} — pass a file path explicitly")
            return 2
        sample = clips[0]  # smallest clip: fastest meaningful upload

    sha1 = hashlib.sha1(sample.read_bytes()).hexdigest()
    print(f"file: {sample}  ({sample.stat().st_size:,} bytes, sha1 {sha1[:12]}…)")
    print(f"bucket: {settings.OSS_BUCKET}  region: {settings.OSS_REGION}")
    print(f"upload endpoint: {settings.OSS_INTERNAL_ENDPOINT or settings.OSS_ENDPOINT}")

    key = oss.upload(sha1, sample, mime="video/mp4")
    if key is None:
        print("FAIL: upload returned None (see warning above — creds? bucket? endpoint?)")
        return 1
    print(f"uploaded: {key}")

    url = oss.presign_get(key, mime="video/mp4", filename=sample.name)
    if url is None:
        print("FAIL: presign returned None")
        return 1

    # Range GET, not HEAD: it proves byte-serving and seek support in one call.
    resp = httpx.get(url, timeout=30, headers={"Range": "bytes=0-99"})
    print(f"\nGET (Range: bytes=0-99) -> {resp.status_code}")
    for h in ("content-type", "content-disposition", "content-range", "accept-ranges",
              "content-length", "x-oss-force-download"):
        if h in resp.headers:
            print(f"  {h}: {resp.headers[h]}")

    ctype = resp.headers.get("content-type", "")
    checks = {
        "partial-content (206)": resp.status_code == 206,
        "content-type is video/mp4": ctype == "video/mp4",
        "range served": "content-range" in resp.headers,
    }
    print()
    for label, passed in checks.items():
        print(f"  {'OK  ' if passed else 'FAIL'} {label}")
    if resp.headers.get("content-disposition", "").startswith("attachment"):
        print("  NOTE attachment disposition — expected on the default domain;"
              " <video>/<img> playback is unaffected (see module docstring)")

    print(f"\npresigned URL (valid {settings.OSS_PRESIGN_TTL_S}s):\n{url}\n")
    if all(checks.values()):
        print("PASS — OSS is wired: credentials, upload, presign, and range/seek all work.")
        return 0
    print("FAIL — see the failing check above before enabling the catalog in production.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Probe the two unused DashScope capabilities: image editing and keyframe->video.

docs/verification.md section 2 banks free quota for qwen-image-edit (100 images) and
wan2.1-kf2v-plus (200 s / 40 cycles) that server/ has never called. They are the
backend for a targeted repair: extract the failing frame, edit THAT frame, re-render
the clip anchored to it -- instead of blind-re-prompting a whole 5 s shot.

Same zero-cost trick as scripts/probe_models.py: a deliberately invalid request
(empty input) exercises endpoint + auth + model routing and fails at server-side
validation, so nothing is generated and nothing is billed. The rejection usually
NAMES the missing field, which means a failed probe also documents the request
schema -- the point of running this before writing the client.

The endpoint path for each model is itself unknown, so every plausible path is
tried and classified. Only auth failures and "model not found" are real failures.

    python scripts/probe_edit_models.py
"""

import sys
import time

import httpx
from rich import print

from server.config import settings

BASE = settings.DASHSCOPE_BASE_URL
TASK_URL = f"{BASE}/api/v1/tasks/{{task_id}}"

IMAGE_PATHS = {
    "image2image": f"{BASE}/api/v1/services/aigc/image2image/image-synthesis",
    "multimodal": f"{BASE}/api/v1/services/aigc/multimodal-generation/generation",
    "text2image": f"{BASE}/api/v1/services/aigc/text2image/image-synthesis",
}
VIDEO_PATHS = {
    "video-synthesis": f"{BASE}/api/v1/services/aigc/video-generation/video-synthesis",
    "image2video": f"{BASE}/api/v1/services/aigc/image2video/video-synthesis",
}

# (label, url, model). Ordered most-likely-first within each capability.
CANDIDATES = [
    ("qwen-image-edit", IMAGE_PATHS["image2image"], "qwen-image-edit"),
    ("qwen-image-edit", IMAGE_PATHS["multimodal"], "qwen-image-edit"),
    ("qwen-image-edit", IMAGE_PATHS["text2image"], "qwen-image-edit"),
    ("qwen-image-edit-plus", IMAGE_PATHS["image2image"], "qwen-image-edit-plus"),
    ("wanx2.1-imageedit", IMAGE_PATHS["image2image"], "wanx2.1-imageedit"),
    ("wan2.1-kf2v-plus", VIDEO_PATHS["video-synthesis"], "wan2.1-kf2v-plus"),
    ("wan2.1-kf2v-plus", VIDEO_PATHS["image2video"], "wan2.1-kf2v-plus"),
    ("wan2.2-i2v-flash", VIDEO_PATHS["video-synthesis"], "wan2.2-i2v-flash"),
    ("wan2.2-i2v-flash", VIDEO_PATHS["image2video"], "wan2.2-i2v-flash"),
]

# Server-side validation vocabulary. A complaint about a MISSING FIELD is the good
# outcome; a complaint about the MODEL means we are knocking on the wrong door.
_MODEL_ERRORS = ("model not exist", "model not found", "invalidmodel", "unsupported model",
                 "model is not supported", "no permission", "unauthorized model")


def _auth(extra: dict | None = None) -> dict:
    h = {"Authorization": f"Bearer {settings.QWEN_API_KEY}", "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def _poll(task_id: str, timeout_s: int = 45) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = httpx.get(TASK_URL.format(task_id=task_id), headers=_auth(), timeout=30)
        r.raise_for_status()
        out = r.json().get("output", {})
        if out.get("task_status") in {"SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"}:
            return out
        time.sleep(2)
    return {"task_status": "TIMEOUT"}


def probe(label: str, url: str, model: str) -> tuple[str, str]:
    """Return (verdict, evidence). Never generates: `input` is empty on purpose."""
    path = url.rsplit("/aigc/", 1)[-1]
    try:
        r = httpx.post(url, headers=_auth({"X-DashScope-Async": "enable"}),
                       json={"model": model, "input": {}}, timeout=60)
    except Exception as exc:  # noqa: BLE001
        return "ERROR", f"{type(exc).__name__}: {exc}"

    try:
        payload = r.json()
    except Exception:  # noqa: BLE001
        payload = {}
    code = payload.get("code") or ""
    msg = payload.get("message") or ""

    if r.status_code == 200 and payload.get("output", {}).get("task_id"):
        out = _poll(payload["output"]["task_id"])
        code, msg = out.get("code") or "", out.get("message") or ""
        if out.get("task_status") == "FAILED":
            verdict = "MODEL_UNKNOWN" if any(m in msg.lower() for m in _MODEL_ERRORS) else "REACHABLE"
            return verdict, f"async validation: {code}: {msg}"
        return "UNEXPECTED", f"terminal={out.get('task_status')} {code}: {msg}"

    if r.status_code in (401, 403):
        return "AUTH_FAIL", f"HTTP {r.status_code} {code}: {msg}"
    if r.status_code == 404:
        return "NO_SUCH_PATH", f"HTTP 404 {code}: {msg}"
    if any(m in msg.lower() for m in _MODEL_ERRORS):
        return "MODEL_UNKNOWN", f"HTTP {r.status_code} {code}: {msg}"
    if r.status_code == 400:
        return "REACHABLE", f"sync validation: {code}: {msg}"
    return "UNEXPECTED", f"HTTP {r.status_code} {code}: {msg}"


def main() -> int:
    if not settings.QWEN_API_KEY:
        print("[red]FAIL[/red] QWEN_API_KEY missing.")
        return 1
    print(f"[bold]edit/keyframe endpoint discovery — host {BASE}[/bold]")
    print("[dim]empty `input` on purpose: validation rejects it before anything generates[/dim]\n")

    reachable: list[str] = []
    for label, url, model in CANDIDATES:
        path = url.rsplit("/aigc/", 1)[-1]
        verdict, evidence = probe(label, url, model)
        color = {"REACHABLE": "green", "MODEL_UNKNOWN": "yellow",
                 "NO_SUCH_PATH": "yellow", "AUTH_FAIL": "red"}.get(verdict, "white")
        print(f"  [{color}]{verdict:<13}[/{color}] {label:<22} @ {path}")
        print(f"                {evidence[:220]}")
        if verdict == "REACHABLE":
            reachable.append(f"{label} @ {path}")

    print()
    if reachable:
        print(f"[green]USABLE[/green] ({len(reachable)}): " + " | ".join(reachable))
        print("[dim]Read each 'sync/async validation' message above — it names the "
              "required input fields, which is the request schema.[/dim]")
        return 0
    print("[red]none reachable[/red] — targeted repair needs a different backend.")
    return 2


if __name__ == "__main__":
    sys.exit(main())

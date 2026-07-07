"""Hour-zero probe: confirm the text-to-image (Tier-0) endpoint before building tier0.py.

Tier 0 pre-screens a doomed shot with a single still at ~1/25th of video cost, so
the t2i surface must be confirmed early. Same trick as the Wan video probe: a
deliberately invalid request (no prompt) exercises endpoint + auth + model routing
and fails at server-side validation — proving reachability WITHOUT spending an
image credit. Pass --real to then generate one actual still (1 image credit,
budgeted in PLAN.md's hour-zero row) and bank the URL.

    python scripts/probe_models.py          # zero-cost reachability probe only
    python scripts/probe_models.py --real    # + generate 1 real still
"""

import os
import sys
import time

import httpx
from dotenv import load_dotenv
from rich import print

load_dotenv()

DASHSCOPE_BASE_URL = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com")
T2I_URL = f"{DASHSCOPE_BASE_URL}/api/v1/services/aigc/text2image/image-synthesis"
TASK_URL = f"{DASHSCOPE_BASE_URL}/api/v1/tasks/{{task_id}}"
T2I_MODEL = os.environ.get("WAN_T2I_MODEL", "wan2.1-t2i-plus")


def _auth(api_key: str, extra: dict | None = None) -> dict:
    h = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def create_task(api_key: str, body: dict) -> httpx.Response:
    return httpx.post(T2I_URL, headers=_auth(api_key, {"X-DashScope-Async": "enable"}), json=body, timeout=60)


def poll(api_key: str, task_id: str, timeout_s: int = 120) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = httpx.get(TASK_URL.format(task_id=task_id), headers=_auth(api_key), timeout=60)
        r.raise_for_status()
        out = r.json().get("output", {})
        status = out.get("task_status")
        if status in {"SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"}:
            return out
        time.sleep(3)
    return {"task_status": "TIMEOUT"}


def zero_cost_probe(api_key: str) -> bool:
    """Invalid request (no prompt) -> a field-validation rejection confirms reachability.

    Two valid signals depending on how the endpoint validates:
      (a) async accept (video-style): HTTP 200 -> poll -> FAILED at validation
      (b) sync validate (image-style): HTTP 400 InvalidParameter about the prompt
    Either proves endpoint + auth + model routing at zero cost. Only 401/403 (auth)
    or 404/model-not-found are true failures.
    """
    r = create_task(api_key, {"model": T2I_MODEL, "input": {}})
    print(f"  POST {T2I_URL} -> HTTP {r.status_code}")
    try:
        payload = r.json()
    except Exception:  # noqa: BLE001
        payload = {}
    code = payload.get("code")
    msg = payload.get("message", "") or ""

    if r.status_code == 200:
        task_id = payload.get("output", {}).get("task_id")
        if not task_id:
            print(f"  [red]FAIL[/red] 200 but no task_id: {r.text[:300]}")
            return False
        out = poll(api_key, task_id)
        print(f"  task {task_id} -> {out.get('task_status')} code={out.get('code')} msg={out.get('message')}")
        if out.get("task_status") == "FAILED":
            print(f"  [green]OK[/green] endpoint + auth + model '{T2I_MODEL}' confirmed (async validation).")
            return True
        print(f"  [yellow]?[/yellow] unexpected terminal state: {out}")
        return False

    if r.status_code == 400 and (code in {"InvalidParameter", "InvalidParameters"} or "prompt" in msg.lower()):
        print(f"  code={code} msg={msg}")
        print(f"  [green]OK[/green] endpoint + auth + model '{T2I_MODEL}' confirmed (sync validation rejected empty prompt).")
        return True
    if r.status_code in (401, 403):
        print(f"  [red]FAIL[/red] auth rejected (code={code}): check QWEN_API_KEY / endpoint pairing.")
        return False
    print(f"  [red]FAIL[/red] unexpected: HTTP {r.status_code} code={code} msg={msg}")
    return False


def real_still(api_key: str) -> None:
    body = {
        "model": T2I_MODEL,
        "input": {"prompt": "a single red apple on a white studio table, soft daylight, centered"},
        "parameters": {"size": "1024*1024", "n": 1},
    }
    r = create_task(api_key, body)
    print(f"  real still POST -> HTTP {r.status_code}")
    r.raise_for_status()
    task_id = r.json()["output"]["task_id"]
    out = poll(api_key, task_id, timeout_s=180)
    print(f"  task {task_id} -> {out.get('task_status')}")
    if out.get("task_status") == "SUCCEEDED":
        results = out.get("results") or []
        url = results[0].get("url") if results else None
        print(f"  [green]OK[/green] still generated: {url}")
        print(f"  usage: {out.get('usage') or 'n/a'}")
    else:
        print(f"  [red]FAIL[/red] {out}")


def main() -> int:
    api_key = os.environ.get("QWEN_API_KEY")
    if not api_key:
        print("[red]FAIL[/red] QWEN_API_KEY missing.")
        return 1
    print(f"[bold]t2i endpoint probe — model {T2I_MODEL}[/bold]")
    ok = zero_cost_probe(api_key)
    if not ok:
        return 2
    if "--real" in sys.argv:
        print("\n[cyan]--real: generating one still (1 image credit)[/cyan]")
        real_still(api_key)
    return 0


if __name__ == "__main__":
    sys.exit(main())

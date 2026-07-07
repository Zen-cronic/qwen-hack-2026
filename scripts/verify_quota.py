"""Day-1 verify-or-abort gate (PLAN.md, Jul 5).

Checks, in order:
  1. QWEN_API_KEY works against the sanctioned OpenAI-compatible endpoint.
  2. A minimal chat completion succeeds and reports token usage (free tier sanity).
  3. Prints the manual checklist for Wan/HappyHorse video-gen access — the video
     API surface is UNVERIFIED as of Jul 5; do not assume an endpoint shape.

ABORT RULE (state.md): if video-gen quota can't cover ~a dozen generation
cycles on the free tier, pivot to DataCrew (Track 3) or skip.
"""

import os
import sys

from dotenv import load_dotenv
from openai import OpenAI
from rich import print

load_dotenv()

BASE_URL = os.environ.get("QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
MODEL = os.environ.get("QWEN_CHAT_MODEL", "qwen-plus")


def main() -> int:
    api_key = os.environ.get("QWEN_API_KEY")
    if not api_key:
        print("[red]FAIL[/red] QWEN_API_KEY missing — copy .env.example to .env and fill it in.")
        return 1

    client = OpenAI(api_key=api_key, base_url=BASE_URL)

    # 1+2: minimal chat completion with usage reporting
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            max_tokens=8,
        )
    except Exception as exc:  # noqa: BLE001 — gate script, report anything
        print(f"[red]FAIL[/red] chat completion against {BASE_URL} ({MODEL}): {exc}")
        return 1

    usage = resp.usage
    print(f"[green]OK[/green] chat completion via {BASE_URL} model={MODEL}")
    print(f"     usage: prompt={usage.prompt_tokens} completion={usage.completion_tokens} total={usage.total_tokens}")

    # 3: video-gen access is a manual check until the Wan API surface is confirmed
    print()
    print("[yellow]MANUAL CHECKS — video generation (Wan / HappyHorse):[/yellow]")
    print("  1. In the Qwen Cloud console, confirm a Wan/video model is listed and callable on your account.")
    print("  2. Find the per-track token allowance for Track 2 (unpublished; ask Discord if absent).")
    print("  3. Estimate: ~a dozen generation cycles needed. If free-tier quota can't cover that: ABORT to DataCrew.")
    print("  4. Record the Wan endpoint + request shape in server/wan.py before writing generate_shot().")
    print("     (done Jul 6 — see docs/verification.md for the evidence log)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

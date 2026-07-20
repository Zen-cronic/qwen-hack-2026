"""Day-1 verify-or-abort gate: the key works, a chat completion reports usage, and the
manual video-gen checklist prints. Abort rule (state.md): if quota can't cover ~a dozen
generation cycles, pivot to DataCrew (Track 3) or skip."""

import sys

from openai import OpenAI
from rich import print

from server.config import settings

BASE_URL = settings.QWEN_BASE_URL
MODEL = settings.QWEN_CHAT_MODEL


def main() -> int:
    api_key = settings.QWEN_API_KEY
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

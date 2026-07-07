"""Hour-zero probe: is qwen-vl usable for Tier-B semantic verdicts? (PLAN.md, Dailies)

Tier B asks a vision-language model JSON questions about strided video frames
(subject_present, identity_consistent, action_completed). Before building that,
we must prove the VLM (a) is callable on this account and (b) actually reads
pixels rather than hallucinating.

The test: generate two solid-gray images — one bright, one dark — in memory, and
ask the model to classify each. A model that sees pixels answers correctly for
both; a model that can't see them (or isn't really multimodal) can't beat a coin
flip across the pair. We try both call shapes × both model tiers:

  shape "openai"    -> chat.completions with image_url content parts (data URI)
  shape "dashscope" -> native multimodal-generation endpoint

DECISION (writes to stdout; you pin the winner into .env by hand):
  GO   -> first (model, shape) that classifies BOTH images correctly.
          Set VL_MODEL + VL_SHAPE in .env; Jul 7 builds tier_b.py for real.
  NO-GO-> nothing passes. tier_b.py compiles every Tier-B assertion to
          `inconclusive` and the UI shows human verdict buttons instead.
          The never-cut spine (Tier-A deterministic CV) is unaffected.

Cost: a handful of tiny vision calls, ~2-4k tokens total. Zero video quota.
"""

import base64
import os
import sys

import cv2
import httpx
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from rich import print

load_dotenv()

OPENAI_BASE_URL = os.environ.get("QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
DASHSCOPE_BASE_URL = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com")
MULTIMODAL_URL = f"{DASHSCOPE_BASE_URL}/api/v1/services/aigc/multimodal-generation/generation"

MODELS = ["qwen-vl-plus", "qwen-vl-max"]
QUESTION = "Is this image mostly bright/white or mostly dark/black? Answer with exactly one word: bright or dark."


def solid_png_data_uri(value: int) -> str:
    """A 256x256 solid-gray PNG at the given 0-255 level, as a base64 data URI."""
    img = np.full((256, 256, 3), value, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("cv2.imencode failed")
    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def classify_openai(client: OpenAI, model: str, data_uri: str) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": QUESTION},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
        max_tokens=10,
    )
    return (resp.choices[0].message.content or "").strip().lower()


def classify_dashscope(api_key: str, model: str, data_uri: str) -> str:
    resp = httpx.post(
        MULTIMODAL_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": QUESTION}, {"image": data_uri}],
                    }
                ]
            },
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    # output.choices[0].message.content is a list of {text: ...} parts
    content = data["output"]["choices"][0]["message"]["content"]
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content).strip().lower()
    return str(content).strip().lower()


def verdict_correct(answer: str, expected: str) -> bool:
    """expected is 'bright' or 'dark'; accept the word appearing and its opposite absent."""
    other = "dark" if expected == "bright" else "bright"
    return expected in answer and other not in answer


def try_combo(name: str, classify) -> bool:
    bright_uri = solid_png_data_uri(225)
    dark_uri = solid_png_data_uri(25)
    try:
        a_bright = classify(bright_uri)
        a_dark = classify(dark_uri)
    except Exception as exc:  # noqa: BLE001 — probe: report anything and move on
        print(f"  [red]ERR[/red] {name}: {exc}")
        return False
    ok_bright = verdict_correct(a_bright, "bright")
    ok_dark = verdict_correct(a_dark, "dark")
    tag = "[green]PASS[/green]" if (ok_bright and ok_dark) else "[yellow]FAIL[/yellow]"
    print(f"  {tag} {name}: bright->'{a_bright}' ({ok_bright}) dark->'{a_dark}' ({ok_dark})")
    return ok_bright and ok_dark


def main() -> int:
    api_key = os.environ.get("QWEN_API_KEY")
    if not api_key:
        print("[red]FAIL[/red] QWEN_API_KEY missing.")
        return 1

    client = OpenAI(api_key=api_key, base_url=OPENAI_BASE_URL)
    print("[bold]qwen-vl smoke test — Tier-B GO/NO-GO[/bold]")

    for model in MODELS:
        print(f"[cyan]model {model}[/cyan]")
        if try_combo(f"{model} / openai", lambda uri, m=model: classify_openai(client, m, uri)):
            print(f"\n[green]GO[/green] Tier B is live. Pin in .env:  VL_MODEL={model}  VL_SHAPE=openai")
            return 0
        if try_combo(f"{model} / dashscope", lambda uri, m=model: classify_dashscope(api_key, m, uri)):
            print(f"\n[green]GO[/green] Tier B is live. Pin in .env:  VL_MODEL={model}  VL_SHAPE=dashscope")
            return 0

    print("\n[yellow]NO-GO[/yellow] No VL combo classified both images. Tier B -> inconclusive + human verdict buttons.")
    print("  (Deterministic Tier-A CV is the never-cut spine and is unaffected.)")
    return 2


if __name__ == "__main__":
    sys.exit(main())

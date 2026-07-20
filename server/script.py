"""The script agent — premise -> shots + dynamic assertions, in one qwen-plus call.

The allowed-assertions section of the prompt is generated from ASSERTION_META, so
what we TELL the model it may emit can never drift from what the compiler will
actually accept. The model returns strict JSON; we parse defensively (some
OpenAI-compatible backends wrap JSON in code fences or ignore response_format).

Returns (raw_shots, usage) — raw_shots feed compiler.compile_shots, usage feeds
the metrics ledger. No assertion validation happens here; that's the compiler's job.
"""

from __future__ import annotations

import json
from typing import Any

from server.specs import ASSERTION_META, CAMERA_DIRECTIONS, AssertionType

_SYSTEM = """You are the shot planner for Dailies, a system that generates and then \
QC-checks short AI video shots. Break the premise into a short sequence of single-take, \
~5-second shots. For each shot provide:
- prompt: a vivid text-to-video prompt — ONE continuous shot, ONE clear action.
- negative_prompt: optional; artifacts/content to avoid.
- subject: optional; the key recurring subject/character to track across shots.
- narration: the one line spoken over this shot. AT MOST 12 WORDS — it is synthesized to \
audio and hard-truncated at the shot's ~5 seconds, so a longer line is cut off mid-word. \
Write the story, not the frame: it should carry meaning the picture cannot, and read as \
one continuous voice-over when the shots play back to back. Never name the shot number.
- speaker: optional; the character who SAYS that line, named EXACTLY as in subject so the \
same character is recognised across shots. Set it only when the line is that character's \
own words, and write those words in first person. Omit it for narrator voice-over, which \
should be third person. Do NOT name a voice or an actor — casting is not yours to choose.
- assertions: machine-checkable claims about the RENDERED clip, chosen ONLY from the \
closed vocabulary below. Add one only when the prompt justifies it (a panning shot -> \
camera_motion; a named character -> subject_present/identity_consistent; a finished \
action -> action_completed).

Closed assertion vocabulary — use these types and params EXACTLY; never invent types:
{vocab}

Do NOT restate duration/brightness/flicker/scene_cuts — those defaults are applied \
automatically. Output STRICT JSON only:
{{"shots": [{{"prompt": "...", "negative_prompt": "...", "subject": "...", \
"narration": "...", "speaker": "...", \
"assertions": [{{"type": "...", "params": {{...}}}}]}}]}}"""


def _vocabulary_doc() -> str:
    lines: list[str] = []
    for t, meta in ASSERTION_META.items():
        params = ", ".join(meta.required) or "(none)"
        note = f" (direction in {sorted(CAMERA_DIRECTIONS)})" if t is AssertionType.CAMERA_MOTION else ""
        flags = f"tier={meta.tier.value}" + (", advisory" if meta.advisory else "")
        lines.append(f"- {t.value} [{flags}] params: {params}{note}")
    return "\n".join(lines)


def _extract_json(content: str) -> dict[str, Any]:
    """Tolerate ```json fences / stray prose around the object."""
    s = content.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end != -1:
        s = s[start : end + 1]
    return json.loads(s)


_CUSTOM_SYSTEM = """You compile plain-language QC rules — written by a non-technical \
stakeholder — into machine-checkable assertions for an AI-generated video shot. Choose ONLY \
from the closed vocabulary below; never invent a type. A single rule may map to zero, one, or \
several assertions.

Closed assertion vocabulary — use these types and params EXACTLY:
{vocab}

If a rule CANNOT be expressed with this vocabulary — e.g. it needs audio/transcript, on-screen \
text/OCR, counting occurrences, or a specific time window like "first 3 seconds" / "the outro" \
— OMIT it entirely rather than approximating with a type that means something else. Output \
STRICT JSON only: {{"assertions": [{{"type": "...", "params": {{...}}}}]}}"""


def compile_custom_rules(
    rules: list[str],
    *,
    client,
    model: str,
    temperature: float = 0.0,
    max_tokens: int = 800,
) -> tuple[list[dict[str, Any]], Any]:
    """Compile user-authored plain-language QC rules into raw assertion dicts.

    Mirrors script_and_specs: constrained to the closed vocabulary via the SAME
    _vocabulary_doc(), returns raw dicts (validation is the compiler's job, via
    parse_assertions). Rules needing an unsupported modality are omitted, not faked.
    """
    numbered = "\n".join(f"{i+1}. {r}" for i, r in enumerate(rules))
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _CUSTOM_SYSTEM.format(vocab=_vocabulary_doc())},
            {"role": "user", "content": f"Rules:\n{numbered}"},
        ],
        response_format={"type": "json_object"},
        temperature=temperature,
        max_tokens=max_tokens,
    )
    data = _extract_json(resp.choices[0].message.content or "{}")
    out = data.get("assertions", [])
    if not isinstance(out, list):
        raise ValueError("custom-rule compiler returned non-list 'assertions'")
    return out, resp.usage


def script_and_specs(
    premise: str,
    *,
    pack,
    max_shots: int,
    client,
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 1500,
):
    user = (
        f"Premise: {premise}\n\n"
        f"Produce at most {max_shots} shots for pack '{pack.name}'"
        + (f" ({pack.description})." if pack.description else ".")
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM.format(vocab=_vocabulary_doc())},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = resp.choices[0].message.content or "{}"
    data = _extract_json(content)
    shots = data.get("shots", [])
    if not isinstance(shots, list):
        raise ValueError("script agent returned non-list 'shots'")
    return shots[:max_shots], resp.usage

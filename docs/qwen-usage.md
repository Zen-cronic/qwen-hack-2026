# Qwen Cloud usage — API surface, mapped to the judging rubric

How Dailies uses Qwen Cloud, and why each use is *sophisticated* rather than a bare prompt
call. Written for a judge scoring **Innovation & AI Creativity (30%)** and **Technical Depth
& Engineering (30%)**, both of which name "sophisticated use of QwenCloud APIs (e.g. custom
skills, MCP integrations)" explicitly.

Every platform fact below (endpoints, parameters, the split between the two API transports,
what `tool_choice` and `response_format` accept) is checked against Alibaba Cloud Model
Studio / DashScope documentation; every *our-side* fact points at the file that implements
it. Live-API evidence for this project's own calls is in [verification.md](verification.md).

## The rubric, concretely

The Build Session FAQ publishes four weighted categories. Stated in full so the mapping
below is auditable:

| Weight | Category | What it measures |
|---|---|---|
| **30%** | **Innovation & AI Creativity** | Sophisticated use of Qwen Cloud APIs — *custom skills, MCP integrations*. Algorithmic / engineering innovation — novel solutions, custom components, performance optimization. |
| **30%** | **Technical Depth & Engineering** | Architecture quality — modularity, scalability, error handling. Engineering excellence — clean code, non-trivial logic. Tech-stack sophistication — advanced patterns, thoughtful adoption. |
| **25%** | **Problem Value & Impact** | Real-world utility, commercial paths, community/open-source viability. (See [impact.md](impact.md).) |
| **15%** | **Presentation & Documentation** | Clarity of technical visualization/data and structural code diagrams. (See [architecture.md](architecture.md), [profiling.md](profiling.md), and this file.) |

## What "sophisticated" means on this platform

Qwen Cloud exposes the same models over **two transports**, and advanced usage is largely
about picking the right one per capability and driving its non-default controls:

- **OpenAI-compatible** — `…/compatible-mode/v1`. Fronts the chat LLMs, Qwen-VL, Qwen-Coder,
  Qwen-Omni. Function calling via the OpenAI `tools` array; `tool_choice` supports `auto` /
  `none` / `required` / a named-function object; `parallel_tool_calls` (default off) returns
  several calls at once; `response_format={"type":"json_object"}` is the *only* structured
  mode — there is **no** `json_schema` enforcement on Model Studio.
- **DashScope-native** — `…/api/v1/services/aigc/…`. The async media surface: Wan video/image
  generation is **mandatorily asynchronous** (create task + `X-DashScope-Async: enable`, then
  poll `GET /api/v1/tasks/{id}`; no OpenAI-compatible mode exists for video), and Qwen-TTS is
  the synchronous `multimodal-generation` route.

Above the raw API sit **Qwen-Agent** (a framework with `@register_tool` custom tools, native
MCP via an `mcpServers` block, a Docker code-interpreter, and built-in RAG) and **Model
Studio Applications** (a no-code agent/plugin builder plus a Bailian-hosted MCP marketplace).
A submission can *consume* those, or it can *build the equivalent* against the raw API. Dailies
does the latter where the domain demands it, and uses the framework where it is the honest fit
— the sections below say which, and why.

## The surface Dailies exercises

Seven model roles across four API families, plus both integration frameworks the rubric names.

| Surface | Transport / entry | Models | What is non-trivial |
|---|---|---|---|
| **Wan video** | native async `…/video-generation/video-synthesis`, `…/image2video/video-synthesis`, `…/text2image/image-synthesis` + `/tasks/{id}` | `wan2.1-t2v-turbo` (draft), `wan2.2-i2v-flash` (frame-anchored final + repair)·`wan2.1-i2v-turbo`·`wan2.1-kf2v-plus`, `wan2.2-t2v-plus` (t2v final fallback), `wan2.1-t2i-plus` (still) | async poll with terminal-status branching; per-model frame-size negotiation; frame-anchored i2v via inline data-URI (no OSS upload); content-addressed replay cache |
| **Qwen-VL** | compat chat + `image_url` parts | `qwen-vl-plus` | two verifier tiers (1 still / 7 strided frames); JSON verdicts; per-shot token accounting; degrade-to-`INCONCLUSIVE` |
| **Qwen chat + function calling** | compat chat + `tools` | `qwen-plus` | two tool-call loops — `run_shot_tests` and plan-authoring `build_pipeline_graph` (`tool_choice="auto"`), transcript captured as evidence |
| **Qwen-TTS** | native `…/multimodal-generation/generation` | `qwen3-tts-flash` | per-shot narration, `voice` required, same replay cache |
| **Structured output** | `response_format={"type":"json_object"}` | `qwen-plus` | script + repair emit parseable JSON, no prose scraping |
| **Qwen-Agent** | `qwen_agent.agents.Assistant` | `qwen-plus` | custom `BaseTool` via `@register_tool`; `mcpServers` block; `fncall_prompt_type="nous"` |
| **MCP** | FastMCP stdio server + Qwen-Agent MCP client | — | `run_shot_tests` + `patch_clip` tools; installable `dailies-mcp` console script; closed loop, both ends ours |

Base URLs and the model roster live in one place — `server/config.py` — and the sanctioned
endpoints are in [hackathon.md](hackathon.md).

## A. One conformance engine, three Qwen integration shapes

The load-bearing idea for the Innovation axis: **the same deterministic verification function
(`run_shot_tests`) is exposed to a Qwen model three different ways**, so "custom skills" and
"MCP integrations" are not claims — they are three runnable code paths over one contract.

1. **Native OpenAI-compatible function calling** — `RUN_SHOT_TESTS_TOOL` is the JSON-Schema
   tool spec; `call_with_function_calling()` runs the tool-call loop against `qwen-plus` and
   returns a transcript of every call + result. `server/qwen_tools.py`.
2. **Qwen-Agent custom tool ("skill")** — `register_qwen_agent_tool()` registers a `BaseTool`
   subclass via the framework's `@register_tool` decorator; `build_conformance_agent()` wires
   it into an `Assistant`. `server/qwen_tools.py`.
3. **MCP tool** — `server/mcp_server.py` publishes it (and `patch_clip`) over the Model Context
   Protocol; `server/mcp_agent.py` has a Qwen-Agent client consume it. See section D.

The shared core (`run_shot_tests_json`) imports neither `openai` nor `qwen_agent`, so it is
unit-tested on its own and the three wrappers import lazily — a modularity point for the Depth
axis. Both live loops spend only chat tokens (no video quota): `scripts/qwen_tool_demo.py`
drives shapes 1–2, `scripts/mcp_agent_demo.py` drives shape 3.

## B. Function calling / tool use

The platform documents four `tool_choice` modes (`auto`, `none`, `required`, named-function)
and `parallel_tool_calls`. Dailies runs **two independent function-calling loops**, both at
`temperature=0` for reproducibility:

- **Conformance-as-a-tool** (`server/qwen_tools.py`) — `qwen-plus` decides when to call
  `run_shot_tests`, we execute the deterministic CV checks, feed the JSON report back as a
  `role:"tool"` message with the matching `tool_call_id`, and loop until the model answers in
  natural language. This is the canonical multi-round tool loop, hand-built on the
  OpenAI-compatible endpoint.
- **Agent-authored pipeline** (`server/agent_plan.py`, route `server/app.py` `POST
  /api/agent/plan`) — the headline demo. A user types a request; `qwen-plus` calls
  `build_pipeline_graph` with `tool_choice="auto"`, emitting run *parameters* (`premise`,
  `pack`, `max_shots`, `custom_checks`). The server deterministically expands those into the
  canonical node/edge graph. **The model authors the run but cannot emit a malformed graph,
  because it never emits topology** — a design that turns "agent wired the pipeline" into a
  truthful, un-break­able claim. The full tool-call transcript is returned to the UI as
  judge-facing evidence.

*Rubric:* custom-skill function calling (Innovation); a tool loop that gates side-effectful
video spend behind a validated parameter contract (Depth).

## C. Custom skills

"Custom skill" has two concrete meanings on this platform, and Dailies implements both:

- **Qwen-Agent custom tool** — a `BaseTool` with `description` + `parameters`, registered via
  `@register_tool` and passed in an `Assistant`'s `function_list` (`server/qwen_tools.py`).
  This is the framework's own custom-skill mechanism, used verbatim.
- **Native tool spec** — the same capability as a raw JSON-Schema `tools` entry for callers who
  do not want the framework dependency (`RUN_SHOT_TESTS_TOOL`).

Both wrap a **closed-vocabulary** assertion validator: an invented or malformed assertion is
rejected by `parse_assertions` before anything runs, so the skill cannot be talked into
checking something it does not implement. That closed vocabulary (`server/specs.py`,
`packs/*.yaml`) is the reusable "skill" surface — assertions-as-data, not prompts.

## D. MCP — producer *and* consumer, loop closed

The documented Model Studio MCP path is *consumption*: register up to 10 external SSE MCP
servers in a Responses-API `tools` block, or pull one from the Bailian MCP marketplace.
Dailies goes further — **it is an MCP *producer*.**

- **Server** (`server/mcp_server.py`) — a `FastMCP("dailies")` server exposes two tools over
  stdio: `run_shot_tests` (zero-token, deterministic Tier-A CV, runs on *any* mp4 — the
  model-agnostic claim made executable) and `patch_clip` (localizes the first blocking failure
  in time, anchors a Wan i2v regeneration just before it, re-verifies, and only reports
  `patched` if the retake passes). It is an installable console script — `uvx --from '.[mcp]'
  dailies-mcp` — so the productization surface is runnable, not asserted.
- **Client** (`server/mcp_agent.py`) — a Qwen-Agent `Assistant` with Dailies' own server in
  its `mcpServers` block, so `qwen-plus` invokes the conformance tool *through* the protocol.
  Both ends are ours; `scripts/mcp_agent_demo.py` runs the whole loop on chat tokens alone.

*Rubric:* the rubric's named "MCP integration" example, implemented as the harder direction
(exposing a domain capability as an MCP tool a Qwen model calls), not merely wiring a stock
server in.

## E. Wan video — the async lifecycle, driven correctly

Wan is mandatorily asynchronous, and Dailies drives the full lifecycle by hand over `httpx`
rather than leaning on the SDK's blocking `wait()` — which is what lets it thread cost
accounting and caching through every call (`server/wan.py`).

- **Create + poll** — `X-DashScope-Async: enable` on create, poll `/tasks/{id}` every 15 s,
  branch on the *polled* `task_status` (`SUCCEEDED`/`FAILED`/`CANCELED`/`UNKNOWN`/timeout).
  This encodes a verified platform gotcha: **HTTP 200 on create does not mean valid** —
  validation surfaces asynchronously on the first poll ([verification.md §3](verification.md)).
- **A cost ladder, not one model** — cheap `wan2.1-t2v-turbo` drafts; promotion happens only on
  a passing draft and renders as a frame-anchored `wan2.2-i2v-flash` continuation of it, so the
  certified clip inherits the look the human approved instead of re-rolling from noise
  (`wan2.2-t2v-plus` remains the t2v fallback when no anchored model is wired). All of it runs
  through **per-model frame-size negotiation** (`wan2.2-t2v-plus` rejects `1280*720`; the size is
  part of the cache key, so a wrong guess both fails the request and poisons the cache).
- **Frame-anchored repair** — the novel component. `generate_video_from_frame` sends the anchor
  frame **inline as a base64 `data:` URI**, so a repair can hold a composition that lives only
  on this box with no OSS upload step; the frame bytes salt the cache key so two repairs of one
  shot don't collide. This is the i2v `media`/`img_url` input used for targeted repair rather
  than fresh generation.
- **Content-addressed replay cache** — every clip is addressed by `sha1(model|prompt|seed|
  size|negative)`. Identical inputs replay for free, which is what lets a judge re-verify
  cached clips at **zero video quota** while genuine repairs (which change the prompt) still
  generate fresh.

*Rubric:* async task orchestration with correct error handling, a cost-optimizing model ladder,
and a genuinely novel repair primitive (Depth + Innovation). Cost/latency numbers per tier are
in [profiling.md](profiling.md).

## F. Qwen-VL — two verifier tiers with token accounting

`qwen-vl-plus` answers the questions deterministic CV cannot, at two points where a rejection
is still cheap:

- **Tier-0** (`server/tier0.py`) — one **pre-render still**, downscaled to 512 px (VLM image
  tokens scale with pixels), asks `subject_present` before any video spend — the cheapest
  rejection the pipeline can make.
- **Tier-B** (`server/tier_b.py`) — **7 strided frames** of the finished clip as a multi-image
  message, asks the motion questions (`identity_consistent`, `action_completed`,
  `title_card_present`). Advisory by design: a VLM judgment is softer evidence than a pixel
  measurement, so a Tier-B FAIL informs the human but never auto-blocks promotion.

Both send frames as base64 `image_url` parts, force **strict JSON verdicts**, and — the
engineering detail — expose `pop_last_usage()` so the pipeline logs VLM prompt/completion
tokens per shot with **no special-casing in the pipeline loop**. Errors degrade to
`INCONCLUSIVE`; a broken VL call must never fabricate a FAIL.

*Rubric:* multimodal understanding placed where it is economically rational, with per-tier cost
observability (Depth) and a human-in-the-loop trust boundary (Impact).

## G. Qwen-TTS — narration, cached like video

Wan clips are silent, so a certified episode was silent too. `server/tts.py` synthesizes one
narration line per shot with `qwen3-tts-flash` on the synchronous DashScope-native
`multimodal-generation` route (`voice` is **required** — omitting it is a 400, not a default),
downloads the expiring OSS URL immediately, and caches by `sha1(model|voice|text)` so a
judge-mode replay stays at zero spend. The assembler muxes it under each clip.

*Rubric:* a third Qwen modality (speech) integrated end-to-end, reusing the same replay-cache
discipline as video (Depth); a demo that plays with sound (Presentation).

## H. Structured output — `json_object`, and why not `json_schema`

Model Studio's only structured-output mode is `response_format={"type":"json_object"}` (the
prompt must contain the literal word "JSON"); there is **no `json_schema` constraint** on the
platform. Dailies uses `json_object` where the output is consumed by code — script generation
and repair planning (`server/script.py`, `server/repair.py`). The VL tiers instead ask for
"STRICT JSON only" and parse with a tolerant `_extract_json` (some backends fence JSON in code
blocks); this is a deliberate robustness choice for the multimodal path, not an oversight — see
"deliberately not used" below.

## What Dailies deliberately does not use (and why)

Honesty sharpens the sophistication claim — these are choices, not gaps:

- **No-code Model Studio Applications / plugin builder** — the console agent-builder would hide
  the exact ledger/spend accounting, evidence dirs, review gate, and promotion fallback the
  pipeline is *about*. Building the orchestration in code is what makes those inspectable.
- **Bailian MCP marketplace / Responses-API MCP consumer flow** — we produce an MCP tool rather
  than consume stock ones, because the reusable asset here is *our* conformance engine.
- **Qwen3-VL native `video_url` + `fps` sampling** — `qwen3-vl-plus` can ingest an mp4 directly
  and sample frames server-side. We extract and stride frames ourselves (`cv2`) so frame count,
  resolution, and therefore **token cost are deterministic and logged per shot** — the pipeline
  is a cost story, and handing frame selection to the model would forfeit that. A documented
  upgrade path, taken with eyes open.
- **`parallel_tool_calls` / `tool_choice:"required"`** — both loops are single-tool by design
  (`build_pipeline_graph` is called exactly once; the conformance loop is inherently
  sequential), so forcing parallelism would add surface without value.
- **Qwen-Agent RAG / code-interpreter** — real capabilities, but out of domain for a video-QC
  pipeline; adopting them for their own sake would be the opposite of "thoughtful adoption."
- **Streaming (`X-DashScope-SSE`) / audio-driven Wan (`audio_url`)** — the pipeline is batch and
  poll-driven end to end; TTS is synthesized separately and muxed, which keeps narration cached
  and swappable. Streaming buys nothing for a review artifact.

## Evidence map

| Rubric criterion | Evidence in this repo | File |
|---|---|---|
| Custom skills | conformance engine as native FC tool + Qwen-Agent `@register_tool` `BaseTool` | `server/qwen_tools.py` |
| MCP integration | FastMCP server (`dailies-mcp`) + Qwen-Agent MCP client, loop closed | `server/mcp_server.py`, `server/mcp_agent.py` |
| Agentic tool use | `qwen-plus` authors the run via `build_pipeline_graph` (`tool_choice`), transcript surfaced | `server/agent_plan.py`, `server/app.py` |
| Novel component | frame-anchored i2v repair (inline data-URI anchor, failure localized in time) | `server/wan.py`, `server/patch.py` |
| Performance optimization | content-addressed replay cache → zero-quota re-verification; per-tier token/latency accounting | `server/wan.py`, `server/tts.py`, [profiling.md](profiling.md) |
| Error handling | async poll branches on task status, not HTTP 200; VL errors degrade to `INCONCLUSIVE` | `server/wan.py`, `server/tier0.py`, `server/tier_b.py` |
| Multimodal breadth | Wan t2v/i2v + t2i, Qwen-VL image/video, Qwen-TTS speech — one pipeline | `server/config.py` (roster) |
| Structured output | `response_format={"type":"json_object"}` for code-consumed generations | `server/script.py`, `server/repair.py` |
| Thoughtful adoption | deliberate non-use of no-code apps, native video-VL, streaming — with rationale | this file, above |

Live-API proof for these calls: [verification.md](verification.md). System diagrams:
[architecture.md](architecture.md).

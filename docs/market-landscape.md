# Market landscape — where Dailies sits among the tools that exist

*A web-grounded survey (2026-07-14, 7 parallel research agents, ~30 recorded search queries;
repo facts re-verified via the GitHub API 2026-07-18). It exists because an improvement
statement should be checkable — and because this survey changed ours.*

## The claim, before and after

An earlier draft of this repo's README claimed Dailies was *"the first shipped per-shot
conformance harness."* This survey falsified the letter of that claim: OpenMontage
(2026-03-29) and Kinocut (2026-03-21) both pre-date it and both gate video before release.
So the README now claims the narrower thing the survey could **not** find anywhere:

> the only **standalone, model-agnostic per-shot conformance gate** — authored shot specs
> compile through a closed assertion DSL into a cost-tiered cascade with bounded repair.

Every element of that sentence is load-bearing, because each one is where an otherwise-close
project diverges: *per-shot* (OpenMontage gates at video level), *authored spec + closed DSL*
(every surveyed critic loop uses LLM-generated or hardcoded natural-language rubrics),
*standalone/neutral* (every surveyed gate grades its own pipeline's output), *cost-tiered
with a deterministic zero-token spine* (every surveyed check spends model tokens), *bounded
repair* (research code only). The combination is what's absent — this file is the evidence
trail, kept in the repo so the claim can be audited rather than trusted.

## Commercial products that sound adjacent (none ships output verification)

Four products that come up as "doesn't X already do this?" — surveyed specifically for
whether they check generated output against a spec:

| Product | What it ships | QC of generated output | Relation to Dailies |
|---|---|---|---|
| **fal** (fal.ai) | Generative media inference infra: 600+ hosted image/video/3D/audio models, Workflows chaining, serverless GPUs. $4.5B valuation (Series D, Dec 2025); customers incl. Canva, Perplexity, Shopify. | **None.** Workflows chain models with no quality branching; the changelog through mid-2026 has zero output-QC entries; only NSFW/harm safety filters. Competitor Runflow markets against exactly this gap: "fal has no quality layer… returns raw output." | Complementary — the substrate to gate. Dailies' cascade (draft model → checks → premium promotion) maps directly onto fal-hosted models. |
| **Overshoot** (overshoot.ai) | Real-time vision inference API (YC W26): live video streams in, <200ms VLM analysis out, frame-anchored queries, JSON-schema outputs. | **None.** Stream-in/chat-out; validation is explicitly left to application code. | Complementary — plumbing a VLM tier could ride on. Generates nothing, scores nothing. |
| **ngram** (ngram.com) | Release-notes/docs/URL → branded announcement-video SaaS (script, storyboard, motion graphics, voiceover, brand kit; REST API, MCP server). Customers incl. Veeva, DocuSign, HubSpot. | **None automated.** The only gate is human storyboard approval *before* render — authoring-side, like LTX Studio. The brand kit is apply-side templating, not a post-render check. | Complementary — a pipeline a gate sits downstream of. |
| **Clueso** (clueso.io) | Screen-recording → polished product/tutorial video + docs; MCP for video *creation* shipped Jun 2026. 1,000+ customer orgs. | **None.** Review is human timestamped comments; brand kit is templating, not enforcement. | Complementary, different substrate (real captures, not generated shots). Its creation-MCP signals the "an agent produced the mp4, something must gate it" workflow going mainstream. |

The pattern across all four is the pitch's premise, not its refutation: generation and
inference infrastructure keeps shipping; output conformance doesn't.

## What the sweep actually found (and how each differs)

| Finding | Overlap | What it ships, and where it diverges |
|---|---|---|
| **OpenMontage** ([github.com/calesthio/OpenMontage](https://github.com/calesthio/OpenMontage), created 2026-03-29, AGPL-3.0, ~39.8k stars — verified via API 2026-07-18) | Closest in shape | Agentic video production system with hard-gated post-render self-review against an authored "delivery promise" (ffprobe validation, black-frame detection, audio silence/clipping, subtitle checks — the video is not presented if review fails). Diverges on every element of the claim: video-level not per-shot, self-grading inside its own pipeline, no assertion grammar, no cost cascade, no repair loop, no gate for external mp4s. |
| **Kinocut** ([github.com/KyaniteLabs/mcp-video](https://github.com/KyaniteLabs/mcp-video), created 2026-03-21, Apache-2.0) | Adjacent | Guardrailed FFmpeg MCP server (142 tools) including `video_quality_check` and `release_checkpoint` — proof the *MCP-gate mechanism* is not novel on its own. Checks are generic technical QC with human-gated verdicts; no shot spec, no semantic checks, no repair. |
| **VideoRepair** ([github.com/daeunni/VideoRepair](https://github.com/daeunni/VideoRepair), UNC/Adobe, arXiv 2411.15115) | Same shape, research | Public, runnable detect-misalignment-then-repair code — the skeleton of a VLM tier + prompt repair. Benchmark-oriented; no DSL, no packaging, no cascade. "The loop exists in research" is true; "the loop ships as a usable gate" is what it lacks. |
| **promptfoo** | Adjacent — the one to watch | Owns the assertion-DSL + CI-gating shape for LLM output, and has added video-gen providers (Sora, Veo) plus multimodal red-teaming. It does not read frames today. If it ships frame-level video assertions, it becomes the closest thing to Dailies in existence. |
| Broadcast QC (Interra BATON, Elecard Quality Gates) | Adjacent, decades old | Per-file video gating against authored *technical* specs (codec compliance, loudness, black frames) has shipped for a decade. The claim here is scoped accordingly: creative/semantic conformance of AI-generated shots, not delivery-spec QC. |
| Adobe GenStudio, Pencil, Typeface, Canva, AdCreative.ai | Adjacent, platform-locked | Brand/regulatory scoring of generated assets exists as a category — static rules, own-output scoring, or locked to one vendor's stack. See [impact.md](impact.md) for the honest concession: inside Adobe's stack, on Adobe's models, Adobe wins. |
| VBench / EvalCrafter / VideoScore / Video Arena | Complementary | Model-level evaluation on benchmark suites — grades *models*, not *your shots against your spec*. Their metric code is raw material for expanding the assertion vocabulary. |
| ViMax / CoAgent (arXiv 2512.22536) / VISTA (arXiv 2510.15831) / Genflow Ad Studio (arXiv 2605.16748) | Adjacent, research | VLM-judge-scores-own-candidates-with-retry appears repeatedly in 2025–26 research — validating the loop — but all self-grade inside their own generation systems; none is a neutral gate, none has a deterministic tier, none ships. |
| Wireflow "AI Video Pipeline" | Unverified | Marketing copy describes validation nodes with retry-on-failure; the homepage feature list doesn't carry it. Listed for completeness, treated as unconfirmed. |

## What would change this analysis

Honest tripwires — each names the event that would force this document's conclusions to be
rewritten:

- **promptfoo ships frame-reading video assertions** → the closed-DSL + CI shape stops being
  unique to Dailies; the differentiator narrows to the deterministic tier and the
  human-override calibration corpus ([impact.md](impact.md)).
- **fal Workflows adds a quality/branching stage** → the substrate starts absorbing the gate.
- **OpenMontage goes per-shot or opens its review to external input** → the closest-in-shape
  project closes two of its five gaps.
- **Wireflow's validation nodes turn out to be real** → re-run this survey against it.

## Sources

Product claims: fal.ai docs (Workflows, changelog), fal Series C/D announcements,
runflow.io/compare/fal, sacra.com/c/fal-ai; docs.overshoot.ai and YC launch pages; ngram.com
(changelog-video, brand-kit, pricing); clueso.io (changelog, pricing, video features). Sweep
findings: the GitHub repos linked inline (star counts and creation dates re-verified via the
GitHub API on 2026-07-18); arXiv 2411.15115 (VideoRepair), 2512.22536 (CoAgent), 2510.15831
(VISTA), 2605.16748 (Genflow); business.adobe.com (GenStudio brand compliance);
interrasystems.com; elecard.com; artificialanalysis.ai/video.

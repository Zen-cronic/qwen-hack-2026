# Submission deliverables — verbatim-sourced from Devpost /rules + update 45055

- [ ] **Public open-source repo** — license file "detectable and visible at the top of the repository page"; contains "all necessary source code, assets, and instructions required for the project to be functional"
- [ ] **Code file with the Qwen Cloud Base URL clearly visible** — sanctioned base URLs:
  - `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`
  - `https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` (OpenAI-compatible)
  - `https://token-plan.ap-southeast-1.maas.aliyuncs.com/apps/anthropic` (Anthropic-compatible)
- [ ] **Screenshot of running resources from Alibaba Cloud Workbench** — "No proof = not eligible"
- [ ] **Architecture diagram** — "how Qwen Cloud connects to your backend, database, and frontend"
- [ ] **Demo video** — "less than three (3) minutes", public on YouTube/Vimeo/Youku, "must include footage that shows the Project functioning on the device for which it was built", "not a Figma mockup — real working app!", no third-party trademarks / copyrighted music
- [ ] **Text description** — features + functionality, in English
- [ ] **Track identified** — Track 2: AI Showrunner
- [ ] **Testing access** — link to working demo/site; login credentials if private; free of charge, unrestricted "until the Judging Period ends"
- [ ] (Optional, stacks with track prize) **Blog/social post URL** — "showing your journey building with QwenCloud"; judged on "thoroughness and potential impact"; $500 cash + $500 credits × 10 winners

## Problem Value & Impact

Full argument in [docs/impact.md](docs/impact.md). In brief:

**The pain (authentic, already attested in this repo).** Every team adopting AI video has
quietly appointed a human test suite — one person who eyeballs each clip for brand palette,
length, flicker, character continuity, and whether the brief was followed — and that person is
the bottleneck for everyone upstream who *owns* "correct" but can't check it themselves. The
codebase names this exact user (`packs/brand_rules.yaml`, `PLAN.md`: "a one-person social team
shipping unattended AI video"). The insight is organizational: the person who **defines** correct
(brand/legal/marketing) isn't the person who **operates** the generator, and today those roles are
coupled through a human reviewer. Dailies decouples them — the stakeholder authors a
machine-checkable spec once, and every shot is tested against it automatically. The buyer is
**marketing ops**, who already pays for those review hours and owns brand-risk liability.

**Why won't Mux/Adobe just build this?** Generators can't credibly grade their own output (a green
light from the vendor whose model failed is marking its own homework — and each covers only its own
model), and Mux sells neutral *extraction* to engineers, not a *conformance verdict* to producers.
Adobe GenStudio/Firefly ships the closest loop (brand-check → score → regenerate) but it's
locked to the Adobe stack on static brand rules; Dailies is the **neutral gate for the multi-model
shop generating outside any one vendor's walled garden** (honest concession: inside Adobe's stack,
Adobe wins). The one moat with a real mechanism is the **human-override calibration corpus** captured
at the approve gate — collectable only from the buyer-side review seat.

**Productization / OSS path.** Assertion packs are *data, not code*, so the engine lifts out as a
consumable `@dailies/vidtest` package and an **MCP server** (`run_shot_tests`, shipped in
`server/mcp_server.py`) that lets any pipeline or agent gate video the way it already gates code.
It is model-agnostic by construction — checks take frames, not generator internals — so assertion
packs run as CI regression tests that *outlive any one generator*.

**Honest scope.** Today Dailies deterministically gates the mechanical guarantees (palette ΔE,
duration, flicker, scene-cuts, camera-motion) at zero token cost and adds VLM-advisory judgments
(identity continuity, briefed-action, title-card present), all authored in natural language and
compiled to a closed, rejected-before-spend vocabulary; transcript/OCR/count and time-windowed
"outro" checks are named, published **roadmap** — not claimed as built.

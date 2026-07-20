# Submission deliverables — verbatim-sourced from Devpost /rules + update 45055

- [x] **Public open-source repo** — license file "detectable and visible at the top of the repository page"; contains "all necessary source code, assets, and instructions required for the project to be functional".
  Root [LICENSE](LICENSE) is verbatim MIT, which GitHub auto-detects and renders in the About
  sidebar; also declared in `pyproject.toml`.
- [x] **Code file with the Qwen Cloud Base URL clearly visible** — sanctioned base URLs:
  - `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`
  - `https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` (OpenAI-compatible)
  - `https://token-plan.ap-southeast-1.maas.aliyuncs.com/apps/anthropic` (Anthropic-compatible)

  Submit [server/config.py](server/config.py) — the sanctioned URL is a literal there
  (`QWEN_BASE_URL`, `DASHSCOPE_BASE_URL`). It also appears in `.env.example`,
  `docker-compose.yml`, and `server/wan.py`'s module docstring.
- [ ] **Proof of Alibaba Cloud deployment** — "No proof = not eligible". The rules and the FAQ
  word this differently, so satisfy both: (a) screenshot of running resources from the Alibaba
  Cloud Workbench — **still to capture**, per [deploy.md](docs/deploy.md) "Eligibility"; and
  (b) "a link to a code file in their code repo that demonstrates use of Alibaba Cloud services
  and APIs" — use [server/wan.py](server/wan.py), which names the DashScope host and drives its
  async task API (submit with `X-DashScope-Async`, poll `/tasks/{id}`, fetch the signed result).
  Corroborating: [server/oss.py](server/oss.py) (OSS SDK) and
  [.github/workflows/deploy-prod.yml](.github/workflows/deploy-prod.yml) (deploys onto the SAS box).
- [x] **Architecture diagram** — "how Qwen Cloud connects to your backend, database, and frontend".
  [docs/architecture.md](docs/architecture.md). If the form takes one image, use the **deployment
  topology** diagram — it names the SAS instance, the Postgres sidecar and OSS explicitly.
- [ ] **Demo video** — "less than three (3) minutes", public on YouTube/Vimeo/Youku, "must include footage that shows the Project functioning on the device for which it was built", "not a Figma mockup — real working app!", no third-party trademarks / copyrighted music.
  Rendered at 2:00; **upload and paste the URL here.**
- [x] **Text description** — features + functionality, in English. [README.md](README.md); the
  impact narrative is below and in [docs/impact.md](docs/impact.md).
- [x] **Track identified** — Track 2: AI Showrunner
- [ ] **Testing access** — link to working demo/site; login credentials if private; free of charge, unrestricted "until the Judging Period ends".
  The box's public IP is deliberately absent from this repo; it goes in the Devpost field only.
  Confirm the runtime first: `curl http://<host>/api/health` should not report `mode: "real"` for
  an unattended URL — see [deploy.md](docs/deploy.md) on the fresh-final cap.
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
consumable Python package — runnable today, unpublished to PyPI yet: `uvx --from '.[mcp]'
dailies-mcp` — and an **MCP server** (`run_shot_tests` to report, `patch_clip` to repair, both
in `server/mcp_server.py`) that lets any pipeline or agent gate video the way it already gates code.
It is model-agnostic by construction — checks take frames, not generator internals — so assertion
packs run as CI regression tests that *outlive any one generator*.

**Honest scope.** Today Dailies deterministically gates the mechanical guarantees (palette ΔE,
duration, flicker, scene-cuts, camera-motion) at zero token cost and adds VLM-advisory judgments
(identity continuity, briefed-action, title-card present), all authored in natural language and
compiled to a closed, rejected-before-spend vocabulary; transcript/OCR/count and time-windowed
"outro" checks are named, published **roadmap** — not claimed as built.

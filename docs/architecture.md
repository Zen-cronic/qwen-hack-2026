# Dailies architecture

> A rendered version of this is a REQUIRED submission deliverable: "how Qwen Cloud
> connects to your backend, database, and frontend."

Modeled with the [C4 model](https://c4model.com): **Level 1 (System Context)** — who
uses Dailies and which external systems it talks to — and **Level 2 (Container)** — the
deployable/runnable units inside Dailies and how a request flows through them. Levels 3–4
(component/code) are omitted deliberately: they would duplicate the source under
`server/`, which is the ground truth. The diagrams therefore stay at container/stage
altitude and name no source files; the file that backs each box is named in the prose
underneath, so every box is still traceable to code you can open.

**Diagram conventions.** Each diagram has a title (type + scope) and a legend. Colour is
sparse and purposeful: neutral fills for containers and external systems, a light accent
for actors, and **red reserved for the one path that matters most — reject-before-spend
(an assertion outside the closed DSL) and the blocking conformance failure that triggers
auto-repair.**

## Level 1 — System Context

```mermaid
---
title: "C4 Level 1 — System Context: Dailies (CI for AI-generated video)"
---
flowchart TB
    stakeholder["Brand / marketing / legal stakeholder<br/><i>Person</i><br/>Authors the shot spec: premise,<br/>assertion pack, plain-language checks"]:::person
    operator["Marketing-ops operator<br/><i>Person</i><br/>Runs batches; approves the one<br/>human gate before any video spend"]:::person

    dailies["Dailies<br/><i>Software System</i><br/>Compiles specs to a closed assertion DSL and runs each<br/>generated shot through a cost-tiered conformance<br/>cascade with bounded auto-repair"]:::system

    qwen["Qwen Cloud<br/><i>External System</i><br/>qwen-plus (chat/repair), qwen-vl-plus (VLM),<br/>wan2.1-t2v-turbo / wan2.2-i2v-flash / wan2.1-t2i-plus<br/>via OpenAI-compat /v1 + native async task API"]:::external
    mcphost["MCP client host<br/><i>External System</i><br/>A Qwen agent / Claude that gates video<br/>by calling run_shot_tests over MCP"]:::external

    stakeholder -->|"authors a machine-checkable spec"| dailies
    operator -->|"starts runs, approves the human gate,<br/>reads the conformance dashboard"| dailies
    dailies -->|"scripting + repair, VLM verdicts, video/image gen"| qwen
    mcphost -->|"gate video like code:<br/>run_shot_tests (Tier-A, zero-token)"| dailies

    subgraph legend["Legend / key"]
        direction LR
        k1["Person (actor)"]:::person
        k2["Dailies (our system)"]:::system
        k3["External system"]:::external
    end

    classDef person fill:#f5f0ff,stroke:#8250df,color:#1c1c22
    classDef system fill:#dbeafe,stroke:#1f6feb,color:#0b2a5b
    classDef external fill:#eceff3,stroke:#6e7781,color:#24292f
```

Two human roles that today are collapsed into one overworked reviewer. The **stakeholder**
owns "correct" and authors the spec once (premise + assertion pack + plain-language custom
checks). The **operator** runs batches and is the only human in the loop at runtime — at the
single review gate before any video is paid for. Dailies drives **Qwen Cloud** for every
model call, and exposes its own conformance engine to an **MCP client host** so any agent can
gate video the way it already gates code.

## Level 2 — Container

```mermaid
---
title: "C4 Level 2 — Containers: how Qwen Cloud connects to the frontend, backend, and store"
---
flowchart TB
    operator["Marketing-ops operator / stakeholder<br/><i>Person</i>"]:::person

    subgraph sys["Dailies — Software System"]
        spa["Web SPA<br/><i>Container: single-page app behind a web server</i><br/>Authoring form + live conformance dashboard"]:::container
        api["Backend API<br/><i>Container: REST service</i><br/>Starts runs, serves the conformance report,<br/>never blocks on a model call"]:::container

        subgraph pipe["Pipeline — background state machine"]
            direction TB
            script["scripting"]:::stage
            compile["compile the spec to a closed assertion DSL"]:::stage
            reject["reject before spend<br/>(assertion outside the DSL)"]:::reject
            gate["still preview + human review gate<br/>the only human in the loop,<br/>before any video is paid for"]:::stage
            draft["draft render"]:::stage
            checks["conformance checks<br/>deterministic CV (blocking, zero-token)<br/>+ advisory VLM verdict"]:::stage
            hardfail["blocking FAIL"]:::reject
            repair["bounded auto-repair"]:::stage
            promote["promote the approved take<br/>(frame-anchored final)"]:::stage
            assemble["assembly + narration mux"]:::stage

            script --> compile
            compile -->|"unsupported sentence"| reject
            compile -->|"valid contract"| gate
            gate -->|"operator approves"| draft
            draft --> checks
            checks -->|"blocking FAIL"| hardfail
            hardfail -->|"retake, bounded"| repair
            repair --> draft
            checks -->|"pass"| promote
            promote --> assemble
        end

        patch["Targeted repair<br/><i>post-run, one shot, outside the pipeline</i><br/>Re-render from the last good frame, re-check,<br/>keep the original clip if it still fails"]:::stage
        ledger["Metrics ledger<br/><i>Container: append-only run log</i><br/>Every model call; derives the<br/>cost-quality frontier"]:::container
        store["Store + snapshots<br/><i>Container: live-run state + media cache</i><br/>Atomic snapshots; identical requests replay for free"]:::container
        catalog["Catalog database<br/><i>Container: relational store, flag-gated</i><br/>A finished run as rows — projects, shots, takes,<br/>assertion results, ledger"]:::container
        reuse["Reuse surface<br/><i>Container: one conformance engine, three ways</i><br/>Function-calling tool · agent skill · MCP server,<br/>plus our own MCP client that closes the loop"]:::container
    end

    qwen["Qwen Cloud<br/><i>External System</i><br/>qwen-plus (chat/repair) · qwen-vl-plus (VLM) ·<br/>qwen3-tts (speech) · Wan (text-to-image,<br/>text-to-video, image-to-video)"]:::external
    mcphost["MCP client host<br/><i>External System</i><br/>A Qwen agent / Claude"]:::external
    disk["Storage volume<br/><i>External: bind-mounted disk</i><br/>Snapshots, run log, cached media"]:::external
    objstore["Cloud object storage<br/><i>External System</i><br/>Published media, private bucket"]:::external

    operator --> spa
    spa -->|"submit a spec, approve the gate,<br/>poll the conformance report"| api
    api -->|"starts the run"| script
    api -->|"repair one shot after the run"| patch
    api -->|"reads state + run log to build the report"| store
    api --> ledger
    patch -->|"pass — becomes the shot final"| assemble

    script -->|"chat"| qwen
    gate -->|"still preview"| qwen
    draft -->|"draft render"| qwen
    checks -->|"VLM verdict"| qwen
    repair -->|"repair prompt"| qwen
    promote -->|"final render"| qwen
    assemble -->|"narration"| qwen
    patch -->|"re-render from anchor"| qwen

    pipe -->|"records every call"| ledger
    pipe -->|"mutates state, atomic snapshot"| store
    store --> disk
    ledger --> disk
    pipe -->|"publishes a finished run"| catalog
    catalog -->|"media by content hash"| objstore

    reuse -->|"reuses the same engine"| checks
    reuse -->|"agent + function-calling loop"| qwen
    mcphost -->|"gate video like code"| reuse

    subgraph legend2["Legend / key"]
        direction LR
        k1["Person"]:::person
        k2["Container (in Dailies)"]:::container
        k3["Pipeline / repair stage"]:::stage
        k4["External system"]:::external
        k5["reject-before-spend / hard-fail"]:::reject
    end

    style sys fill:#f0f6ff,stroke:#1f6feb,color:#0b2a5b
    classDef person fill:#f5f0ff,stroke:#8250df,color:#1c1c22
    classDef container fill:#f6f8fa,stroke:#8b98a9,color:#24292f
    classDef stage fill:#eef4ff,stroke:#4a9eff,color:#0b2a5b
    classDef external fill:#eceff3,stroke:#6e7781,color:#24292f
    classDef reject fill:#ffe3e0,stroke:#cf222e,color:#8b1a12
```

Reading it as the request flows:

- **Web SPA** (`web/src`) is authoring + dashboard in one. It `POST`s a spec to the API and
  then polls `GET /api/projects/:id` every 2.5s; the poll payload already includes the derived
  `metrics` block, so the dashboard *is* a live view of the conformance report.
- **Backend API** (`server/app.py`) validates the pack, creates the project, and spawns the
  pipeline on a **background thread**. It never blocks on model calls; it just serves reads.
- **Pipeline** (`server/pipeline.py`) is the state machine `scripting → DSL compiler → Tier-0
  still → human gate → drafts → Tier-A CV (+ advisory Tier-B VLM) → bounded auto-repair →
  promote → assembly`. Two paths are red: a sentence outside the closed DSL is a **compile
  error rejected before any spend**, and a **blocking Tier-A FAIL** is the only thing that
  triggers a (budget-bounded) retake. Advisory Tier-B verdicts never block promotion.
  **Promotion is frame-anchored**: the certified final continues from the take the human
  approved (`wan2.2-i2v-flash`) rather than re-rolling from noise, so takes of one shot share
  a look. A shot whose contract asserts camera motion skips promotion and ships the approved
  take, because an anchor frame carries composition but not motion — measured, not assumed
  ([verification §3e](verification.md)).
- **Targeted repair** (`server/patch.py`) is the post-run escape hatch: it re-measures the
  failing window, cuts the last good frame as an anchor, re-renders one shot from there, and
  re-verifies. A patch that still fails is discarded and the original clip stays — repair can
  never make a run worse. It does not re-enter the pipeline.
- **Metrics ledger** (`server/metrics.py`, `server/report.py`) records every Qwen/Wan call and
  derives the frontier / heatmap / repair-convergence numbers the dashboard charts.
- **Store + snapshots** (`server/store.py`) is the live-run "database": in-memory state mutated
  under an RLock, written as an **atomic `state.json` snapshot** after each change, plus a
  **content-addressed media cache** so identical (model, prompt, seed) requests replay for free.
- **Catalog (additive, flag-gated)** (`server/catalog.py`, `server/db/models.py`) is the
  production data layer: when a run finishes, it publishes into a **Postgres sidecar**
  (projects / shots / takes / assertion results / cast+voices / ledger — schema
  Alembic-managed) with media uploaded to a **private Alibaba OSS bucket**, object keys in
  columns, and `GET /api/media/...` answering with a presigned 302 when the local file is
  gone. `CATALOG_ENABLED=0` (default) means none of it exists at runtime — live runs never
  depend on it.
- **Reuse surface** (`server/qwen_tools.py`, `server/mcp_server.py`, `server/mcp_agent.py`)
  exposes the same deterministic `run_shot_tests` engine to a Qwen model **three ways**: a native
  **function-calling tool**, a **Qwen-Agent custom skill** (`@register_tool`), and an **MCP server**
  — the *producer*. Our own **Qwen-Agent MCP client** is the *consumer* that closes the loop (both
  ends ours), while any external MCP host can consume the same server. Runnable, not asserted; the
  full API-to-rubric map is in [qwen-usage.md](qwen-usage.md).

## Deployment topology (Alibaba Cloud SAS)

```mermaid
---
title: "Deployment — Alibaba Cloud SAS (single docker compose file)"
---
flowchart LR
    internet["Internet / judges"]:::person
    qwen["Qwen Cloud"]:::external
    oss["Alibaba OSS<br/><i>private bucket · us-west-1</i><br/>published media, content-addressed<br/>(media/&lt;sha1&gt;.mp4/.png/.wav)"]:::external
    subgraph sas["Alibaba Cloud SAS instance · US (Silicon Valley, us-west-1) · Python 3.12"]
        subgraph compose["docker compose (one multi-stage Dockerfile)"]
            web["web<br/><i>nginx:alpine</i><br/>serves web/dist, proxies /api → :80 (public)"]:::container
            app["app<br/><i>python:3.12-slim + ffmpeg</i><br/>uvicorn --factory → :8099 (internal)<br/>JUDGE_MODE=1 (fresh-clip cap; cached replays free)"]:::container
            db["db<br/><i>postgres:18-alpine</i><br/>catalog of published runs<br/>(flag-gated, no public port)"]:::container
            vol["volume ./data:/data<br/><i>cache + state persist across restarts</i>"]:::external
            pgvol["volume pgdata<br/><i>catalog rows persist across restarts</i>"]:::external
        end
    end
    internet -->|":80"| web
    web -->|"/api proxy"| app
    app --> vol
    app -->|"OpenAI-compat + native REST"| qwen
    app -->|"psycopg pool<br/>(CATALOG_ENABLED)"| db
    db --> pgvol
    app -->|"uploads via internal endpoint<br/>(free same-region traffic)"| oss
    internet -.->|"302 from /api/media →<br/>presigned GET (inline, ~1h)"| oss

    classDef person fill:#f5f0ff,stroke:#8250df,color:#1c1c22
    classDef container fill:#f6f8fa,stroke:#8b98a9,color:#24292f
    classDef external fill:#eceff3,stroke:#6e7781,color:#24292f
```

A push to `main` triggers the deploy workflow (GitHub Actions → SSH → rebuild + health-gate;
setup and failure signatures in [deploy.md](deploy.md)). Proof-of-deployment has two limbs: the
sanctioned Qwen Cloud base URL visible in code (`server/config.py`, `server/wan.py`,
`.env.example`, `docker-compose.yml`) — done — and the Alibaba Cloud Workbench screenshot of
running resources,
captured on the box at deploy time per the runbook's eligibility section. Backend compute runs
on the SAS box, not just API calls from elsewhere.

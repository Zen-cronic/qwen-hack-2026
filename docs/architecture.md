# Dailies architecture

> A rendered version of this is a REQUIRED submission deliverable: "how Qwen Cloud
> connects to your backend, database, and frontend."

Modeled with the [C4 model](https://c4model.com): **Level 1 (System Context)** — who
uses Dailies and which external systems it talks to — and **Level 2 (Container)** — the
deployable/runnable units inside Dailies and how a request flows through them. Levels 3–4
(component/code) are omitted deliberately: they would duplicate the source under
`server/`, which is the ground truth. Every box and edge below is traceable to a file you
can open.

**Diagram conventions.** Each diagram has a title (type + scope) and a legend. Colour is
sparse and purposeful: neutral fills for containers and external systems, a light accent
for actors, and **red reserved for the one path that matters most — reject-before-spend
(a DSL compile error) and the Tier-A hard-fail that triggers auto-repair.**

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
        spa["Web SPA<br/><i>React + Vite + TS, served by nginx</i><br/>Authoring form + conformance dashboard;<br/>polls GET /api/projects/:id every 2.5s"]:::container
        api["Backend API<br/><i>FastAPI on uvicorn :8099</i><br/>REST endpoints; spawns the pipeline thread;<br/>the poll payload IS the conformance report"]:::container

        subgraph pipe["Pipeline — background-thread state machine"]
            direction TB
            script["scripting<br/><i>qwen-plus</i>"]:::stage
            compile["DSL compiler<br/><i>specs.py / compiler.py</i>"]:::stage
            reject["reject before spend<br/>(DSL compile error)"]:::reject
            tier0["Tier-0 still<br/><i>wan2.1-t2i-plus</i>"]:::stage
            gate["human review gate<br/><i>threading.Event</i>"]:::stage
            draft["draft<br/><i>wan2.1-t2v-turbo</i>"]:::stage
            tierA["Tier-A CV<br/><i>OpenCV, ZERO tokens</i>"]:::stage
            tierB["Tier-B VLM (advisory)<br/><i>qwen-vl-plus</i>"]:::stage
            hardfail["blocking Tier-A FAIL"]:::reject
            repair["bounded auto-repair<br/><i>qwen-plus</i>"]:::stage
            promote["promote (frame-anchored)<br/><i>wan2.2-i2v-flash</i>"]:::stage
            narrate["narration<br/><i>qwen3-tts-flash</i>"]:::stage
            assemble["assembly + mux<br/><i>ffmpeg</i>"]:::stage

            script --> compile
            compile -->|"invalid sentence"| reject
            compile -->|"valid"| tier0
            tier0 --> gate
            gate -->|"operator approves"| draft
            draft --> tierA
            draft -.->|"advisory, parallel"| tierB
            tierA -->|"blocking FAIL"| hardfail
            hardfail -->|"retake, bounded"| repair
            repair --> draft
            tierA -->|"pass"| promote
            promote --> narrate
            narrate --> assemble
        end

        subgraph patchsub["Targeted repair — post-run, one shot, no pipeline re-entry"]
            direction TB
            locate["locate failure<br/><i>tier_a.py, re-measured</i><br/>fail_window_s"]:::stage
            anchor["cut anchor frame<br/><i>patch.py, last good frame</i>"]:::stage
            regen["re-render from anchor<br/><i>wan2.2-i2v-flash / kf2v</i>"]:::stage
            reverify["Tier-A re-verify"]:::stage
            keep["patch rejected —<br/>original clip stays"]:::reject

            locate --> anchor
            anchor --> regen
            regen --> reverify
            reverify -->|"blocking FAIL"| keep
        end

        ledger["Metrics ledger<br/><i>metrics.py + report.py</i><br/>Append-only JSONL; derives the<br/>cost-quality frontier + report metrics"]:::container
        store["Store + snapshots<br/><i>store.py, in-memory + JSON</i><br/>State under RLock; atomic state.json;<br/>content-addressed media cache"]:::container
        subgraph reuse["Reuse surface — one run_shot_tests engine, exposed three ways"]
            direction TB
            fc["Skill 1 · function-calling tool<br/><i>qwen_tools.py</i><br/>RUN_SHOT_TESTS_TOOL (OpenAI-compat tools=)"]:::container
            skill["Skill 2 · Qwen-Agent custom skill<br/><i>qwen_tools.py</i><br/>@register_tool BaseTool"]:::container
            mcpsrv["Skill 3 · MCP server (producer)<br/><i>FastMCP stdio, mcp_server.py</i><br/>run_shot_tests (free) + patch_clip"]:::container
            mcpcli["MCP client (consumer)<br/><i>Qwen-Agent, mcp_agent.py</i><br/>mcpServers block — closes the loop"]:::container
        end
    end

    qwen["Qwen Cloud<br/><i>External System</i><br/>qwen-plus · qwen-vl-plus · qwen3-tts-flash ·<br/>wan2.1-t2v-turbo / wan2.2-i2v-flash / wan2.1-t2i-plus"]:::external
    mcphost["MCP client host<br/><i>External System</i><br/>A Qwen agent / Claude"]:::external
    disk["Storage volume<br/><i>local /data, bind-mounted</i><br/>state.json · ledger.jsonl · cache/sha1.mp4 or .png"]:::external

    operator --> spa
    spa -->|"POST /api/projects, review, verdict;<br/>POST shots/:i/patch; GET poll 2.5s"| api
    api -->|"patch one shot"| locate
    reverify -->|"pass — becomes the shot final"| assemble
    regen -->|"i2v/kf2v, separate quota pool"| qwen
    api -->|"spawns thread"| script
    api -->|"reads state + ledger to build report metrics"| store
    api --> ledger

    script -->|"chat"| qwen
    tier0 -->|"t2i"| qwen
    draft -->|"t2v draft"| qwen
    tierB -->|"VLM verdict"| qwen
    repair -->|"repair prompt"| qwen
    promote -->|"t2v final"| qwen
    narrate -->|"text-to-speech"| qwen

    pipe -->|"records every call"| ledger
    pipe -->|"mutates state, atomic snapshot"| store
    store --> disk
    ledger --> disk

    fc -->|"reuses"| tierA
    skill -->|"reuses"| tierA
    mcpsrv -->|"reuses"| tierA
    fc -->|"function-calling loop"| qwen
    skill -->|"Qwen-Agent Assistant"| qwen
    mcpcli -->|"mcpServers stdio — both ends ours"| mcpsrv
    mcphost -->|"ListTools / CallTool (stdio)"| mcpsrv

    subgraph legend2["Legend / key"]
        direction LR
        k1["Person"]:::person
        k2["Container (in Dailies)"]:::container
        k3["Pipeline stage"]:::stage
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
- **Metrics ledger** (`server/metrics.py`, `server/report.py`) records every Qwen/Wan call and
  derives the frontier / heatmap / repair-convergence numbers the dashboard charts.
- **Store + snapshots** (`server/store.py`) is the "database": in-memory state mutated under an
  RLock, written as an **atomic `state.json` snapshot** after each change, plus a
  **content-addressed media cache** so identical (model, prompt, seed) requests replay for free.
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
    subgraph sas["Alibaba Cloud SAS instance · Canada · Python 3.12"]
        subgraph compose["docker compose (one multi-stage Dockerfile)"]
            web["web<br/><i>nginx:alpine</i><br/>serves web/dist, proxies /api → :80 (public)"]:::container
            app["app<br/><i>python:3.12-slim + ffmpeg</i><br/>uvicorn --factory → :8099 (internal)<br/>JUDGE_MODE=1 (fresh-clip cap; cached replays free)"]:::container
            vol["volume ./data:/data<br/><i>cache + state persist across restarts</i>"]:::external
        end
    end
    internet -->|":80"| web
    web -->|"/api proxy"| app
    app --> vol
    app -->|"OpenAI-compat + native REST"| qwen

    classDef person fill:#f5f0ff,stroke:#8250df,color:#1c1c22
    classDef container fill:#f6f8fa,stroke:#8b98a9,color:#24292f
    classDef external fill:#eceff3,stroke:#6e7781,color:#24292f
```

A push to `main` triggers the deploy workflow (GitHub Actions → SSH → rebuild + health-gate;
setup and failure signatures in [deploy.md](deploy.md)). Proof-of-deployment has two limbs: the
sanctioned Qwen Cloud base URL visible in code (`.env.example`, `server/wan.py`,
`server/app.py`) — done — and the Alibaba Cloud Workbench screenshot of running resources,
captured on the box at deploy time per the runbook's eligibility section. Backend compute runs
on the SAS box, not just API calls from elsewhere.

## About the project

```markdown
## Inspiration

Every team shipping AI video has quietly appointed a human test suite: one person who watches
every clip and checks it for length, brightness, flicker, brand palette, character continuity,
and whether the brief was followed at all. That person is the bottleneck for everyone upstream
who *owns* "correct" but cannot check it themselves.

The failure mode is specific and expensive: AI video fails **in motion**, after you have already
paid for it. A gorgeous keyframe becomes a clip that pans the wrong way, or does not pan at all.
The whole industry is optimizing generation. Nobody is testing the product.

So we built the part nobody built: the tests.

## What it does

You describe an episode in plain language. A Qwen agent turns it into a pipeline — the shots,
the rules, and a stop for your approval — by function-calling a real tool, so the topology is
always well-formed. Each rule you write is compiled into a **closed assertion grammar of ten
sentence types across three tiers**. A rule the grammar cannot express is rejected *before a
token is spent*; that rejection is the compile error, and it is the literal "CI" in "CI for
generated video".

Then every generated take is measured:

- **Tier 0** renders one cheap still per shot and asks Qwen-VL whether the prompt can even
  produce its own subject — roughly 1/25th of a video second's cost, before any video spend.
- **Tier A** is deterministic OpenCV: duration, brightness, flicker, scene cuts, camera motion
  by optical flow, palette ΔE. **Zero tokens**, so it runs on every take, and it reports *where*
  a check failed, not just that it did — a failure carries a time window and writes the frame
  it indicted.
- **Tier B** is Qwen-VL judgment on strided frames — identity continuity, briefed action, title
  card. Advisory only: a model's opinion never blocks what a measurement approved.

A take that fails a blocking check goes back for a bounded repair: Qwen-plus rewrites the prompt
from the failing assertions, and a frame-anchored Wan i2v model re-renders from the last good
frame, so the retake is a *continuation* of the approved take rather than a fresh roll. A patch
has to earn its slot — if it still fails, the original stays.

There is exactly one human checkpoint, and it sits before any video is paid for.

The verification engine is then re-exposed three ways — a native Qwen function-calling tool, a
Qwen-Agent custom skill, and an **MCP server** — so any pipeline or agent can gate video the way
it already gates code. We ship the MCP client too, so both ends of that loop are ours.

## How we built it

A FastAPI backend runs the pipeline as a background state machine; a React SPA polls one endpoint
whose payload *is* the conformance report. The whole thing runs on Alibaba Cloud — a Simple
Application Server instance in US (Silicon Valley) running nginx, the API, and a Postgres sidecar
under one `docker compose`, with published media in a private OSS bucket and a GitHub Actions
workflow that redeploys on every merge to main.

Every model call lands on Qwen Cloud, in two API shapes because the models need different ones.
Chat and vision go through the OpenAI-compatible endpoint, so one client carries function calling
and structured output. Generation is long-running, so video, image and speech go through the
native DashScope async task API — submit, poll, fetch — which the OpenAI-compatible shape has no
vocabulary for.

Three design decisions did the heavy lifting:

**The agent emits parameters, not topology.** The tool takes a premise, a pack, a shot count and
custom checks; the *server* expands those into the canonical graph. The model cannot emit a
malformed pipeline because it never emits a pipeline. The "an agent authored this run" story
stays completely true, and the failure mode designs itself out.

**The deterministic tier is the spine.** Tier A calls nothing and costs nothing, which is the
only reason it can run on every take. Model judgment sits on top as advice, never as foundation.

**Everything is content-addressed.** Identical (model, prompt, seed) requests replay from cache,
so re-certifying real 1080p video costs zero video quota — measured, not asserted. That is what
makes the whole thing demonstrable without burning a quota.

## Challenges we ran into

**Our green test suite was hiding four real bugs, and they shared one shape.** The first
end-to-end run against real models found that the premium promote model rejects the draft's frame
size — meaning *every premium promotion we had ever made had silently failed* — that the budget
governor was asking the cache about the wrong key and calling every cached final "fresh", that
the ledger wrote an empty note for both a no-op and a hard failure, and that state snapshots were
written and never read back, so every redeploy discarded every run. Each one was a fallback that
made failure look like success. The audit trail was not auditing. We fixed all four, and each fix
has a regression test verified by reverting the fix and confirming the test fails.

**We had shipped a gate we were billing for and never wired.** A Tier-0 verdict was being
generated, paid for, and stored — and nothing ever read it. It fell between two tiers and was
evaluated by neither. It is documented rather than quietly patched, because that is the exact
failure the project exists to catch.

**An anchor frame carries composition, but not motion.** Frame-anchored promotion made every
shot look consistent — and quietly killed camera movement, because i2v holds the anchor's
composition. Measured at |v|=0.112 against a 0.4 threshold, versus 4.871 for a fresh roll. So a
shot whose contract asserts camera motion now skips promotion and ships the approved take. That
is a measurement, not a preference.

**Staging a failure is not the same as having one.** Our planted kill-shot kept *passing*. The
prompt asked the camera to pan right and follow the dog — and a subject moving laterally hands
the model every reason to track, so the ask became self-fulfilling and the check had nothing to
catch. We refused to write a prompt designed to fail. We restored the *condition* instead: a
sincere pan request over a scene with no inherent lateral motion. The model returned a beautiful,
plausible, completely static shot at |v|=0.028. One bounded repair took it to 4.871 and it
certified. That failure is real, and we can show the measurement.

**The video API returns 429 on concurrent submits**, so generation has to stay sequential while
stills parallelize fine — the kind of thing you only learn by hitting it.

## Accomplishments that we're proud of

- The deterministic layer costs **zero tokens** and catches the failure the whole demo turns on.
  It is not a wrapper around a model's opinion.
- **Re-certifying real 1080p video costs zero video quota**, because the cache is content-
  addressed. Judges can re-run the pipeline as many times as they like.
- The verification engine is genuinely reusable: a function-calling tool, an agent skill, and an
  MCP server — plus our own MCP client, so the loop closes with both ends ours. Runnable, not
  asserted.
- Every measurement in our docs is reproducible from a script in the repo, including the ones
  that made us rewrite our own claims.

## What we learned

**A cache key is a contract.** Prompts are cache keys here, so "tidying" a prompt string orphans
a clip you already paid for. That invariant now lives in a comment above every pinned string.

**Green tests prove the code does what you told it to, not that you told it the right thing.**
All four of our worst bugs were invisible to a passing suite, because a fallback path turned
failure into a plausible success. The lesson generalizes past this project: if failure and
success produce identical state, you have no test — you have a coin flip you are not watching.

**Advisory has to mean advisory.** The temptation to let a model verdict block promotion is
constant, and every time we resisted it the system got more trustworthy. A pixel measurement and
a language model's opinion are different kinds of evidence and should not have the same authority.

**Write the thing that measures before the thing that generates.** We could not have found any of
the above without a ledger that priced every call and a check that reported *where* it failed.

## What's next for Dailies

- **Modalities the grammar cannot yet express**, published as roadmap rather than claimed as
  built: transcript/ASR checks, on-screen-text OCR, and time-windowed assertions like "a
  conspicuous title in the first three seconds" or "the brand named twice in the outro".
- **A diagnostic for silent omission.** Today a plain-language rule needing a missing modality is
  dropped rather than approximated — correct behaviour, but the author gets no message saying so.
- **Assertion packs as a distributable artifact**, so a brand's rules become a dependency your CI
  pins, versions, and regression-tests across generator upgrades.
- **The human-override corpus.** Every time a reviewer overrules a verdict at the approve gate,
  that is calibration data no generator vendor can collect — it only exists on the buyer's side
  of the gate.
```

## Other form fields

**URL to your code file showing proof of Alibaba Cloud Deployment:**

```
https://github.com/Zen-cronic/qwen-hack-2026/blob/main/server/wan.py
```

Names the DashScope host and drives its async task API — submit with `X-DashScope-Async`, poll
`/api/v1/tasks/{id}`, fetch the signed result. If a second link is allowed, add
`server/oss.py` (Alibaba OSS SDK) or `.github/workflows/deploy-prod.yml` (deploys onto the
Simple Application Server instance).

**Testing instructions:**

```markdown
No credentials required — the app is open and free to use.

Live: http://<host>/

Click "Run this pipeline" on the prefilled request, or type your own episode in plain
language and press Design. The run stops at a human review gate showing still evidence
before any video is generated; approve it to continue. Shot 1 fails its camera-motion
check on the first take and is automatically repaired — that failure is real and
measured, not scripted. The conformance board shows per-assertion verdicts with the
evidence frame each one indicted.

Everything is content-addressed, so re-running an identical spec replays from cache and
costs nothing. Re-run it as often as you like.

To run it locally with no API key at all:

  git clone https://github.com/Zen-cronic/qwen-hack-2026 && cd qwen-hack-2026
  python3.12 -m venv .venv && source .venv/bin/activate
  pip install -e ".[dev]"
  npm --prefix web install && npm --prefix web run build
  DAILIES_DEMO=1 SPA_DIST=web/dist uvicorn server.app:create_production_app --factory --port 8099

Then open http://localhost:8099/. Demo mode runs the real pipeline, the real OpenCV
checks and real ffmpeg assembly over synthetic clips — zero video quota, no network.
Requires ffmpeg. `pytest -q` runs the full suite with no key and no network.
```
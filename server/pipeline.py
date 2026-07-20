"""The pipeline — a background-thread state machine over one ProjectState.

Every stage is INJECTED (see Deps), so this orchestration is testable with fakes
today and the real CV/VLM/repair stages (Subphases F–H) drop in unchanged. The
one human checkpoint is a threading.Event between tier0 and any video spend.

State flow (state.md):
  queued -> scripting -> tier0 -> awaiting_review [Event] -> drafting -> verifying
         -> repairing -> promoting -> assembling -> done | failed

Spend discipline: cache-hit clips are logged with video_seconds=0 (free); only
billed generations (seconds>0) count against the wallet. Promotion to the final
model is automatic up to final_cap; beyond it, a passing draft is certified as-is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from server.compiler import compile_shots, load_pack
from server.metrics import LedgerWriter, ResourceKind
from server.patch import anchor_second, extract_frame, localized_failure
from server.specs import (
    Assertion,
    AssertionResult,
    AssertionType,
    ShotSpec,
    Status,
    parse_assertions,
)
from server.tts import narration_for
from server.store import (
    ProjectState,
    ProjectStatus,
    ShotState,
    ShotStatus,
    Store,
    Take,
    TakeStatus,
)

# Stage callables (structural — any callable with the right shape works).
ScriptFn = Callable[[str, object, int], tuple[list[dict], object]]        # (premise, pack, max_shots) -> (raw_shots, usage)
CustomRuleFn = Callable[[list[str]], tuple[list[dict], object]]           # (rules) -> (raw_assertions, usage)
GenImageFn = Callable[[str], object]                                      # (prompt) -> WanResult-like
GenVideoFn = Callable[[str, str], object]                                 # (prompt, model) -> WanResult-like
Tier0Fn = Callable[[ShotSpec, str], list[AssertionResult]]               # (spec, still_path) -> results
TierAFn = Callable[[str, ShotSpec, str], list[AssertionResult]]          # (video_path, spec, evidence_dir) -> results
TierBFn = Callable[[str, ShotSpec], list[AssertionResult]]               # (video_path, spec) -> results
RepairFn = Callable[[ShotSpec, list[AssertionResult]], tuple[str, object]]  # (spec, failures) -> (new_prompt, usage)
PatchVideoFn = Callable[[str, str, str], object]                          # (prompt, model, frame_path) -> WanResult-like
NarrateFn = Callable[[str], object]                                       # (text) -> TTSResult-like
AssembleFn = Callable[[list[str], str], str]                             # (clip_paths, out_path) -> episode_path


@dataclass
class Deps:
    script_fn: ScriptFn
    gen_image_fn: GenImageFn
    gen_video_fn: GenVideoFn
    tier0_fn: Tier0Fn
    tier_a_fn: TierAFn
    tier_b_fn: TierBFn
    repair_fn: RepairFn
    assemble_fn: AssembleFn
    ledger: LedgerWriter
    custom_rule_fn: CustomRuleFn | None = None  # optional: compile user-authored checks
    patch_video_fn: PatchVideoFn | None = None  # optional: frame-anchored targeted repair
    narrate_fn: NarrateFn | None = None         # optional: narration track for the episode


@dataclass
class Config:
    chat_model: str = "qwen-plus"
    vl_model: str = "qwen-vl-plus"
    t2i_model: str = "wan2.1-t2i-plus"
    draft_model: str = "wan2.1-t2v-turbo"
    final_model: str = "wan2.2-t2v-plus"
    # Frame-anchored repair. i2v-flash takes a single anchor, which is what a motion
    # repair wants — kf2v interpolates between two keyframes, so pinning the last one
    # would re-impose the very end state the patch is trying to fix.
    patch_model: str = "wan2.2-i2v-flash"
    tts_model: str = "qwen3-tts-flash"
    max_retakes: int = 1
    final_cap: int = 4
    packs_dir: str | None = None
    data_dir: str = "data/projects"


def _spend_note(res) -> str:
    """What the ledger records about one generation call.

    A FAILED call must say why. Every wan2.2-t2v-plus promote was rejected with
    InvalidParameter (wrong frame size) for the project's entire life and nobody noticed,
    because a failed call and a no-op call both wrote an empty note while _promote quietly
    fell back to the passing draft. The ledger is the audit trail; make it audit.
    """
    if getattr(res, "from_cache", False):
        return "cache"
    if not getattr(res, "ok", True):
        code = getattr(res, "code", None) or getattr(res, "status", "FAILED")
        return f"FAILED {code}: {getattr(res, 'message', '') or ''}".strip()[:180]
    return ""


def _pop_usage(stage_fn) -> tuple[int, int]:
    """A stage may expose token usage from its last call via pop_last_usage();
    plain-function stages (e.g. Tier-A) simply report nothing."""
    pop = getattr(stage_fn, "pop_last_usage", None)
    if callable(pop):
        try:
            return pop()
        except Exception:  # noqa: BLE001
            return (0, 0)
    return (0, 0)


def build_style_descriptor(premise: str, specs: list[ShotSpec]) -> str:
    """A shared look/identity clause woven into every shot's generation prompt.

    Deterministic and free — no extra model call. It fixes the two things that drift
    across independently generated shots: the visual grade, and the identity of any
    recurring subject. Frame-anchored i2v (repair/promotion) carries continuity WITHIN a
    shot; this descriptor carries the look ACROSS shots so the episode reads as one piece.
    """
    seen: list[str] = []
    for s in specs:
        subj = (getattr(s, "subject", None) or "").strip()
        if subj and subj.lower() not in [x.lower() for x in seen]:
            seen.append(subj)
    look = ("consistent cinematic look throughout: one unified color grade, matched "
            "lighting and lens, continuous art direction")
    if seen:
        return f"{look}; hold a consistent appearance and wardrobe for {'; '.join(seen)}"
    return look


# Which second of the approved draft anchors the promoted final. Early, so the certified
# clip BEGINS like the take the human approved and reads as a continuation of it.
PROMOTE_ANCHOR_S = 0.1


def asserts_camera_motion(spec: ShotSpec) -> bool:
    """Whether this shot's contract pins camera motion.

    An anchor frame carries composition but NOT motion, so an i2v promotion has to
    re-invent the move — and on real Wan output it INVERTED it: an approved rightward pan
    (|v|=0.745, 'right') promoted to |v|=6.15 'left' and failed Tier-A. When motion is
    contractual the approved take is already the most consistent final, so it ships as-is
    rather than spending a clip on a mechanism that cannot preserve the property under test.
    """
    return any(a.type is AssertionType.CAMERA_MOTION for a in spec.assertions)


class Pipeline:
    def __init__(self, store: Store, project_id: str, deps: Deps, cfg: Config | None = None):
        self.store = store
        self.pid = project_id
        self.deps = deps
        self.cfg = cfg or Config()

    # Entry point — target for threading.Thread(target=Pipeline(...).run).
    def run(self) -> None:
        try:
            self._scripting()
            self._tier0()
            self._await_review()
            self._draft_all()
            self._assemble()
        except Exception as exc:  # noqa: BLE001 — a background thread must not die silently
            self._set(lambda p: setattr_many(p, status=ProjectStatus.FAILED, error=str(exc)))

    # helpers

    def _set(self, mutate: Callable[[ProjectState], None]) -> None:
        self.store.update(self.pid, mutate)

    def _status(self, status: ProjectStatus) -> None:
        self._set(lambda p: setattr(p, "status", status))

    def _shot_status(self, idx: int, status: ShotStatus) -> None:
        self._set(lambda p: setattr(p.shots[idx], "status", status))

    def _spend(self, *, kind: ResourceKind, model: str, stage: str, shot_index: int | None = None,
               tokens_in: int = 0, tokens_out: int = 0, images: int = 0, video_seconds: int = 0,
               cached_seconds: int = 0, latency_ms: int = 0, note: str = "") -> None:
        entry = self.deps.ledger.record(
            stage=stage, kind=kind, model=model, tokens_in=tokens_in, tokens_out=tokens_out,
            images=images, video_seconds=video_seconds, cached_seconds=cached_seconds,
            latency_ms=latency_ms, shot_index=shot_index, note=note,
        )

        def mut(p: ProjectState) -> None:
            p.ledger.append(entry)
            p.recompute_wallet()

        self._set(mut)

    def _evidence_dir(self, idx: int, take_no: int) -> str:
        d = Path(self.cfg.data_dir) / self.pid / "evidence" / f"shot{idx}" / f"take{take_no}"
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    def _compose_prompt(self, base: str) -> str:
        """Weave the project's shared visual bible into a generation prompt. Applied at
        the gen call ONLY — takes store the raw creative prompt, so this never
        double-composes, and repair/promotion re-compose from that raw prompt."""
        desc = self.store.get(self.pid).style_descriptor
        return f"{base} — {desc}" if desc else base

    def _anchor_for_retake(self, video_path: str, results: list[AssertionResult],
                           idx: int, take_no: int) -> str | None:
        """The last good frame before the located failure — the i2v anchor for a retake.

        Reuses Tier-A's failure localization (server.patch). Returns None when the failure
        can't be placed in time, so the caller falls back to a fresh t2v roll rather than
        anchoring on a frame that isn't meaningfully 'before' the defect."""
        failure = localized_failure(results)
        if failure is None:
            return None
        at = anchor_second(failure)
        # Anchor to PRESERVE, re-roll to CHANGE. If the defect starts at t=0 there is no
        # good frame before it, and i2v works by holding the anchor's composition — so
        # anchoring would pin the very thing the retake has to fix. Measured on real Wan
        # output: a clip static throughout (fail_window [0.0, 5.33], |v|=0.005) retaken via
        # i2v from frame 0 still measured |v|=0.112 against a 0.4 threshold, while a fresh
        # t2v roll on the motion-forward repair prompt reaches |v|~1.47.
        if at <= 0.0:
            return None
        out = Path(self._evidence_dir(idx, take_no)) / "retake_anchor.png"
        return extract_frame(video_path, at, out)

    # stages

    def _scripting(self) -> None:
        self._status(ProjectStatus.SCRIPTING)
        p = self.store.get(self.pid)
        pack = load_pack(p.pack, self.cfg.packs_dir)
        # User-authored checks compile ONCE (before the script loop) and apply to every
        # shot. A malformed rule raises here — rejected before any video spend.
        extra_defaults = self._compile_custom_checks(p)

        last_err: Exception | None = None
        tin = tout = 0
        specs: list[ShotSpec] | None = None
        for _ in range(2):  # one re-prompt on a compile failure
            raw, usage = self.deps.script_fn(p.premise, pack, p.max_shots)
            tin += getattr(usage, "prompt_tokens", 0)
            tout += getattr(usage, "completion_tokens", 0)
            try:
                specs = compile_shots(raw, pack, extra_defaults=extra_defaults)
                break
            except ValueError as exc:
                last_err = exc
        self._spend(kind=ResourceKind.CHAT, model=self.cfg.chat_model, stage="scripting",
                    tokens_in=tin, tokens_out=tout)
        if specs is None:
            raise ValueError(f"script agent output failed to compile after retry: {last_err}")

        def set_shots(p: ProjectState) -> None:
            p.shots = [ShotState(spec=s) for s in specs]
            # The shared look is fixed here, once, from the compiled shots — every
            # downstream generation composes it in so the episode stays coherent.
            p.style_descriptor = build_style_descriptor(p.premise, specs)

        self._set(set_shots)

    def _compile_custom_checks(self, p: ProjectState) -> list[Assertion]:
        """Compile the project's plain-language custom checks into validated assertions.

        No-op when there are none or no compiler is wired. The token cost is billed to
        the scripting stage; a rule the compiler emits but the closed vocabulary rejects
        fails HERE — extending the reject-before-spend guarantee to user input.
        """
        rules = [r.strip() for r in (p.custom_checks or []) if r.strip()]
        if not rules or self.deps.custom_rule_fn is None:
            return []
        raw, usage = self.deps.custom_rule_fn(rules)
        tin = getattr(usage, "prompt_tokens", 0) or 0
        tout = getattr(usage, "completion_tokens", 0) or 0
        if tin or tout:
            self._spend(kind=ResourceKind.CHAT, model=self.cfg.chat_model, stage="scripting",
                        tokens_in=tin, tokens_out=tout, note="custom checks")
        try:
            return parse_assertions(raw)
        except ValueError as exc:
            raise ValueError(f"custom check failed to compile: {exc}") from exc

    def _tier0(self) -> None:
        self._status(ProjectStatus.TIER0)
        for idx in range(len(self.store.get(self.pid).shots)):
            spec = self.store.get(self.pid).shots[idx].spec
            res = self.deps.gen_image_fn(self._compose_prompt(spec.prompt))
            self._spend(kind=ResourceKind.IMAGE, model=self.cfg.t2i_model, stage="tier0",
                        shot_index=idx, images=0 if getattr(res, "from_cache", False) else 1,
                        latency_ms=getattr(res, "latency_ms", 0),
                        note=_spend_note(res))
            results = self.deps.tier0_fn(spec, res.local_path) if res.ok else []
            t0_in, t0_out = _pop_usage(self.deps.tier0_fn)
            if t0_in or t0_out:
                self._spend(kind=ResourceKind.VLM, model=self.cfg.vl_model, stage="tier0",
                            shot_index=idx, tokens_in=t0_in, tokens_out=t0_out)

            def mut(p: ProjectState, idx=idx, res=res, results=results) -> None:
                st = p.shots[idx]
                st.still_path = res.local_path if res.ok else None
                st.tier0_results = results
                st.status = ShotStatus.TIER0

            self._set(mut)

    def _await_review(self) -> None:
        self._status(ProjectStatus.AWAITING_REVIEW)
        self.store.review_event(self.pid).wait()  # the ONE human gate — blocks pre-video-spend

    def _draft_all(self) -> None:
        self._status(ProjectStatus.DRAFTING)
        for idx in range(len(self.store.get(self.pid).shots)):
            self._process_shot(idx)
        # assembling status set in _assemble

    def _process_shot(self, idx: int) -> None:
        spec = self.store.get(self.pid).shots[idx].spec
        prompt = spec.prompt
        anchor: str | None = None   # last good frame of the prior take; drives an i2v retake
        passed = False
        for take_no in range(self.cfg.max_retakes + 1):
            self._shot_status(idx, ShotStatus.DRAFTING)
            # A retake continues from the frame that still passed (i2v) rather than
            # re-rolling the whole shot from noise — so the fix inherits the composition
            # the draft already got right and stays visually continuous with it. The first
            # take, or a runtime with no frame-anchored model, uses a fresh t2v draft.
            if anchor and self.deps.patch_video_fn is not None:
                res = self.deps.patch_video_fn(self._compose_prompt(prompt), self.cfg.patch_model, anchor)
                tier, model, kind = "repair", self.cfg.patch_model, ResourceKind.VIDEO_PATCH
            else:
                res = self.deps.gen_video_fn(self._compose_prompt(prompt), self.cfg.draft_model)
                tier, model, kind = "draft", self.cfg.draft_model, ResourceKind.VIDEO_DRAFT
            billed = 0 if getattr(res, "from_cache", False) else getattr(res, "seconds", 0)
            self._spend(kind=kind, model=model, stage="drafting",
                        shot_index=idx, video_seconds=billed,
                        cached_seconds=getattr(res, "cached_seconds", 0),
                        latency_ms=getattr(res, "latency_ms", 0), note=_spend_note(res))
            take = Take(take_no=take_no, tier=tier, model=model, prompt=prompt,
                        status=TakeStatus.DONE if res.ok else TakeStatus.FAILED,
                        task_id=getattr(res, "task_id", None), video_path=res.local_path if res.ok else None)
            if not res.ok:
                self._append_take(idx, take)
                break

            self._status(ProjectStatus.VERIFYING)
            results = list(self.deps.tier_a_fn(res.local_path, spec, self._evidence_dir(idx, take_no)))
            results += list(self.deps.tier_b_fn(res.local_path, spec))
            tb_in, tb_out = _pop_usage(self.deps.tier_b_fn)
            if tb_in or tb_out:
                self._spend(kind=ResourceKind.VLM, model=self.cfg.vl_model, stage="verifying",
                            shot_index=idx, tokens_in=tb_in, tokens_out=tb_out)
            take.results = results
            take.passed = not [r for r in results if not r.advisory and r.status is Status.FAIL]
            self._append_take(idx, take)

            if take.passed:
                passed = True
                break
            if take_no < self.cfg.max_retakes:
                self._status(ProjectStatus.REPAIRING)
                self._shot_status(idx, ShotStatus.REPAIRING)
                failures = [r for r in results if not r.advisory and r.status is Status.FAIL]
                new_prompt, usage = self.deps.repair_fn(spec, failures)
                self._spend(kind=ResourceKind.CHAT, model=self.cfg.chat_model, stage="repairing",
                            shot_index=idx, tokens_in=getattr(usage, "prompt_tokens", 0),
                            tokens_out=getattr(usage, "completion_tokens", 0))
                prompt = new_prompt
                anchor = self._anchor_for_retake(res.local_path, results, idx, take_no)

        if passed:
            self._promote(idx)
        else:
            self._shot_status(idx, ShotStatus.FAILED)

    def _promote(self, idx: int) -> None:
        self._status(ProjectStatus.PROMOTING)
        p = self.store.get(self.pid)
        certified_so_far = sum(1 for s in p.shots if s.certified)
        last = p.shots[idx].latest_take
        assert last is not None and last.video_path is not None

        if certified_so_far >= self.cfg.final_cap:
            # Out of promotion budget — certify the passing draft as the final.
            self._set(lambda p: _certify(p, idx, p.shots[idx].latest_take.video_path))
            return

        # Anchor the final on the take that just passed, so the certified clip is a
        # continuation of what was approved rather than a fresh roll that drifts off it. A
        # seed can't do this — it doesn't transfer across models; the frame does. Fall back
        # to a t2v final when no frame-anchored model is wired (e.g. the fixtures runtime).
        spec = p.shots[idx].spec
        # Motion is contractual here and an anchor frame cannot carry it (see
        # asserts_camera_motion): ship the take that actually passed instead of spending a
        # generation that can only re-invent the move — which is also the most consistent
        # final we can give, since it IS the approved take.
        if self.deps.patch_video_fn is not None and asserts_camera_motion(spec):
            self._set(lambda p: _certify(p, idx, p.shots[idx].latest_take.video_path))
            return

        anchor = None
        if self.deps.patch_video_fn is not None:
            out = Path(self._evidence_dir(idx, 99)) / "final_anchor.png"
            anchor = extract_frame(last.video_path, PROMOTE_ANCHOR_S, out)
        if anchor is not None:
            res = self.deps.patch_video_fn(self._compose_prompt(last.prompt), self.cfg.patch_model, anchor)
            final_model = self.cfg.patch_model
        else:
            res = self.deps.gen_video_fn(self._compose_prompt(last.prompt), self.cfg.final_model)
            final_model = self.cfg.final_model
        billed = 0 if getattr(res, "from_cache", False) else getattr(res, "seconds", 0)
        # Recorded as the FINAL however it was rendered — this IS the certified clip, and
        # the role is what the frontier and wallet reason about, not the endpoint used.
        self._spend(kind=ResourceKind.VIDEO_FINAL, model=final_model, stage="promoting",
                    shot_index=idx, video_seconds=billed,
                    cached_seconds=getattr(res, "cached_seconds", 0),
                    latency_ms=getattr(res, "latency_ms", 0), note=_spend_note(res))
        if not res.ok:
            # Promotion failed — keep the draft as the certified final.
            self._set(lambda p: _certify(p, idx, p.shots[idx].latest_take.video_path))
            return

        # Re-verify Tier-A on the final (deterministic, no tokens).
        results = list(self.deps.tier_a_fn(res.local_path, spec, self._evidence_dir(idx, 99)))
        final_take = Take(take_no=len(p.shots[idx].takes), tier="final", model=final_model,
                          prompt=last.prompt, status=TakeStatus.DONE, task_id=getattr(res, "task_id", None),
                          video_path=res.local_path, results=results,
                          passed=not [r for r in results if not r.advisory and r.status is Status.FAIL])
        self._append_take(idx, final_take)
        if final_take.passed:
            self._set(lambda p: _certify(p, idx, res.local_path))
        else:
            # The final regressed on the deterministic tier even though the draft cleared
            # it. Certify the draft rather than ship an unverified final — the same fallback
            # the budget and promotion-failure paths above already take.
            self._set(lambda p: _certify(p, idx, last.video_path))

    def _assemble(self) -> None:
        self._status(ProjectStatus.ASSEMBLING)
        p = self.store.get(self.pid)
        shipped = [s for s in p.shots if s.certified and s.final_path]
        paths = [s.final_path for s in shipped]
        if not paths:
            self._set(lambda p: setattr_many(p, status=ProjectStatus.FAILED,
                                             error="no certified shots to assemble"))
            return
        out = str(Path(self.cfg.data_dir) / self.pid / "episode.mp4")
        audio = self._narrate(shipped)
        episode = (self.deps.assemble_fn(paths, out, audio_paths=audio) if audio
                   else self.deps.assemble_fn(paths, out))
        self._set(lambda p: setattr_many(p, status=ProjectStatus.DONE, episode_path=episode))

    def _narrate(self, shipped: list[ShotState]) -> list[str | None] | None:
        """A narration track per shipped shot, or None if this runtime has no voice.

        Never fatal: a shot whose line fails to synthesize gets silence, and the episode
        still ships. Sound is a finish on the deliverable, not part of the contract —
        failing a certified run over a voice call would invert what this system is for.
        """
        if self.deps.narrate_fn is None:
            return None
        out: list[str | None] = []
        for s in shipped:
            text = narration_for(s.spec)
            if not text:
                out.append(None)
                continue
            res = self.deps.narrate_fn(text)
            ok = bool(getattr(res, "ok", False))
            self._spend(kind=ResourceKind.AUDIO, model=self.cfg.tts_model, stage="assembling",
                        shot_index=s.spec.index, latency_ms=getattr(res, "latency_ms", 0),
                        note=("cache" if getattr(res, "from_cache", False)
                              else f"{getattr(res, 'chars', 0)} chars" if ok
                              else f"FAILED {getattr(res, 'message', '')}"[:180]))
            out.append(getattr(res, "local_path", None) if ok else None)
        return out if any(out) else None

    def _append_take(self, idx: int, take: Take) -> None:
        self._set(lambda p: p.shots[idx].takes.append(take))


def _certify(p: ProjectState, idx: int, final_path: str | None) -> None:
    st = p.shots[idx]
    st.certified = True
    st.final_path = final_path
    st.status = ShotStatus.CERTIFIED


def setattr_many(obj, **kw) -> None:
    for k, v in kw.items():
        setattr(obj, k, v)

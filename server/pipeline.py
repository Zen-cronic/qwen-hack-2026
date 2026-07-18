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
from server.specs import Assertion, AssertionResult, ShotSpec, Status, parse_assertions
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


@dataclass
class Config:
    chat_model: str = "qwen-plus"
    vl_model: str = "qwen-vl-plus"
    t2i_model: str = "wan2.1-t2i-plus"
    draft_model: str = "wan2.1-t2v-turbo"
    final_model: str = "wan2.2-t2v-plus"
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
        self._set(lambda p: setattr(p, "shots", [ShotState(spec=s) for s in specs]))

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
            res = self.deps.gen_image_fn(spec.prompt)
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
        passed = False
        for take_no in range(self.cfg.max_retakes + 1):
            self._shot_status(idx, ShotStatus.DRAFTING)
            res = self.deps.gen_video_fn(prompt, self.cfg.draft_model)
            billed = 0 if getattr(res, "from_cache", False) else getattr(res, "seconds", 0)
            self._spend(kind=ResourceKind.VIDEO_DRAFT, model=self.cfg.draft_model, stage="drafting",
                        shot_index=idx, video_seconds=billed,
                        cached_seconds=getattr(res, "cached_seconds", 0),
                        latency_ms=getattr(res, "latency_ms", 0), note=_spend_note(res))
            take = Take(take_no=take_no, tier="draft", model=self.cfg.draft_model, prompt=prompt,
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

        res = self.deps.gen_video_fn(last.prompt, self.cfg.final_model)
        billed = 0 if getattr(res, "from_cache", False) else getattr(res, "seconds", 0)
        self._spend(kind=ResourceKind.VIDEO_FINAL, model=self.cfg.final_model, stage="promoting",
                    shot_index=idx, video_seconds=billed,
                    cached_seconds=getattr(res, "cached_seconds", 0),
                    latency_ms=getattr(res, "latency_ms", 0), note=_spend_note(res))
        if not res.ok:
            # Promotion failed — keep the draft as the certified final.
            self._set(lambda p: _certify(p, idx, p.shots[idx].latest_take.video_path))
            return

        # Re-verify Tier-A on the final (deterministic, no tokens).
        results = list(self.deps.tier_a_fn(res.local_path, p.shots[idx].spec, self._evidence_dir(idx, 99)))
        final_take = Take(take_no=len(p.shots[idx].takes), tier="final", model=self.cfg.final_model,
                          prompt=last.prompt, status=TakeStatus.DONE, task_id=getattr(res, "task_id", None),
                          video_path=res.local_path, results=results,
                          passed=not [r for r in results if not r.advisory and r.status is Status.FAIL])
        self._append_take(idx, final_take)
        if final_take.passed:
            self._set(lambda p: _certify(p, idx, res.local_path))
        else:
            # The premium final regressed on the deterministic tier even though the draft
            # cleared it. Certify the draft rather than ship an unverified final — the same
            # fallback the budget and promotion-failure paths above already take. Certifying
            # res.local_path here would put a Tier-A FAIL into the episode.
            self._set(lambda p: _certify(p, idx, last.video_path))

    def _assemble(self) -> None:
        self._status(ProjectStatus.ASSEMBLING)
        p = self.store.get(self.pid)
        paths = [s.final_path for s in p.shots if s.certified and s.final_path]
        if not paths:
            self._set(lambda p: setattr_many(p, status=ProjectStatus.FAILED,
                                             error="no certified shots to assemble"))
            return
        out = str(Path(self.cfg.data_dir) / self.pid / "episode.mp4")
        episode = self.deps.assemble_fn(paths, out)
        self._set(lambda p: setattr_many(p, status=ProjectStatus.DONE, episode_path=episode))

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

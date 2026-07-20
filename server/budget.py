"""Judge-mode budget governor — caps FRESH (billable) generations per process.

Cached replays bypass the cap entirely; outside judge mode this is a pass-through.
"""

from __future__ import annotations

import threading

from server.config import settings
from server.wan import WanClient, WanResult, video_size_for


class BudgetGovernor:
    # Exhausting a cap is not a failure path: Pipeline._promote certifies the passing draft.
    def __init__(self, *, judge_mode: bool | None = None,
                 fresh_draft_cap: int = 2, fresh_final_cap: int = 2):
        self.judge_mode = settings.JUDGE_MODE if judge_mode is None else judge_mode
        self.fresh_draft_cap = fresh_draft_cap
        self.fresh_final_cap = fresh_final_cap
        self._fresh = {"draft": 0, "final": 0}
        self._lock = threading.Lock()

    def allow_fresh(self, tier: str) -> bool:
        if not self.judge_mode:
            return True
        cap = self.fresh_final_cap if tier == "final" else self.fresh_draft_cap
        with self._lock:
            return self._fresh[tier] < cap

    def record_fresh(self, tier: str) -> None:
        with self._lock:
            self._fresh[tier] = self._fresh.get(tier, 0) + 1

    def counters(self) -> dict:
        with self._lock:
            return {"judge_mode": self.judge_mode, "fresh_drafts": self._fresh["draft"],
                    "fresh_finals": self._fresh["final"], "fresh_draft_cap": self.fresh_draft_cap,
                    "fresh_final_cap": self.fresh_final_cap}


def governed_gen_video(wan: WanClient, governor: BudgetGovernor, *, final_model: str):
    """Wrap WanClient.generate_video with the governor, returning a GenVideoFn. Cached requests
    are always allowed; a capped fresh one is refused with a synthetic FAILED result."""

    def gen(prompt: str, model: str, negative_prompt: str | None = None) -> WanResult:
        tier = "final" if model == final_model else "draft"
        # Must ask the model for its size — it is part of the cache key, so a hardcoded one
        # looks up the wrong key and reports cached clips as fresh.
        cached = wan.is_cached("video", model, prompt, None, video_size_for(model), negative_prompt)
        if not cached and not governor.allow_fresh(tier):
            return WanResult(status="FAILED", kind="video", code="JudgeCap",
                             message=f"judge-mode {tier} cap reached; cached replays only")
        res = wan.generate_video(prompt, model=model, negative_prompt=negative_prompt)
        if res.ok and not res.from_cache:
            governor.record_fresh(tier)
        return res

    return gen

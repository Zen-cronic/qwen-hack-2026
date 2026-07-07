"""Metrics ledger — the novelty lives here (see README novelty statement).

Every Qwen/Wan call appends a LedgerEntry: stage, model, tokens_in/out,
latency_ms, cost estimate, and (for shots) a quality rating. The dashboard
reads this to chart the cost-quality frontier and answer: "what does a
minute of finished video cost, and where is the next token best spent?"
"""

# TODO(Jul 6): LedgerEntry dataclass + append-only JSONL writer (data/ledger.jsonl).
#   Wire into the OpenAI client via a thin wrapper — no call escapes unlogged.

# TODO(Jul 7): frontier() -> list[FrontierPoint]
#   Aggregate per-shot spend vs quality rating; expose slope for retry policy.

# TODO(Jul 7): dashboard chart (single static HTML or rich-terminal render is
#   enough for the demo — do not gold-plate; Presentation is 15% of score).

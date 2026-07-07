"""ClipCrew — token-budgeted short-drama pipeline agent on Qwen Cloud.

Pipeline: premise -> script -> storyboard/shot-list -> [HITL checkpoint]
          -> video generation (Wan) -> assembly (ffmpeg) -> cut

Every step reports token spend and latency to the metrics ledger; the
cost-quality frontier is the product's core feature, not telemetry.
"""

__version__ = "0.1.0"

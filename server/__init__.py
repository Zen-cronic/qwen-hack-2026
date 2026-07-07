"""Dailies — CI for AI-generated video ("pytest for video shots"), on Qwen Cloud.

Shot specs compile to machine-checkable assertions run as a cost-tiered cascade:
  premise -> script + specs (qwen-plus) -> compiled assertion checklist
          -> Tier-0 still pre-screen (t2i, 1/25th cost)
          -> [human review gate — the one checkpoint, pre-video-spend]
          -> drafts (wan2.1-t2v-turbo) -> Tier-A CV (zero tokens) + Tier-B VLM (advisory)
          -> bounded prompt-repair + retake -> promote passing shots (wan2.2-t2v-plus)
          -> ffmpeg assembly -> certified episode

Every call reports token/quota spend and latency to the metrics ledger; the
cost-quality frontier is the product's core feature, not telemetry.
"""

__version__ = "0.1.0"

"""Ledger + wallet: the frontier's denominator. No call escapes unlogged."""

from server.metrics import LedgerEntry, LedgerWriter, ResourceKind


def test_est_usd_video_draft():
    e = LedgerEntry(ts=0.0, stage="drafting", kind=ResourceKind.VIDEO_DRAFT,
                    model="wan2.1-t2v-turbo", video_seconds=5)
    assert e.est_usd == 0.5  # 5s * $0.10/s


def test_wallet_aggregates_and_jsonl_is_appended(tmp_path):
    path = tmp_path / "ledger.jsonl"
    lw = LedgerWriter(path)
    lw.record(stage="scripting", kind=ResourceKind.CHAT, model="qwen-plus",
              tokens_in=1000, tokens_out=500)
    lw.record(stage="drafting", kind=ResourceKind.VIDEO_DRAFT, model="wan2.1-t2v-turbo",
              video_seconds=5)
    lw.record(stage="promoting", kind=ResourceKind.VIDEO_FINAL, model="wan2.2-t2v-plus",
              video_seconds=5)
    lw.record(stage="tier0", kind=ResourceKind.IMAGE, model="wan2.1-t2i-plus", images=1)

    w = lw.wallet()
    assert (w.draft_clips, w.final_clips, w.images) == (1, 1, 1)
    assert (w.tokens_in, w.tokens_out, w.video_seconds) == (1000, 500, 10)
    assert abs(w.est_usd - 2.021) < 1e-6  # 0.001 chat + 0.5 draft + 1.5 final + 0.02 image

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 4  # append-only audit trail, one line per call

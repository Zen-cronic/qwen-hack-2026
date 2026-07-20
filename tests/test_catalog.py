"""Catalog layer — the parts that must hold without a database.

Everything here is DB-free on purpose: these guard the two behaviours that are
easy to break silently and expensive to notice — path normalization (the media
route's security boundary AND its OSS lookup key) and the availability gate that
keeps an optional feature from bricking boot.
"""

import pytest

from server import catalog
from server.config import catalog_available, settings


@pytest.fixture
def flag(monkeypatch):
    def _set(on: bool):
        monkeypatch.setattr(settings, "CATALOG_ENABLED", on)
    return _set


class TestNormalizeMediaPath:
    """state.json stores paths verbatim in three different shapes."""

    def test_cwd_relative(self):
        assert catalog.normalize_media_path("data/cache/ab.mp4") == "cache/ab.mp4"

    def test_absolute_under_data_root(self):
        p = catalog.DATA_ROOT / "projects/p1/episode.mp4"
        assert catalog.normalize_media_path(str(p)) == "projects/p1/episode.mp4"

    def test_absolute_from_a_foreign_machine(self):
        # Old snapshots carry another developer's absolute paths; they must still
        # resolve, because the bytes they name live in this box's data dir.
        assert catalog.normalize_media_path(
            "/home/someone-else/checkout/data/cache/zz.png") == "cache/zz.png"

    def test_nested_data_dir(self):
        # e2e runs with DATA_DIR=data/e2e; paths stay relative to the real root.
        assert catalog.normalize_media_path("data/e2e/cache/x.png") == "e2e/cache/x.png"

    @pytest.mark.parametrize("hostile", [
        "../../../etc/passwd",
        "/etc/passwd",
        "/mnt/data/../../etc/passwd",
        "",
        None,
    ])
    def test_traversal_and_empties_are_rejected(self, hostile):
        # This is the security boundary: a None here means the media route never
        # reaches the database, let alone OSS.
        assert catalog.normalize_media_path(hostile) is None


class TestAvailabilityGate:
    def test_off_when_flag_is_off(self, flag):
        flag(False)
        assert catalog_available() is False

    def test_requires_optional_deps(self, flag, monkeypatch):
        # An image built before the catalog deps existed (a rollback, a stale
        # layer) must degrade to catalog-off, not raise ModuleNotFoundError at
        # import time and take the whole app down with it.
        flag(True)
        monkeypatch.setattr("server.config._catalog_deps_installed",
                            lambda: False)
        assert catalog_available() is False

    def test_safe_publish_is_a_noop_when_unavailable(self, flag):
        flag(False)
        assert catalog.safe_publish(store=None, pid="whatever") is None


class TestMediaScope:
    """_collect_media decides what ships to OSS."""

    def _state(self):
        from server.specs import ShotSpec
        from server.store import ProjectState, ShotState, Take

        return ProjectState(
            id="p1", premise="x", pack="short_drama", max_shots=1,
            episode_path="data/projects/p1/episode.mp4",
            shots=[ShotState(
                spec=ShotSpec(index=0, prompt="a shot"),
                still_path="data/cache/still.png",
                final_path="data/cache/final.mp4",
                takes=[
                    Take(take_no=0, tier="draft", model="m", prompt="p",
                         video_path="data/cache/draft.mp4"),
                    Take(take_no=1, tier="final", model="m", prompt="p",
                         video_path="data/cache/final.mp4"),
                ],
            )],
        )

    def test_full_scope_includes_drafts(self):
        paths = [p for p, _ in catalog._collect_media(self._state(), "full")]
        assert "data/cache/draft.mp4" in paths

    def test_minimal_scope_drops_drafts_but_keeps_the_rest(self):
        paths = [p for p, _ in catalog._collect_media(self._state(), "minimal")]
        assert "data/cache/draft.mp4" not in paths
        for kept in ("data/projects/p1/episode.mp4", "data/cache/still.png",
                     "data/cache/final.mp4"):
            assert kept in paths

    def test_episode_is_tagged_as_its_own_kind(self):
        kinds = dict(catalog._collect_media(self._state(), "full"))
        assert kinds["data/projects/p1/episode.mp4"] == "episode"

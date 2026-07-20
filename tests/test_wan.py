"""Wan client flow — mocked HTTP, zero quota: create/poll/download/cache and FAILED."""

from pathlib import Path

import httpx

from server.wan import WanClient, cache_key


def _client(tmp_path, handler):
    http = httpx.Client(transport=httpx.MockTransport(handler), timeout=5)
    return WanClient(api_key="test", cache_dir=tmp_path / "cache", poll_interval=0.0, http=http)


def test_video_success_downloads_and_then_replays_from_cache(tmp_path):
    calls = {"create": 0, "download": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/video-synthesis"):
            calls["create"] += 1
            return httpx.Response(200, json={"output": {"task_id": "t1", "task_status": "PENDING"}})
        if "/tasks/t1" in url:
            return httpx.Response(200, json={"output": {"task_id": "t1", "task_status": "SUCCEEDED",
                                                        "video_url": "https://cdn.example/x.mp4"}})
        if url.endswith("x.mp4"):
            calls["download"] += 1
            return httpx.Response(200, content=b"FAKEMP4")
        return httpx.Response(404)

    c = _client(tmp_path, handler)
    r = c.generate_video("a cat on a fence", model="wan2.1-t2v-turbo", seed=7)
    assert r.ok and not r.from_cache
    assert r.seconds == 5
    assert Path(r.local_path).read_bytes() == b"FAKEMP4"
    assert (calls["create"], calls["download"]) == (1, 1)

    # Identical inputs -> cache hit, no new API traffic, zero billed seconds.
    r2 = c.generate_video("a cat on a fence", model="wan2.1-t2v-turbo", seed=7)
    assert r2.from_cache and r2.ok
    assert r2.seconds == 0
    assert (calls["create"], calls["download"]) == (1, 1)


def test_video_failed_status_surfaces_code_and_message(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/video-synthesis"):
            return httpx.Response(200, json={"output": {"task_id": "t2", "task_status": "PENDING"}})
        if "/tasks/t2" in url:
            return httpx.Response(200, json={"output": {"task_id": "t2", "task_status": "FAILED",
                                                        "code": "InvalidParameter",
                                                        "message": "prompt must contain words"}})
        return httpx.Response(404)

    c = _client(tmp_path, handler)
    r = c.generate_video("x", model="wan2.1-t2v-turbo", seed=1)
    assert r.status == "FAILED"
    assert r.code == "InvalidParameter"
    assert r.local_path is None
    assert not r.ok


def test_image_success_uses_results_url(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/image-synthesis"):
            return httpx.Response(200, json={"output": {"task_id": "i1", "task_status": "PENDING"}})
        if "/tasks/i1" in url:
            return httpx.Response(200, json={"output": {"task_id": "i1", "task_status": "SUCCEEDED",
                                                        "results": [{"url": "https://cdn.example/y.png"}]}})
        if url.endswith("y.png"):
            return httpx.Response(200, content=b"PNGDATA")
        return httpx.Response(404)

    c = _client(tmp_path, handler)
    r = c.generate_image("a red apple", model="wan2.1-t2i-plus", seed=2)
    assert r.ok and r.kind == "image"
    assert Path(r.local_path).read_bytes() == b"PNGDATA"


def test_cache_key_is_stable_and_input_sensitive():
    a = cache_key("m", "p", 1, "1280*720", None)
    assert a == cache_key("m", "p", 1, "1280*720", None)
    assert a != cache_key("m", "p", 2, "1280*720", None)   # seed
    assert a != cache_key("m", "p2", 1, "1280*720", None)  # prompt


def test_video_size_is_chosen_per_model(tmp_path):
    """The premium final model rejects the draft model's frame size (verified live
    2026-07-15), and _promote hides that rejection — so the size must follow the model."""
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/video-synthesis"):
            import json
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"output": {"task_id": "t9", "task_status": "SUCCEEDED",
                                                        "video_url": "https://cdn.example/y.mp4"}})
        if "/tasks/t9" in url:
            return httpx.Response(200, json={"output": {"task_id": "t9", "task_status": "SUCCEEDED",
                                                        "video_url": "https://cdn.example/y.mp4"}})
        if url.endswith("y.mp4"):
            return httpx.Response(200, content=b"FAKEMP4")
        return httpx.Response(404)

    c = _client(tmp_path, handler)
    c.generate_video("a lighthouse", model="wan2.1-t2v-turbo")
    c.generate_video("a lighthouse", model="wan2.2-t2v-plus")

    sizes = [s["parameters"]["size"] for s in sent]
    assert sizes == ["1280*720", "1920*1080"], f"size did not follow the model: {sizes}"


def test_video_size_for_maps_models():
    from server.wan import DEFAULT_VIDEO_SIZE, video_size_for

    assert video_size_for("wan2.2-t2v-plus") == "1920*1080"   # rejects 1280*720
    assert video_size_for("wan2.1-t2v-turbo") == DEFAULT_VIDEO_SIZE == "1280*720"
    assert video_size_for("some-unknown-model") == DEFAULT_VIDEO_SIZE

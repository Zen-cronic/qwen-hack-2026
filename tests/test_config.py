"""Settings: defaults apply without a .env; env vars override and coerce types."""

from server.config import Settings


def test_defaults_apply_without_env(monkeypatch):
    for k in ("JUDGE_MODE", "DAILIES_DEMO", "QWEN_CHAT_MODEL", "WAN_DRAFT_MODEL", "QWEN_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)  # ignore the repo .env — pure defaults
    assert s.QWEN_CHAT_MODEL == "qwen-plus"
    assert s.WAN_DRAFT_MODEL == "wan2.1-t2v-turbo"
    assert s.DASHSCOPE_BASE_URL == "https://dashscope-intl.aliyuncs.com"
    assert s.JUDGE_MODE is False
    assert s.QWEN_API_KEY == ""  # importing never crashes when the secret is absent


def test_env_overrides_and_bool_coercion(monkeypatch):
    monkeypatch.setenv("JUDGE_MODE", "1")
    monkeypatch.setenv("QWEN_CHAT_MODEL", "qwen-max")
    s = Settings(_env_file=None)
    assert s.JUDGE_MODE is True          # "1" -> bool
    assert s.QWEN_CHAT_MODEL == "qwen-max"


def test_unrelated_env_vars_are_ignored(monkeypatch):
    monkeypatch.setenv("SOME_UNRELATED_VAR", "x")  # extra=ignore -> no crash
    Settings(_env_file=None)

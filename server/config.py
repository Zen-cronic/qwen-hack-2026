"""Centralized settings — the env-driven `settings` singleton. Every field has a default."""

from functools import lru_cache
from importlib.util import find_spec

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # env vars first, then repo-root .env, then the defaults below; ignore unrelated env vars.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("JUDGE_MODE", "DAILIES_DEMO", "CATALOG_ENABLED", mode="before")
    @classmethod
    def _blank_bool_is_off(cls, v: object) -> object:
        # Required: pydantic-settings >=2.13 refuses "" -> bool and would crash boot.
        return False if isinstance(v, str) and v.strip() == "" else v

    # Qwen Cloud access
    QWEN_API_KEY: str = ""
    QWEN_BASE_URL: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"  # OpenAI-compat: chat + VLM
    DASHSCOPE_BASE_URL: str = "https://dashscope-intl.aliyuncs.com"                 # native async video/image tasks

    # Model roster (verified console roster — docs/verification.md)
    QWEN_CHAT_MODEL: str = "qwen-plus"
    VL_MODEL: str = "qwen-vl-plus"
    VL_SHAPE: str = "openai"          # openai (image_url parts) | dashscope (multimodal-generation)
    WAN_DRAFT_MODEL: str = "wan2.1-t2v-turbo"
    WAN_FINAL_MODEL: str = "wan2.2-t2v-plus"
    WAN_T2I_MODEL: str = "wan2.1-t2i-plus"

    # Paths
    DATA_DIR: str = "data"
    PACKS_DIR: str = "packs"
    SPA_DIST: str = "web/dist"

    # Modes
    JUDGE_MODE: bool = False          # cap fresh clips/session; cached replays free
    DAILIES_DEMO: bool = False        # run the pipeline on synthetic clips, zero video quota
    DAILIES_FIXTURES: bool = False    # REAL Wan clips with pinned prompts; free once the cache is warm

    # Catalog layer (optional, off by default) — Postgres sidecar + OSS media.
    CATALOG_ENABLED: bool = False
    DATABASE_URL: str = ""            # postgresql://dailies:...@db:5432/dailies
    OSS_ACCESS_KEY_ID: str = ""       # least-privilege RAM user, not the account key
    OSS_ACCESS_KEY_SECRET: str = ""
    OSS_BUCKET: str = ""
    OSS_REGION: str = "us-west-1"
    OSS_ENDPOINT: str = "https://oss-us-west-1.aliyuncs.com"  # public — host baked into presigned browser URLs
    OSS_INTERNAL_ENDPOINT: str = ""   # set on the SAS box: https://oss-us-west-1-internal.aliyuncs.com (free traffic)
    OSS_PRESIGN_TTL_S: int = 3600


settings = Settings()


@lru_cache(maxsize=1)
def _catalog_deps_installed() -> bool:
    return all(find_spec(m) is not None
               for m in ("psycopg", "psycopg_pool", "alibabacloud_oss_v2"))


def catalog_available() -> bool:
    """CATALOG_ENABLED *and* the optional deps importable — a missing dep must degrade to off, not brick boot."""
    return bool(settings.CATALOG_ENABLED) and _catalog_deps_installed()

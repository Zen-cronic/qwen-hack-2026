"""Centralized settings — single source of truth for env-driven config.

Follows the pydantic-settings pattern: one BaseSettings subclass, one module-level
`settings` singleton that everything imports (`from server.config import settings`).
Values resolve from OS env vars first, then the repo-root `.env` (via env_file),
then the defaults below. Every field HAS a default so importing this module never
crashes when a full .env is absent (demo mode, tests, fresh checkouts); real-mode
code that needs a secret (QWEN_API_KEY) fails clearly at call time instead.
"""

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
        # An unset compose var (`${VAR:-}`) or a blank .env line arrives as "".
        # Treat that as off, not a hard error — pydantic-settings >=2.13 refuses to
        # parse an empty string into a bool, which would crash boot on the deploy path.
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
    # Live runs stay on the in-memory + state.json path; completed runs publish here.
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
    """CATALOG_ENABLED *and* the optional deps actually importable.

    The flag alone is not enough to gate on: an image built before the catalog
    deps were added (a rollback, a stale layer, a venv that never got them) would
    otherwise raise ModuleNotFoundError at import time and take the whole app
    down. A misconfigured optional feature must degrade to off, never brick boot.
    """
    return bool(settings.CATALOG_ENABLED) and _catalog_deps_installed()

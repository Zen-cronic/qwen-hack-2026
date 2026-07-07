"""Centralized settings — single source of truth for env-driven config.

Follows the pydantic-settings pattern: one BaseSettings subclass, one module-level
`settings` singleton that everything imports (`from server.config import settings`).
Values resolve from OS env vars first, then the repo-root `.env` (via env_file),
then the defaults below. Every field HAS a default so importing this module never
crashes when a full .env is absent (demo mode, tests, fresh checkouts); real-mode
code that needs a secret (QWEN_API_KEY) fails clearly at call time instead.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # env vars first, then repo-root .env, then the defaults below; ignore unrelated env vars.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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


settings = Settings()

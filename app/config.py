"""Application configuration loader."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- App ---
    app_env: str = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    timezone: str = "Asia/Shanghai"

    # --- Database (SQLite for lightweight mode, PostgreSQL for production) ---
    database_url: str = "sqlite+aiosqlite:///./football_prediction.db"
    sync_database_url: str = "sqlite:///./football_prediction.db"

    # --- Redis / Celery ---
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    # --- Football Data API ---
    football_api_provider: str = "football-data"
    api_football_key: str = ""
    api_football_base_url: str = "https://api.football-data.org/v4"
    sportmonks_api_key: str = ""

    # --- AI Model Keys ---
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"

    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.moonshot.cn/v1"

    ernie_api_key: str = ""
    ernie_secret_key: str = ""

    gemini_api_key: str = ""

    anthropic_api_key: str = ""
    openai_api_key: str = ""

    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # --- System Parameters ---
    delta_t: int = 60            # minutes between scheduled predictions
    volatility_threshold: float = 0.15
    learning_rate: float = 0.05
    max_history: int = 5
    max_concurrent_predictions: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

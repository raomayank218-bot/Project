from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://stp_user:stp_pass@localhost:5432/stp_trading"
    database_url_sync: str = "postgresql://stp_user:stp_pass@localhost:5432/stp_trading"

    # Security
    secret_key: str = "dev-secret-key"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8 hours

    # GenAI
    anthropic_api_key: str = ""

    # App
    environment: str = "development"
    log_level: str = "INFO"
    data_dir: str = "/app/data"

    # Trading config
    default_settlement_days: int = 1       # T+1
    fat_finger_price_pct: float = 10.0    # >10% from last price = warning
    fat_finger_notional: float = 1_000_000 # >$1M single order = warning
    session_open: str = "09:30"
    session_close: str = "15:59"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()

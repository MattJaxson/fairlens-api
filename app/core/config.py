from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    APP_NAME: str = "FairLens API"
    API_VERSION: str = "v1"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./fairlens.db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_PRO: str = ""
    STRIPE_PRICE_ENTERPRISE: str = ""

    # Anthropic
    ANTHROPIC_API_KEY: str = ""

    # Security
    SECRET_KEY: str = "change-me-in-production"

    # Tier Limits (requests per month)
    FREE_TIER_LIMIT: int = 100
    PRO_TIER_LIMIT: int = 10_000
    ENTERPRISE_TIER_LIMIT: int = 100_000


settings = Settings()

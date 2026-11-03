from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://rfq:rfq@localhost:5433/rfq"
    redis_url: str = "redis://localhost:6379/0"
    # Browser origins allowed to call the API (the Vite dev server by default).
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # How often the background job closes auctions whose time is up.
    close_sweep_seconds: float = 5.0


settings = Settings()

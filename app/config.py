from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    ptv_dev_id: str
    ptv_api_key: str
    trmnl_webhook_url: str
    default_stop_id: int = 19843  # Melbourne Central
    station_name: str = "Melbourne Central"
    platform_numbers: str | None = None  # Comma-separated, e.g. "1,2"
    refresh_minutes: int = 5


settings = Settings()

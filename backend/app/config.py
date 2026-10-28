from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "CreatorAI Studio API"
    secret_key: str = "development-only-change-me"
    database_url: str = "sqlite:///./creatorai.db"
    media_dir: str = "media"
    frontend_origins: str = "http://localhost:5173"
    max_upload_mb: int = 20
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

settings = Settings()

"""Application configuration from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_host: str = "127.0.0.1"
    app_port: int = 8765
    spotify_client_id: str = ""
    spotify_redirect_uri: str = "http://127.0.0.1:8765/callback"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b"
    whisper_model: str = "small"
    whisper_compute_type: str = "int8"
    data_dir: Path = Path("/data")

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def whisper_models_dir(self) -> Path:
        return self.data_dir / "whisper-models"


settings = Settings()
"""SQLite path and on-disk layout under DATA_DIR."""

from pathlib import Path

from app.config import settings

DB_PATH: Path = settings.data_dir / "overheardr.db"


def init_storage() -> None:
    """Create cache and model directories; SQLite schema ships in a later milestone."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    settings.whisper_models_dir.mkdir(parents=True, exist_ok=True)
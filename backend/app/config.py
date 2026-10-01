"""Application settings. All secrets come from environment variables or a local .env file
that is never committed. Defaults are for local development only."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

DEV_JWT_SECRET = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # blank placeholders in .env fall back to defaults
        extra="ignore",
    )

    app_env: str = "development"
    # Demo mode labels every mock result in the API and UI.
    demo_mode: bool = True

    database_url: str = "sqlite:///" + (BACKEND_DIR / "data" / "talentmatch.db").as_posix()
    storage_dir: str = str(BACKEND_DIR / "data" / "documents")

    jwt_secret: str = DEV_JWT_SECRET
    jwt_expire_minutes: int = 480

    max_upload_mb: int = 10
    max_pdf_pages: int = 40

    # thread  = in-process background worker thread (default for local dev)
    # worker  = separate process: `python -m app.worker` (used by docker compose)
    # inline  = nothing runs automatically; tests call drain() explicitly
    task_mode: str = "thread"
    worker_poll_seconds: float = 1.0
    task_retry_base_seconds: float = 2.0

    llm_provider: str = "mock"
    email_provider: str = "mock"
    email_from: str = "talentmatch-noreply@acme.example"

    # Read-only IMAP access to a recruitment mailbox. The password is a server-side secret and is
    # never stored in the database or returned by the API. Leave empty to keep the connector off.
    mailbox_imap_password: str = ""
    max_email_mb: int = 30

    app_base_url: str = "http://localhost:5173"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()

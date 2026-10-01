"""Application settings, directory creation, and safe logging configuration."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    project_root: Path
    inbox_dir: Path
    data_dir: Path
    logs_dir: Path
    database_path: Path
    openai_api_key: str | None = field(repr=False)
    openai_model: str
    classifier_provider: str = "local"
    local_llm_model: str = ""
    local_llm_base_url: str = "http://127.0.0.1:11434"
    local_llm_timeout: float = 180
    local_llm_validation_retries: int = 1

    @property
    def classifier_model(self) -> str:
        return self.local_llm_model if self.classifier_provider == "local" else self.openai_model

    def ensure_directories(self) -> None:
        """Create application-owned directories without touching source PDFs."""

        for directory in (self.inbox_dir, self.data_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)


def get_settings(project_root: Path | None = None) -> Settings:
    """Load settings, allowing tests to provide an isolated project root."""

    root = (project_root or PROJECT_ROOT).resolve()
    load_dotenv(root / ".env")
    data_dir = root / "data"
    return Settings(
        project_root=root,
        inbox_dir=root / "papers" / "inbox",
        data_dir=data_dir,
        logs_dir=root / "logs",
        database_path=Path(os.getenv("DATABASE_PATH", str(data_dir / "papers.db"))).resolve(),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        classifier_provider=os.getenv("CLASSIFIER_PROVIDER", "local").strip().lower(),
        local_llm_model=os.getenv("LOCAL_LLM_MODEL", "").strip(),
        local_llm_base_url=os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434"),
        local_llm_timeout=float(os.getenv("LOCAL_LLM_TIMEOUT", "180")),
        local_llm_validation_retries=int(os.getenv("LOCAL_LLM_VALIDATION_RETRIES", "1")),
    )


def configure_logging(logs_dir: Path) -> logging.Logger:
    """Configure a rotating file logger that never records paper text or secrets."""

    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("research_paper_classifier")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(
            logs_dir / "app.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        logger.addHandler(handler)
    return logger

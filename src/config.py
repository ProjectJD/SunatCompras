from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH if ENV_PATH.exists() else None)


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    login_url: str
    ruc: str
    user: str
    password: str
    headless: bool
    slow_mo_ms: int
    login_success_url_contains: str
    flask_host: str
    flask_port: int
    artifacts_dir: Path
    auth_state_path: Path
    auth_snapshot_path: Path


def load_settings() -> Settings:
    artifacts_dir = BASE_DIR / "artifacts"
    auth_state_path = BASE_DIR / "playwright" / ".auth" / "storage_state.json"
    auth_snapshot_path = artifacts_dir / "auth_snapshot.json"

    return Settings(
        login_url=os.getenv("SUNAT_LOGIN_URL", "").strip(),
        ruc=os.getenv("SUNAT_RUC", "").strip(),
        user=os.getenv("SUNAT_USER", "").strip(),
        password=os.getenv("SUNAT_PASSWORD", "").strip(),
        headless=_as_bool(os.getenv("HEADLESS"), default=False),
        slow_mo_ms=int(os.getenv("SLOW_MO_MS", "250").strip()),
        login_success_url_contains=os.getenv(
            "LOGIN_SUCCESS_URL_CONTAINS", "e-menu.sunat.gob.pe"
        ).strip(),
        flask_host=os.getenv("FLASK_HOST", "127.0.0.1").strip(),
        flask_port=int(os.getenv("FLASK_PORT", "8000").strip()),
        artifacts_dir=artifacts_dir,
        auth_state_path=auth_state_path,
        auth_snapshot_path=auth_snapshot_path,
    )

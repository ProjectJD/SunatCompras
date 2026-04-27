from __future__ import annotations

import base64
import json
import time
from datetime import UTC, datetime
from typing import Any
from urllib import parse, request

from .config import Settings
from .utils import read_json, write_json


def epoch_to_iso(epoch: int | None) -> str | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat()


def decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}

    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload + padding).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return {}


def extract_token_expiry(token: str) -> int | None:
    payload = decode_jwt_payload(token)
    exp = payload.get("exp")
    return int(exp) if isinstance(exp, (int, float)) else None


def build_token_record(
    token: str,
    refresh_token: str | None,
    source: str,
) -> dict[str, Any]:
    now = int(time.time())
    expires_at = extract_token_expiry(token)
    return {
        "login_success": True,
        "token": token,
        "refresh_token": refresh_token,
        "source": source,
        "captured_at_epoch": now,
        "captured_at_iso": epoch_to_iso(now),
        "expires_at_epoch": expires_at,
        "expires_at_iso": epoch_to_iso(expires_at),
        "is_valid": is_token_record_valid(
            {"token": token, "expires_at_epoch": expires_at}, leeway_seconds=60
        ),
    }


def save_token_record(settings: Settings, record: dict[str, Any]) -> None:
    write_json(settings.token_store_path, record)


def load_token_record(settings: Settings) -> dict[str, Any] | None:
    return read_json(settings.token_store_path)


def is_token_record_valid(
    record: dict[str, Any] | None,
    *,
    leeway_seconds: int = 60,
) -> bool:
    if not record:
        return False

    token = record.get("token")
    if not isinstance(token, str) or not token.strip():
        return False

    expires_at = record.get("expires_at_epoch")
    if not isinstance(expires_at, (int, float)):
        return False

    return int(expires_at) > int(time.time()) + leeway_seconds


def try_refresh_token(settings: Settings, record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not record:
        return None

    refresh_token = record.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        return None

    if not settings.refresh_url:
        return None

    data = parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.refresh_client_id,
            "client_secret": settings.refresh_client_secret,
        }
    ).encode("utf-8")

    req = request.Request(
        settings.refresh_url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    access_token = payload.get("access_token") or payload.get("token") or payload.get("code")
    next_refresh = payload.get("refresh_token") or refresh_token
    if not isinstance(access_token, str) or not access_token.strip():
        return None

    refreshed = build_token_record(access_token.strip(), next_refresh, source="refresh")
    save_token_record(settings, refreshed)
    return refreshed

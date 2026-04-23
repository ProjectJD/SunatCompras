from __future__ import annotations

from flask import Flask, jsonify, request

from .config import load_settings
from .login import perform_login
from .utils import read_json


app = Flask(__name__)


@app.get("/health")
def health():
    settings = load_settings()
    return jsonify(
        {
            "ok": True,
            "service": "sunat-playwright-login",
            "login_url_configured": bool(settings.login_url),
            "auth_state_exists": settings.auth_state_path.exists(),
            "auth_snapshot_exists": settings.auth_snapshot_path.exists(),
        }
    )


@app.post("/auth/login")
def auth_login():
    payload = request.get_json(silent=True) or {}
    timeout_seconds = int(payload.get("timeout_seconds", 180))
    debug = bool(payload.get("debug", False))

    try:
        result = perform_login(timeout_seconds=timeout_seconds, debug=debug)
        status = 200 if result.get("ok") else 408
        return jsonify(result), status
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Error inesperado: {exc}"}), 500


@app.get("/auth/token")
def auth_token():
    settings = load_settings()
    snapshot = read_json(settings.auth_snapshot_path)
    if not snapshot:
        return (
            jsonify(
                {
                    "ok": False,
                    "message": "No hay snapshot de autenticacion. Ejecuta primero POST /auth/login.",
                }
            ),
            404,
        )

    return jsonify(
        {
            "ok": True,
            "token_candidates": snapshot.get("token_candidates", []),
            "current_url": snapshot.get("current_url"),
            "notes": snapshot.get("notes", []),
        }
    )


@app.get("/auth/session")
def auth_session():
    settings = load_settings()
    snapshot = read_json(settings.auth_snapshot_path)
    return jsonify(
        {
            "ok": True,
            "storage_state_path": str(settings.auth_state_path),
            "storage_state_exists": settings.auth_state_path.exists(),
            "auth_snapshot_path": str(settings.auth_snapshot_path),
            "auth_snapshot_exists": settings.auth_snapshot_path.exists(),
            "snapshot": snapshot,
        }
    )


def main() -> None:
    settings = load_settings()
    app.run(host=settings.flask_host, port=settings.flask_port, debug=False)


if __name__ == "__main__":
    main()

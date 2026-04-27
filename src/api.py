from __future__ import annotations

from flask import Flask, jsonify, request

from .cpe_client import fetch_comprobante_artifacts
from .config import load_settings
from .login import perform_login
from .token_manager import (
    is_token_record_valid,
    load_token_record,
    try_refresh_token,
)
from .utils import read_json


app = Flask(__name__)


def ensure_valid_token() -> tuple[dict, int]:
    settings = load_settings()
    stored = load_token_record(settings)

    if is_token_record_valid(stored):
        return (
            {
                "ok": True,
                "login_success": True,
                "token": stored.get("token"),
                "refresh_token": stored.get("refresh_token"),
                "source": "cache",
            },
            200,
        )

    refreshed = try_refresh_token(settings, stored)
    if refreshed and is_token_record_valid(refreshed):
        return (
            {
                "ok": True,
                "login_success": True,
                "token": refreshed.get("token"),
                "refresh_token": refreshed.get("refresh_token"),
                "source": "refresh",
            },
            200,
        )

    login_result = perform_login(timeout_seconds=180, debug=False)
    if login_result.get("ok"):
        return (
            {
                "ok": True,
                "login_success": True,
                "token": login_result.get("token"),
                "refresh_token": login_result.get("refresh_token"),
                "source": "login",
            },
            200,
        )

    return (
        {
            "ok": False,
            "login_success": False,
            "message": login_result.get("message", "No fue posible autenticar con SUNAT."),
        },
        422,
    )


def force_new_login() -> tuple[dict, int]:
    login_result = perform_login(timeout_seconds=180, debug=False)
    if login_result.get("ok"):
        return (
            {
                "ok": True,
                "login_success": True,
                "token": login_result.get("token"),
                "refresh_token": login_result.get("refresh_token"),
                "source": "login",
            },
            200,
        )
    return (
        {
            "ok": False,
            "login_success": False,
            "message": login_result.get("message", "No fue posible autenticar con SUNAT."),
        },
        422,
    )


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
    force_login = bool(payload.get("force_login", False))

    try:
        if not force_login:
            result, status = ensure_valid_token()
            return jsonify(result), status

        result = perform_login(timeout_seconds=timeout_seconds, debug=debug)
        status = 200 if result.get("ok") else 422
        return jsonify(result), status
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Error inesperado: {exc}"}), 500


@app.get("/auth/token")
def auth_token():
    settings = load_settings()
    stored = load_token_record(settings)
    if not stored:
        return (
            jsonify(
                {
                    "ok": False,
                    "message": "No hay token guardado. Ejecuta primero POST /auth/login.",
                }
            ),
            404,
        )

    token = stored.get("token")
    if not token:
        return (
            jsonify(
                {
                    "ok": False,
                    "message": "No se encontro token guardado.",
                }
            ),
            404,
        )

    return jsonify({
        "ok": True,
        "token": token,
        "refresh_token": stored.get("refresh_token"),
        "is_valid": is_token_record_valid(stored),
    })


@app.post("/auth/ensure")
def auth_ensure():
    payload, status = ensure_valid_token()
    return jsonify(payload), status


@app.post("/consultacompras/xml")
def consulta_compras_xml():
    body = request.get_json(silent=True) or {}
    ruc_emisor = str(body.get("ruc_emisor") or body.get("ruc") or "").strip()
    tipo_documento_emisor = str(
        body.get("tipo_documento_emisor") or body.get("tipo_documento") or "01"
    ).strip()
    indicador_consulta = str(body.get("indicador_consulta") or "2").strip()
    tipo_comprobante = str(body.get("tipo_comprobante") or "").strip()
    serie_documento = str(body.get("serie_documento", "")).strip()
    numero_documento = str(body.get("numero_documento", "")).strip()

    missing = [
        field
        for field, value in (
            ("ruc_emisor", ruc_emisor),
            ("tipo_comprobante", tipo_comprobante),
            ("serie_documento", serie_documento),
            ("numero_documento", numero_documento),
        )
        if not value
    ]
    if missing:
        return (
            jsonify(
                {
                    "ok": False,
                    "message": f"Faltan campos obligatorios: {', '.join(missing)}",
                }
            ),
            400,
        )

    auth_payload, status = ensure_valid_token()
    if status != 200:
        return (
            jsonify(
                {
                    "ok": False,
                    "message": auth_payload.get("message", "No fue posible autenticar con SUNAT."),
                }
            ),
            status,
        )

    consulta_result = fetch_comprobante_artifacts(
        token=auth_payload.get("token", ""),
        ruc_emisor=ruc_emisor,
        serie_documento=serie_documento,
        numero_documento=numero_documento,
        indicador_consulta=indicador_consulta,
        tipo_comprobante=tipo_comprobante,
    )

    if consulta_result.get("auth_error"):
        relogin_payload, relogin_status = force_new_login()
        if relogin_status == 200:
            consulta_result = fetch_comprobante_artifacts(
                token=relogin_payload.get("token", ""),
                ruc_emisor=ruc_emisor,
                serie_documento=serie_documento,
                numero_documento=numero_documento,
                indicador_consulta=indicador_consulta,
                tipo_comprobante=tipo_comprobante,
            )
            auth_payload = relogin_payload
        else:
            return (
                jsonify(
                    {
                        "ok": False,
                        "message": relogin_payload.get(
                            "message", "No fue posible reautenticar con SUNAT."
                        ),
                    }
                ),
                relogin_status,
            )

    if not consulta_result.get("ok"):
        return (
            jsonify(
                {
                    "ok": False,
                    "message": consulta_result.get("error_message")
                    or "SUNAT no devolvio un ZIP valido.",
                    "sunat_status_code": consulta_result.get("status_code"),
                    "sunat_content_type": consulta_result.get("content_type"),
                    "error_payload": consulta_result.get("error_payload"),
                }
            ),
            502,
        )

    zip_original_by_tipo_descarga = consulta_result.get("zip_original_by_tipo_descarga") or {}
    zip_original = (
        zip_original_by_tipo_descarga.get("02")
        or zip_original_by_tipo_descarga.get("01")
        or zip_original_by_tipo_descarga.get("03")
    )

    return jsonify(
        {
            "ok": True,
            "status": "success",
            "message": "Consulta realizada correctamente.",
            "data": {
                "consulta": {
                    "ruc_emisor": ruc_emisor,
                    "tipo_documento_emisor": tipo_documento_emisor,
                    "indicador_consulta": indicador_consulta,
                    "tipo_comprobante": tipo_comprobante,
                    "serie_documento": serie_documento,
                    "numero_documento": numero_documento,
                    "sunat_url": consulta_result.get("artifact_urls"),
                    "sunat_status_code": consulta_result.get("status_code"),
                },
                "zip_original": zip_original,
                "zip_por_tipo_descarga": zip_original_by_tipo_descarga,
                "xml": {
                    "nombre": consulta_result.get("xml_filename"),
                    "mime": "application/xml"
                    if consulta_result.get("xml_base64")
                    else None,
                    "base64": consulta_result.get("xml_base64"),
                    "texto": consulta_result.get("xml_content"),
                },
                "pdf": {
                    "nombre": consulta_result.get("pdf_filename"),
                    "mime": "application/pdf"
                    if consulta_result.get("pdf_base64")
                    else None,
                    "base64": consulta_result.get("pdf_base64"),
                },
                "cdr": {
                    "nombre": consulta_result.get("cdr_filename"),
                    "mime": "application/xml"
                    if consulta_result.get("cdr_base64")
                    else None,
                    "base64": consulta_result.get("cdr_base64"),
                    "texto": consulta_result.get("cdr_content"),
                },
            },
            "sunat_status_code": consulta_result.get("status_code"),
        }
    )


@app.get("/auth/session")
def auth_session():
    settings = load_settings()
    snapshot = read_json(settings.auth_snapshot_path)
    token_store = load_token_record(settings)
    return jsonify(
        {
            "ok": True,
            "storage_state_path": str(settings.auth_state_path),
            "storage_state_exists": settings.auth_state_path.exists(),
            "auth_snapshot_path": str(settings.auth_snapshot_path),
            "auth_snapshot_exists": settings.auth_snapshot_path.exists(),
            "snapshot": snapshot,
            "token_store_path": str(settings.token_store_path),
            "token_store": token_store,
        }
    )


def main() -> None:
    settings = load_settings()
    app.run(host=settings.flask_host, port=settings.flask_port, debug=False)


if __name__ == "__main__":
    main()

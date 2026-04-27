from __future__ import annotations

import base64
import io
import json
import zipfile
from urllib import error, request


DEFAULT_TIPO_DOCUMENTO_EMISOR = "01"
DEFAULT_INDICADOR_CONSULTA = "2"
DOWNLOAD_MODE_PDF = "01"
DOWNLOAD_MODE_XML = "02"
DOWNLOAD_MODE_CDR = "03"


def encode_base64(raw_bytes: bytes) -> str:
    return base64.b64encode(raw_bytes).decode("ascii")


def build_consulta_url(
    *,
    ruc_emisor: str,
    tipo_comprobante: str,
    serie_documento: str,
    numero_documento: str,
    indicador_consulta: str,
    tipo_descarga: str,
) -> str:
    document_key = (
        f"{ruc_emisor}-{tipo_comprobante}-{serie_documento}-{numero_documento}-"
        f"{indicador_consulta}/{tipo_descarga}"
    )
    return (
        "https://api-cpe.sunat.gob.pe/v1/contribuyente/consultacpe/comprobantes/"
        f"{document_key}"
    )


def extract_artifacts_from_zip(zip_bytes: bytes) -> dict:
    result = {
        "xml_filename": None,
        "xml_content": None,
        "xml_base64": None,
        "pdf_filename": None,
        "pdf_base64": None,
    }
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            for name in archive.namelist():
                file_bytes = archive.read(name)
                lowered_name = name.lower()
                if lowered_name.endswith(".xml"):
                    result["xml_filename"] = name
                    result["xml_content"] = file_bytes.decode("utf-8", errors="replace")
                    result["xml_base64"] = encode_base64(file_bytes)
                elif lowered_name.endswith(".pdf"):
                    result["pdf_filename"] = name
                    result["pdf_base64"] = encode_base64(file_bytes)
    except zipfile.BadZipFile:
        return result
    return result


def fetch_artifact_from_sunat(
    *,
    token: str,
    ruc_emisor: str,
    serie_documento: str,
    numero_documento: str,
    indicador_consulta: str = DEFAULT_INDICADOR_CONSULTA,
    tipo_comprobante: str,
    tipo_descarga: str,
) -> dict:
    url = build_consulta_url(
        ruc_emisor=ruc_emisor,
        tipo_comprobante=tipo_comprobante,
        serie_documento=serie_documento,
        numero_documento=numero_documento,
        indicador_consulta=indicador_consulta,
        tipo_descarga=tipo_descarga,
    )

    req = request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://e-factura.sunat.gob.pe",
            "Referer": "https://e-factura.sunat.gob.pe/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36"
            ),
        },
        method="GET",
    )

    try:
        with request.urlopen(req, timeout=60) as resp:
            raw_body = resp.read()
            content_type = resp.headers.get("Content-Type", "")

            json_payload = None
            xml_content = None
            xml_base64 = None
            xml_filename = None
            pdf_filename = None
            pdf_base64 = None
            zip_base64 = None

            if "application/json" in content_type.lower():
                try:
                    json_payload = json.loads(raw_body.decode("utf-8", errors="replace"))
                except Exception:
                    json_payload = None

                if isinstance(json_payload, dict):
                    zip_base64 = json_payload.get("valArchivo")
                    if isinstance(zip_base64, str) and zip_base64.strip():
                        try:
                            zip_bytes = base64.b64decode(zip_base64)
                            artifacts = extract_artifacts_from_zip(zip_bytes)
                            xml_filename = artifacts.get("xml_filename")
                            xml_content = artifacts.get("xml_content")
                            xml_base64 = artifacts.get("xml_base64")
                            pdf_filename = artifacts.get("pdf_filename")
                            pdf_base64 = artifacts.get("pdf_base64")
                        except Exception:
                            xml_content = None
                            xml_base64 = None
                            xml_filename = None
                            pdf_filename = None
                            pdf_base64 = None
            else:
                artifacts = extract_artifacts_from_zip(raw_body)
                xml_filename = artifacts.get("xml_filename")
                xml_content = artifacts.get("xml_content")
                xml_base64 = artifacts.get("xml_base64")
                pdf_filename = artifacts.get("pdf_filename")
                pdf_base64 = artifacts.get("pdf_base64")

            return {
                "ok": any((xml_content is not None, xml_base64 is not None, pdf_base64 is not None, zip_base64 is not None)),
                "status_code": resp.status,
                "content_type": content_type,
                "url": url,
                "tipo_descarga": tipo_descarga,
                "xml_filename": xml_filename,
                "xml_content": xml_content,
                "xml_base64": xml_base64,
                "pdf_filename": pdf_filename,
                "pdf_base64": pdf_base64,
                "zip_base64": zip_base64,
                "json_payload": json_payload,
                "raw_size": len(raw_body),
                "error_message": None
                if any((xml_content is not None, pdf_base64 is not None, zip_base64 is not None))
                else "SUNAT respondio, pero no se encontro XML ni PDF dentro del ZIP.",
                "auth_error": resp.status in (401, 403),
            }
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        parsed_error = None
        try:
            parsed_error = json.loads(body)
        except Exception:
            parsed_error = None
        return {
            "ok": False,
            "status_code": exc.code,
            "content_type": exc.headers.get("Content-Type", ""),
            "url": url,
            "tipo_descarga": tipo_descarga,
            "xml_filename": None,
            "xml_content": None,
            "xml_base64": None,
            "pdf_filename": None,
            "pdf_base64": None,
            "zip_base64": None,
            "raw_size": 0,
            "error_message": (
                parsed_error.get("msg")
                if isinstance(parsed_error, dict) and parsed_error.get("msg")
                else body[:1000] or str(exc)
            ),
            "error_payload": parsed_error,
            "auth_error": exc.code in (401, 403),
        }
    except Exception as exc:
        return {
            "ok": False,
            "status_code": None,
            "content_type": None,
            "url": url,
            "tipo_descarga": tipo_descarga,
            "xml_filename": None,
            "xml_content": None,
            "xml_base64": None,
            "pdf_filename": None,
            "pdf_base64": None,
            "zip_base64": None,
            "raw_size": 0,
            "error_message": f"No fue posible consumir SUNAT: {exc}",
            "auth_error": False,
        }


def combine_artifact_results(*results: dict) -> dict:
    combined = {
        "ok": any(result.get("ok") for result in results),
        "status_code": None,
        "content_type": None,
        "url": None,
        "xml_filename": None,
        "xml_content": None,
        "xml_base64": None,
        "pdf_filename": None,
        "pdf_base64": None,
        "cdr_filename": None,
        "cdr_base64": None,
        "cdr_content": None,
        "zip_base64": None,
        "json_payload": None,
        "raw_size": 0,
        "error_message": None,
        "error_payload": None,
        "auth_error": any(result.get("auth_error") for result in results),
        "zip_original_by_tipo_descarga": {},
        "artifact_urls": {},
    }

    error_messages = []
    for result in results:
        tipo_descarga = result.get("tipo_descarga")
        if tipo_descarga:
            combined["artifact_urls"][tipo_descarga] = result.get("url")
        if result.get("zip_base64") and tipo_descarga:
            combined["zip_original_by_tipo_descarga"][tipo_descarga] = {
                "nombre": (result.get("json_payload") or {}).get("nomArchivo"),
                "mime": "application/zip",
                "base64": result.get("zip_base64"),
            }
        if (
            tipo_descarga == DOWNLOAD_MODE_XML
            and result.get("xml_base64")
            and not combined["xml_base64"]
        ):
            combined["xml_filename"] = result.get("xml_filename")
            combined["xml_content"] = result.get("xml_content")
            combined["xml_base64"] = result.get("xml_base64")
        if (
            tipo_descarga == DOWNLOAD_MODE_CDR
            and result.get("xml_base64")
            and not combined["cdr_base64"]
        ):
            combined["cdr_filename"] = result.get("xml_filename")
            combined["cdr_content"] = result.get("xml_content")
            combined["cdr_base64"] = result.get("xml_base64")
        if result.get("pdf_base64") and not combined["pdf_base64"]:
            combined["pdf_filename"] = result.get("pdf_filename")
            combined["pdf_base64"] = result.get("pdf_base64")
        if result.get("status_code") and not combined["status_code"]:
            combined["status_code"] = result.get("status_code")
        if result.get("content_type") and not combined["content_type"]:
            combined["content_type"] = result.get("content_type")
        if result.get("url") and not combined["url"]:
            combined["url"] = result.get("url")
        combined["raw_size"] += int(result.get("raw_size") or 0)
        if result.get("error_message"):
            error_messages.append(result.get("error_message"))

    if not combined["ok"]:
        combined["error_message"] = " | ".join(error_messages) if error_messages else (
            "SUNAT no devolvio XML ni PDF para la consulta."
        )

    return combined


def fetch_comprobante_artifacts(
    *,
    token: str,
    ruc_emisor: str,
    serie_documento: str,
    numero_documento: str,
    indicador_consulta: str = DEFAULT_INDICADOR_CONSULTA,
    tipo_comprobante: str,
) -> dict:
    pdf_result = fetch_artifact_from_sunat(
        token=token,
        ruc_emisor=ruc_emisor,
        serie_documento=serie_documento,
        numero_documento=numero_documento,
        indicador_consulta=indicador_consulta,
        tipo_comprobante=tipo_comprobante,
        tipo_descarga=DOWNLOAD_MODE_PDF,
    )
    xml_result = fetch_artifact_from_sunat(
        token=token,
        ruc_emisor=ruc_emisor,
        serie_documento=serie_documento,
        numero_documento=numero_documento,
        indicador_consulta=indicador_consulta,
        tipo_comprobante=tipo_comprobante,
        tipo_descarga=DOWNLOAD_MODE_XML,
    )
    cdr_result = fetch_artifact_from_sunat(
        token=token,
        ruc_emisor=ruc_emisor,
        serie_documento=serie_documento,
        numero_documento=numero_documento,
        indicador_consulta=indicador_consulta,
        tipo_comprobante=tipo_comprobante,
        tipo_descarga=DOWNLOAD_MODE_CDR,
    )
    return combine_artifact_results(pdf_result, xml_result, cdr_result)

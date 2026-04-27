from __future__ import annotations

import argparse
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Request, Response, sync_playwright

from .config import load_settings
from .utils import write_json

PROBE_TARGETS = {
    "menu-execute-consultacpe": (
        "https://e-menu.sunat.gob.pe/cl-ti-itmenu/"
        "MenuInternet.htm?action=execute&code=11.38.1.1.1&s=ww1"
    ),
    "consulta-integrada": "https://e-menu.sunat.gob.pe/ol-ti-itconsultaunificada/consultaUnificada/consulta",
    "consultacpe-loader": (
        "https://e-menu.sunat.gob.pe/app/contribuyentems/servicio/consultacpe/"
        "consulta/loader/nuevaconsulta.html"
    ),
    "consultacpe-loader-sww1": (
        "https://e-menu.sunat.gob.pe/app/contribuyentems/servicio/consultacpe/"
        "consulta/loader/nuevaconsulta.html?s=ww1"
    ),
    "consultacpe-loader-ww1": (
        "https://ww1.sunat.gob.pe/app/contribuyentems/servicio/consultacpe/"
        "consulta/loader/nuevaconsulta.html"
    ),
    "e-factura": "https://e-factura.sunat.gob.pe/",
}

INTERESTING_TERMS = (
    "consultacpe",
    "consultaunificada",
    "comprobante",
    "comprobantes",
    "api-cpe",
    "token",
    "auth",
    "bearer",
    "xml",
    "archivo",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe de red para modulos CPE de SUNAT")
    parser.add_argument(
        "--target",
        choices=sorted(PROBE_TARGETS),
        default="consultacpe-loader",
        help="Modulo a abrir con la sesion autenticada",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=10,
        help="Segundos para observar llamadas luego de abrir la pagina",
    )
    return parser.parse_args()


def log(message: str) -> None:
    print(f"[sunat-probe] {message}")


def is_interesting(value: str) -> bool:
    lowered = (value or "").lower()
    return any(term in lowered for term in INTERESTING_TERMS)


class ProbeTracker:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def on_request(self, request: Request) -> None:
        url = request.url
        headers = dict(request.headers)
        body = request.post_data or ""
        if not (
            is_interesting(url)
            or any(is_interesting(f"{key}:{value}") for key, value in headers.items())
            or is_interesting(body)
        ):
            return

        self.events.append(
            {
                "type": "request",
                "url": url,
                "method": request.method,
                "resource_type": request.resource_type,
                "headers": {
                    key: value
                    for key, value in headers.items()
                    if key.lower() in {"authorization", "content-type", "referer", "origin", "x-csrf-token"}
                    or "token" in key.lower()
                    or "auth" in key.lower()
                },
                "post_data_excerpt": body[:1500],
            }
        )

    def on_response(self, response: Response) -> None:
        url = response.url
        headers = dict(response.headers)
        body_excerpt = ""
        content_type = headers.get("content-type", "")
        if "json" in content_type.lower() or is_interesting(url):
            try:
                body_excerpt = response.text()[:2000]
            except Exception:
                body_excerpt = ""

        if not (
            is_interesting(url)
            or any(is_interesting(f"{key}:{value}") for key, value in headers.items())
            or is_interesting(body_excerpt)
        ):
            return

        self.events.append(
            {
                "type": "response",
                "url": url,
                "status": response.status,
                "status_text": response.status_text,
                "headers": {
                    key: value
                    for key, value in headers.items()
                    if key.lower() in {"content-type", "location", "set-cookie", "x-csrf-token"}
                    or "token" in key.lower()
                    or "auth" in key.lower()
                },
                "body_excerpt": body_excerpt,
            }
        )


def build_output_path(target: str) -> Path:
    settings = load_settings()
    return settings.artifacts_dir / f"probe_{target}.json"


def run_probe(target: str, wait_seconds: int) -> dict:
    settings = load_settings()
    if not settings.auth_state_path.exists():
        raise ValueError(
            f"No existe la sesion guardada en {settings.auth_state_path}. Ejecuta primero el login."
        )

    probe_url = PROBE_TARGETS[target]
    tracker = ProbeTracker()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=settings.headless,
            slow_mo=settings.slow_mo_ms,
        )
        context = browser.new_context(storage_state=str(settings.auth_state_path))
        page = context.new_page()
        page.on("request", tracker.on_request)
        page.on("response", tracker.on_response)

        try:
            log(f"Abriendo target: {probe_url}")
            page.goto(probe_url, wait_until="domcontentloaded", timeout=120000)
            time.sleep(wait_seconds)

            result = {
                "target": target,
                "target_url": probe_url,
                "final_url": page.url,
                "final_host": urlparse(page.url).netloc.lower(),
                "title": page.title(),
                "event_count": len(tracker.events),
                "events": tracker.events,
            }
            output_path = build_output_path(target)
            write_json(output_path, result)
            log(f"Probe guardado en: {output_path}")
            return result
        finally:
            browser.close()


def main() -> None:
    args = parse_args()
    result = run_probe(target=args.target, wait_seconds=args.wait_seconds)
    print(
        {
            "ok": True,
            "target": result["target"],
            "final_url": result["final_url"],
            "event_count": result["event_count"],
        }
    )


if __name__ == "__main__":
    main()

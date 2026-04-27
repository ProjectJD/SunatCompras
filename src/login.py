from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Request, Response, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .config import load_settings
from .selectors import PASSWORD_SELECTORS, RUC_SELECTORS, SUBMIT_SELECTORS, USER_SELECTORS
from .token_manager import build_token_record, save_token_record
from .utils import (
    ensure_parent_dir,
    first_visible_locator,
    first_visible_locator_in_frames,
    write_json,
    write_text,
)

NETWORK_LOG_LIMIT = 80
CONSULTACPE_MENU_URL = (
    "https://e-menu.sunat.gob.pe/cl-ti-itmenu/"
    "MenuInternet.htm?action=execute&code=11.38.1.1.1&s=ww1"
)
INTERESTING_TERMS = (
    "token",
    "auth",
    "oauth",
    "jwt",
    "bearer",
    "menu",
    "session",
    "login",
    "clave",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Login a SUNAT con Playwright")
    parser.add_argument("--debug", action="store_true", help="Guarda screenshot y HTML")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=180,
        help="Tiempo maximo para completar el login",
    )
    return parser.parse_args()


def log(message: str) -> None:
    print(f"[sunat-login] {message}")


def dump_debug(page, settings) -> None:
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = settings.artifacts_dir / "last_page.png"
    html_path = settings.artifacts_dir / "last_page.html"
    page.screenshot(path=str(screenshot_path), full_page=True)
    write_text(html_path, page.content())
    log(f"Screenshot guardado en: {screenshot_path}")
    log(f"HTML guardado en: {html_path}")


def log_visible_inputs(page) -> None:
    for frame in page.frames:
        try:
            frame_name = frame.name or "<main>"
            inputs = frame.locator("input").all()
            if not inputs:
                continue
            log(f"Inputs detectados en frame {frame_name}: {len(inputs)}")
            for index, locator in enumerate(inputs[:15], start=1):
                attrs = locator.evaluate(
                    """(el) => ({
                        type: el.getAttribute('type') || '',
                        name: el.getAttribute('name') || '',
                        id: el.getAttribute('id') || '',
                        placeholder: el.getAttribute('placeholder') || '',
                        ariaLabel: el.getAttribute('aria-label') || '',
                        autocomplete: el.getAttribute('autocomplete') || ''
                    })"""
                )
                log(
                    f"  input#{index}: type={attrs['type']} name={attrs['name']} id={attrs['id']} "
                    f"placeholder={attrs['placeholder']} aria={attrs['ariaLabel']} autocomplete={attrs['autocomplete']}"
                )
        except Exception:
            continue


def _extract_tokens_from_text(value: str) -> list[str]:
    if not value:
        return []

    results: list[str] = []
    parts = [
        segment.strip()
        for segment in value.replace("#", "&").replace("?", "&").split("&")
        if "=" in segment
    ]
    for part in parts:
        key, token_value = part.split("=", 1)
        lowered = key.lower()
        if "token" in lowered and token_value:
            results.append(token_value)
    return results


def extract_auth_code_from_network(network_summary: dict | None) -> str | None:
    if not network_summary:
        return None

    for response in network_summary.get("interesting_responses", []):
        location = (response.get("headers", {}) or {}).get("location", "")
        if not location:
            continue
        parsed = urlparse(location)
        code_values = parse_qs(parsed.query).get("code", [])
        for code in code_values:
            if code.strip():
                return code.strip()
    return None


def extract_consultacpe_token_from_network(network_summary: dict | None) -> str | None:
    if not network_summary:
        return None

    for response in network_summary.get("interesting_responses", []):
        location = (response.get("headers", {}) or {}).get("location", "")
        if not location:
            continue
        parsed = urlparse(location)
        token_values = parse_qs(parsed.query).get("token", [])
        for token in token_values:
            token = token.strip()
            if token:
                return token
    return None


def is_jwt_like(value: str | None) -> bool:
    if not isinstance(value, str):
        return False
    parts = value.split(".")
    return len(parts) == 3 and all(part.strip() for part in parts)


def extract_primary_token(snapshot: dict) -> str | None:
    storage = snapshot.get("storage", {})
    session_storage = storage.get("sessionStorage", {}) if isinstance(storage, dict) else {}
    session_token = session_storage.get("SUNAT.token")
    if is_jwt_like(session_token):
        return session_token.strip()

    consultacpe_token = snapshot.get("consultacpe_token")
    if is_jwt_like(consultacpe_token):
        return consultacpe_token.strip()

    auth_code = snapshot.get("auth_code")
    if is_jwt_like(auth_code):
        return auth_code.strip()

    candidates = snapshot.get("token_candidates", [])
    for candidate in candidates:
        if is_jwt_like(candidate):
            return candidate.strip()

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def is_interesting_text(value: str) -> bool:
    lowered = (value or "").lower()
    return any(term in lowered for term in INTERESTING_TERMS)


class NetworkTracker:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.responses: list[dict] = []

    def track_request(self, request: Request) -> None:
        url = request.url
        headers = dict(request.headers)
        post_data = request.post_data or ""
        interesting = is_interesting_text(url) or any(
            is_interesting_text(f"{key}:{value}") for key, value in headers.items()
        ) or is_interesting_text(post_data)

        entry = {
            "method": request.method,
            "url": url,
            "resource_type": request.resource_type,
            "interesting": interesting,
            "headers": {
                key: value
                for key, value in headers.items()
                if key.lower() in {"authorization", "cookie", "content-type", "x-csrf-token"}
                or "token" in key.lower()
                or "auth" in key.lower()
            },
            "post_data_excerpt": post_data[:1000] if post_data else "",
        }
        self.requests.append(entry)
        self.requests[:] = self.requests[-NETWORK_LOG_LIMIT:]

    def track_response(self, response: Response) -> None:
        url = response.url
        headers = dict(response.headers)
        content_type = headers.get("content-type", "")
        body_excerpt = ""
        if "application/json" in content_type.lower() or is_interesting_text(url):
            try:
                body_excerpt = response.text()[:1500]
            except Exception:
                body_excerpt = ""

        interesting = is_interesting_text(url) or any(
            is_interesting_text(f"{key}:{value}") for key, value in headers.items()
        ) or is_interesting_text(body_excerpt)

        entry = {
            "url": url,
            "status": response.status,
            "status_text": response.status_text,
            "interesting": interesting,
            "headers": {
                key: value
                for key, value in headers.items()
                if key.lower() in {"set-cookie", "content-type", "location", "authorization", "x-csrf-token"}
                or "token" in key.lower()
                or "auth" in key.lower()
            },
            "body_excerpt": body_excerpt,
        }
        self.responses.append(entry)
        self.responses[:] = self.responses[-NETWORK_LOG_LIMIT:]

    def summary(self) -> dict:
        interesting_requests = [item for item in self.requests if item.get("interesting")]
        interesting_responses = [item for item in self.responses if item.get("interesting")]
        return {
            "interesting_requests": interesting_requests[-20:],
            "interesting_responses": interesting_responses[-20:],
            "request_count": len(self.requests),
            "response_count": len(self.responses),
        }


def build_auth_snapshot(page, context, settings, network_summary: dict | None = None) -> dict:
    current_url = page.url
    parsed = urlparse(current_url)

    query_tokens = []
    for _, values in parse_qs(parsed.query).items():
        for value in values:
            query_tokens.extend(_extract_tokens_from_text(value))

    fragment_tokens = _extract_tokens_from_text(parsed.fragment)

    cookies = context.cookies()
    cookie_candidates = []
    for cookie in cookies:
        name = cookie.get("name", "")
        value = cookie.get("value", "")
        if "token" in name.lower() or "auth" in name.lower() or "session" in name.lower():
            cookie_candidates.append({"name": name, "value": value})

    storage = page.evaluate(
        """() => {
            const pick = (store) => {
                const out = {};
                for (let i = 0; i < store.length; i += 1) {
                    const key = store.key(i);
                    out[key] = store.getItem(key);
                }
                return out;
            };
            return {
                localStorage: pick(window.localStorage),
                sessionStorage: pick(window.sessionStorage),
            };
        }"""
    )

    storage_candidates = []
    for storage_name in ("localStorage", "sessionStorage"):
        items = storage.get(storage_name, {})
        for key, value in items.items():
            if "token" in key.lower() or "auth" in key.lower() or "session" in key.lower():
                storage_candidates.append(
                    {"storage": storage_name, "key": key, "value": value}
                )

    token_candidates = []
    token_candidates.extend(fragment_tokens)
    token_candidates.extend(query_tokens)
    token_candidates.extend(
        item["value"] for item in cookie_candidates if item.get("value")
    )
    token_candidates.extend(
        item["value"] for item in storage_candidates if item.get("value")
    )

    if network_summary:
        for response in network_summary.get("interesting_responses", []):
            token_candidates.extend(_extract_tokens_from_text(response.get("body_excerpt", "")))
        for request in network_summary.get("interesting_requests", []):
            token_candidates.extend(_extract_tokens_from_text(request.get("post_data_excerpt", "")))

    unique_candidates = []
    seen = set()
    for candidate in token_candidates:
        if candidate and candidate not in seen:
            unique_candidates.append(candidate)
            seen.add(candidate)

    snapshot = {
        "login_detected": True,
        "captured_at_epoch": int(time.time()),
        "current_url": current_url,
        "current_host": parsed.netloc.lower(),
        "cookies": cookies,
        "cookie_token_candidates": cookie_candidates,
        "storage": storage,
        "storage_token_candidates": storage_candidates,
        "token_candidates": unique_candidates,
        "network": network_summary or {},
        "notes": [
            "Si no aparece token, este flujo de SUNAT probablemente solo deja sesion web y no un access token reutilizable.",
            "Revisa network.interesting_requests y network.interesting_responses para ver el mecanismo real de autenticacion.",
        ],
    }
    snapshot["auth_code"] = extract_auth_code_from_network(network_summary)
    snapshot["consultacpe_token"] = extract_consultacpe_token_from_network(network_summary)
    snapshot["refresh_token"] = None
    snapshot["primary_token"] = extract_primary_token(snapshot)
    return snapshot


def apply_input_value(locator, value: str, label: str) -> bool:
    try:
        locator.click()
        locator.fill(value)
        locator.dispatch_event("input")
        locator.dispatch_event("change")
        locator.dispatch_event("blur")
        log(f"{label} completado automaticamente.")
        return True
    except Exception as exc:
        log(f"No se pudo completar {label}: {exc}")
        return False


def sync_hidden_fields(page, settings) -> None:
    try:
        page.evaluate(
            """(payload) => {
                const setIfExists = (id, value) => {
                    const el = document.getElementById(id);
                    if (!el || value === undefined || value === null) return;
                    el.value = value;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                };
                setIfExists('custom_ruc', payload.ruc);
                setIfExists('j_username', payload.user);
                setIfExists('j_password', payload.password);
            }""",
            {
                "ruc": settings.ruc,
                "user": settings.user,
                "password": settings.password,
            },
        )
        log("Campos hidden sincronizados para el submit.")
    except Exception as exc:
        log(f"No se pudieron sincronizar campos hidden: {exc}")


def attempt_fill_login(page, settings) -> bool:
    filled_any = False

    if settings.ruc:
        ruc_input = first_visible_locator(page, RUC_SELECTORS) or first_visible_locator_in_frames(
            page, RUC_SELECTORS
        )
        if ruc_input:
            filled_any = apply_input_value(ruc_input, settings.ruc, "RUC") or filled_any
        else:
            log("No se encontro un campo visible para RUC.")

    if settings.user:
        user_input = first_visible_locator(page, USER_SELECTORS) or first_visible_locator_in_frames(
            page, USER_SELECTORS
        )
        if user_input:
            filled_any = apply_input_value(user_input, settings.user, "Usuario") or filled_any
        else:
            log("No se encontro un campo visible para usuario.")

    if settings.password:
        password_input = first_visible_locator(page, PASSWORD_SELECTORS) or first_visible_locator_in_frames(
            page, PASSWORD_SELECTORS
        )
        if password_input:
            filled_any = apply_input_value(password_input, settings.password, "Clave") or filled_any
        else:
            log("No se encontro un campo visible para clave.")

    if filled_any:
        sync_hidden_fields(page, settings)

    submit_button = first_visible_locator(page, SUBMIT_SELECTORS) or first_visible_locator_in_frames(
        page, SUBMIT_SELECTORS
    )
    if submit_button and filled_any:
        try:
            submit_button.click(timeout=5000)
            log("Se hizo click en el boton de envio.")
        except Exception as exc:
            log(f"No se pudo hacer click en el boton de envio: {exc}")
    elif filled_any:
        log("Se llenaron campos, pero no se encontro un boton visible de envio.")

    return filled_any


def wait_for_login_success(page, settings, timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    success_hint = settings.login_success_url_contains.lower().replace("https://", "").replace("http://", "").strip("/")

    log("Esperando confirmacion de login. Completa manualmente cualquier paso faltante en el navegador.")

    while time.time() < deadline:
        current_url = page.url
        parsed = urlparse(current_url)
        current_host = parsed.netloc.lower()
        current_url_lower = current_url.lower()
        in_login_flow = "loginmenusol" in current_url_lower

        if success_hint and current_host == success_hint and not in_login_flow:
            log(f"Login detectado por host final: {current_url}")
            return True

        try:
            page_text = page.locator("body").inner_text(timeout=1000).lower()
        except Exception:
            page_text = ""

        login_markers = ["iniciar sesi", "login", "clave sol", "usuario", "contrase"]
        authenticated_markers = [
            "menu sol",
            "menú sol",
            "bienvenido",
            "cerrar sesi",
            "mis tramites y consultas",
            "mis trámites y consultas",
        ]

        if any(marker in page_text for marker in authenticated_markers) and not any(
            marker in page_text for marker in login_markers
        ):
            log("Login detectado por contenido visible.")
            return True

        time.sleep(1)

    return False


def network_log_path(settings) -> Path:
    return settings.artifacts_dir / "network_log.json"


def navigate_to_consultacpe_menu(page) -> None:
    log("Abriendo el modulo real de consulta CPE para capturar el JWT de api-cpe...")
    page.goto(CONSULTACPE_MENU_URL, wait_until="domcontentloaded", timeout=120000)

    deadline = time.time() + 120
    while time.time() < deadline:
        if page.url.startswith("https://e-factura.sunat.gob.pe/"):
            break
        page.wait_for_timeout(500)

    if not page.url.startswith("https://e-factura.sunat.gob.pe/"):
        raise PlaywrightTimeoutError("No se alcanzo el modulo e-factura de consulta CPE.")

    log(f"URL modulo CPE: {page.url}")


def perform_login(timeout_seconds: int, debug: bool) -> dict:
    settings = load_settings()

    if not settings.login_url:
        raise ValueError("Falta SUNAT_LOGIN_URL en el archivo .env")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=settings.headless,
            slow_mo=settings.slow_mo_ms,
        )
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        tracker = NetworkTracker()

        page.on("request", tracker.track_request)
        page.on("response", tracker.track_response)

        try:
            log("Abriendo URL de login de SUNAT...")
            page.goto(settings.login_url, wait_until="domcontentloaded", timeout=120000)
            log(f"URL actual: {page.url}")
            log(f"Titulo actual: {page.title()}")
            log_visible_inputs(page)

            try:
                attempt_fill_login(page, settings)
            except PlaywrightTimeoutError:
                log("No se pudo completar automaticamente el formulario. Continuaremos en modo manual.")

            success = wait_for_login_success(page, settings, timeout_seconds)

            if debug:
                dump_debug(page, settings)

            network_summary = tracker.summary()
            write_json(network_log_path(settings), network_summary)

            if not success:
                log("No se detecto el login dentro del tiempo esperado.")
                return {
                    "ok": False,
                    "message": "No se detecto un login real dentro del tiempo esperado.",
                    "current_url": page.url,
                    "network": network_summary,
                }

            navigate_to_consultacpe_menu(page)

            ensure_parent_dir(settings.auth_state_path)
            context.storage_state(path=str(settings.auth_state_path))

            snapshot = build_auth_snapshot(page, context, settings, network_summary)
            write_json(settings.auth_snapshot_path, snapshot)
            token = extract_primary_token(snapshot)
            refresh_token = snapshot.get("refresh_token")

            if not token:
                return {
                    "ok": False,
                    "message": "El login web termino, pero SUNAT no devolvio un token code reutilizable.",
                }

            token_record = build_token_record(token, refresh_token, source="login")
            save_token_record(settings, token_record)
            log(f"Sesion guardada en: {settings.auth_state_path}")
            return {
                "ok": True,
                "token": token,
                "refresh_token": refresh_token,
                "login_success": True,
            }
        finally:
            browser.close()


def run() -> int:
    args = parse_args()

    try:
        result = perform_login(timeout_seconds=args.timeout_seconds, debug=args.debug)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(result)
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(run())

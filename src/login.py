from __future__ import annotations

import argparse
import sys
import time
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .config import load_settings
from .selectors import PASSWORD_SELECTORS, RUC_SELECTORS, SUBMIT_SELECTORS, USER_SELECTORS
from .utils import (
    ensure_parent_dir,
    first_visible_locator,
    first_visible_locator_in_frames,
    write_json,
    write_text,
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
        if "token" in key.lower() and token_value:
            results.append(token_value)
    return results


def build_auth_snapshot(page, context, settings) -> dict:
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
        if "token" in name.lower() or "auth" in name.lower():
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
            if "token" in key.lower() or "auth" in key.lower():
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

    unique_candidates = []
    seen = set()
    for candidate in token_candidates:
        if candidate not in seen:
            unique_candidates.append(candidate)
            seen.add(candidate)

    return {
        "login_detected": True,
        "captured_at_epoch": int(time.time()),
        "current_url": current_url,
        "url_contains_success_hint": settings.login_success_url_contains.lower()
        in current_url.lower(),
        "cookies": cookies,
        "cookie_token_candidates": cookie_candidates,
        "storage": storage,
        "storage_token_candidates": storage_candidates,
        "token_candidates": unique_candidates,
        "notes": [
            "Si token_candidates viene vacio, SUNAT probablemente solo dejo una sesion web y no expuso un access token en el navegador.",
            "El storage_state de Playwright sigue siendo util para reutilizar la sesion del portal.",
        ],
    }


def attempt_fill_login(page, settings) -> bool:
    filled_any = False

    if settings.ruc:
        ruc_input = first_visible_locator(page, RUC_SELECTORS) or first_visible_locator_in_frames(
            page, RUC_SELECTORS
        )
        if ruc_input:
            ruc_input.fill(settings.ruc)
            filled_any = True
            log("RUC completado automaticamente.")
        else:
            log("No se encontro un campo visible para RUC.")

    if settings.user:
        user_input = first_visible_locator(page, USER_SELECTORS) or first_visible_locator_in_frames(
            page, USER_SELECTORS
        )
        if user_input:
            user_input.fill(settings.user)
            filled_any = True
            log("Usuario completado automaticamente.")
        else:
            log("No se encontro un campo visible para usuario.")

    if settings.password:
        password_input = first_visible_locator(page, PASSWORD_SELECTORS) or first_visible_locator_in_frames(
            page, PASSWORD_SELECTORS
        )
        if password_input:
            password_input.fill(settings.password)
            filled_any = True
            log("Clave completada automaticamente.")
        else:
            log("No se encontro un campo visible para clave.")

    submit_button = first_visible_locator(page, SUBMIT_SELECTORS) or first_visible_locator_in_frames(
        page, SUBMIT_SELECTORS
    )
    if submit_button and filled_any:
        submit_button.click()
        log("Se hizo click en el boton de envio.")
    elif filled_any:
        log("Se llenaron campos, pero no se encontro un boton visible de envio.")

    return filled_any


def wait_for_login_success(page, settings, timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    success_hint = settings.login_success_url_contains.lower()

    log("Esperando confirmacion de login. Completa manualmente cualquier paso faltante en el navegador.")

    while time.time() < deadline:
        current_url = page.url
        if success_hint and success_hint in current_url.lower():
            log(f"Login detectado por URL: {current_url}")
            return True

        try:
            page_text = page.locator("body").inner_text(timeout=1000).lower()
        except Exception:
            page_text = ""

        if "menu sol" in page_text or "menú sol" in page_text or "bienvenido" in page_text:
            log("Login detectado por contenido visible.")
            return True

        time.sleep(1)

    return False


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

            if not success:
                log("No se detecto el login dentro del tiempo esperado.")
                return {
                    "ok": False,
                    "message": "No se detecto el login dentro del tiempo esperado.",
                    "storage_state_path": str(settings.auth_state_path),
                    "auth_snapshot_path": str(settings.auth_snapshot_path),
                }

            ensure_parent_dir(settings.auth_state_path)
            context.storage_state(path=str(settings.auth_state_path))

            snapshot = build_auth_snapshot(page, context, settings)
            write_json(settings.auth_snapshot_path, snapshot)

            log(f"Sesion guardada en: {settings.auth_state_path}")
            return {
                "ok": True,
                "message": "Login detectado y sesion guardada.",
                "storage_state_path": str(settings.auth_state_path),
                "auth_snapshot_path": str(settings.auth_snapshot_path),
                "token_candidates": snapshot["token_candidates"],
                "current_url": snapshot["current_url"],
                "notes": snapshot["notes"],
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

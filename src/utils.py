from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import Locator, Page


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _pick_existing(locator: Locator) -> Locator | None:
    try:
        if locator.count() == 0:
            return None
        candidate = locator.first
        try:
            if candidate.is_visible():
                return candidate
        except Exception:
            pass
        return candidate
    except Exception:
        return None


def first_visible_locator(page: Page, selectors: list[str]) -> Locator | None:
    for selector in selectors:
        locator = _pick_existing(page.locator(selector))
        if locator is not None:
            return locator
    return None


def first_visible_locator_in_frames(page: Page, selectors: list[str]) -> Locator | None:
    for frame in page.frames:
        for selector in selectors:
            locator = _pick_existing(frame.locator(selector))
            if locator is not None:
                return locator
    return None


def write_text(path: Path, content: str) -> None:
    ensure_parent_dir(path)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, data: dict) -> None:
    ensure_parent_dir(path)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))

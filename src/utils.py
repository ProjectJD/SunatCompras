from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import Locator, Page


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def first_visible_locator(page: Page, selectors: list[str]) -> Locator | None:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.is_visible(timeout=1500):
                return locator
        except Exception:
            continue
    return None


def first_visible_locator_in_frames(page: Page, selectors: list[str]) -> Locator | None:
    for frame in page.frames:
        for selector in selectors:
            locator = frame.locator(selector).first
            try:
                if locator.is_visible(timeout=1000):
                    return locator
            except Exception:
                continue
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

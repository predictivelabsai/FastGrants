"""Capture a headless tour of a running Fast* app into docs/demo/frames/.

Reusable across the Fast* FastHTML apps. Drives a real browser via Playwright
against a locally running server, logs in through the /login form (and, when the
app needs it, picks an RBAC role via POST_LOGIN_PATH), then walks a declarative
TOUR of (filename, path, wait_selector, full_page, post_action) tuples, saving
one PNG frame per screen. Feed the frames to build_demo_gif.sh.

Usage (server must already be running on BASE_URL):
    python scripts/capture_demo.py
    BASE_URL=http://localhost:5015 python scripts/capture_demo.py
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

log = logging.getLogger("capture")

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "docs" / "demo" / "frames"

BASE_URL = os.environ.get("BASE_URL", "http://localhost:5015")
EMAIL = os.environ.get("APP_EMAIL", "admin@fastgrants.example")
PASSWORD = os.environ.get("APP_PASSWORD", "FastGrants2026$")
# Some apps require an RBAC role pick after login — navigate here to set it.
POST_LOGIN_PATH = os.environ.get("POST_LOGIN_PATH", "")
VIEWPORT = {"width": 1400, "height": 900}


# (filename, path, wait_selector, full_page, post_action)
TOUR = [
    ("01-dashboard.png",         "/",               "text=Dashboard",     True,  "wait_charts"),
    ("02-calls.png",             "/calls",          "text=Calls",         True,  None),
    ("03-call-detail.png",       "/calls/1",        "text=budget",        True,  None),
    ("04-applications.png",      "/applications",   "text=Applications",  True,  None),
    ("05-application-detail.png","/applications/1", "text=Application",   True,  None),
    ("06-grants.png",            "/grants",         "text=Grants",        True,  None),
    ("07-grant-detail.png",      "/grants/1",       "text=milestone",     True,  None),
    ("08-reports.png",           "/reports",        "text=Reports",       True,  None),
    ("09-report-detail.png",     "/reports/1",      "text=Report",        True,  None),
    ("10-ai-assistant.png",      "/ai",             "text=AI Assistant",  True,  None),
]


def login(page) -> None:
    page.goto(BASE_URL + "/login", wait_until="networkidle", timeout=30_000)
    try:
        page.fill("input[name=email]", EMAIL)
        page.fill("input[name=password]", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle", timeout=15_000)
        log.info("logged in as %s", EMAIL)
    except Exception as e:
        log.warning("login step failed (already in / no form?): %s", e)
    if POST_LOGIN_PATH:
        try:
            page.goto(BASE_URL + POST_LOGIN_PATH, wait_until="networkidle", timeout=15_000)
            log.info("post-login: %s", POST_LOGIN_PATH)
        except Exception as e:
            log.warning("post-login step failed: %s", e)


def _post_action(page, action: str) -> None:
    if action == "wait_charts":
        time.sleep(3)  # let Plotly render
    time.sleep(0.4)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    FRAMES.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        page = ctx.new_page()

        login(page)

        for fname, path, wait_for, full_page, action in TOUR:
            url = BASE_URL + path
            log.info("→ %s", url)
            try:
                page.goto(url, wait_until="networkidle", timeout=30_000)
            except Exception as e:
                log.warning("goto failed %s: %s — retrying with 'load'", url, e)
                try:
                    page.goto(url, wait_until="load", timeout=30_000)
                except Exception as e2:
                    log.warning("goto failed again %s: %s — skipping", url, e2)
                    continue

            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=8_000)
                except Exception:
                    log.warning("selector %r didn't appear on %s", wait_for, path)

            if action:
                _post_action(page, action)

            out = FRAMES / fname
            try:
                page.screenshot(path=str(out), full_page=full_page)
                log.info("  saved %s", out.relative_to(ROOT))
            except Exception as e:
                log.warning("screenshot failed for %s: %s", path, e)

        browser.close()
    log.info("done — frames in %s", FRAMES)


if __name__ == "__main__":
    main()

"""Log in as each demo role and save README screenshots into docs/img/.

Usage (after `generate` and `build`):
    pip install -e ".[screenshots]"
    python -m playwright install chromium
    python scripts/take_screenshots.py

Starts its own Streamlit server on a spare port and stops exactly that process at the end.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "salesreport" / "dashboard" / "app.py"
OUT = ROOT / "docs" / "img"
PORT = 8599
URL = f"http://localhost:{PORT}"

log = logging.getLogger("screenshots")

SHOTS = [
    # (username, password, page, extra action, file name)
    ("regional", "demo-regional", "Overview", None, "role_regional_manager.png"),
    ("north.manager", "demo-north", "Leaderboard", None, "role_shop_manager.png"),
    ("northgate.employee", "demo-northgate", "Agent detail", None, "role_employee.png"),
    (
        "regional",
        "demo-regional",
        "How it evolved",
        "v3 - Prototype at scale",
        "how_it_evolved_v3.png",
    ),
    ("regional", "demo-regional", "How it evolved", None, "how_it_evolved_v4.png"),
]


def wait_for_server(timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{URL}/_stcore/health", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("streamlit server did not start")


def settle(page: Page, seconds: float = 2.5) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(int(seconds * 1000))


def login(page: Page, username: str, password: str) -> None:
    page.goto(URL)
    page.get_by_role("textbox", name="Username").fill(username)
    page.get_by_role("textbox", name="Password").fill(password)
    page.get_by_role("button", name="Sign in").click()
    page.locator(".page-header").first.wait_for(timeout=30000)
    settle(page)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    OUT.mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(APP),
            "--server.port",
            str(PORT),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log.info("started streamlit (pid %d)", server.pid)
    try:
        wait_for_server()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for username, password, page_name, action, file_name in SHOTS:
                context = browser.new_context(
                    viewport={"width": 1440, "height": 960}, device_scale_factor=1
                )
                page = context.new_page()
                login(page, username, password)
                sidebar = page.locator('[data-testid="stSidebar"]')
                sidebar.get_by_text(page_name, exact=True).click()
                settle(page)
                if action:
                    page.get_by_text(action, exact=True).click()
                    settle(page)
                page.screenshot(path=str(OUT / file_name))
                log.info("saved %s", file_name)
                context.close()
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
        log.info("stopped streamlit (pid %d)", server.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

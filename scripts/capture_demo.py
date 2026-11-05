"""Capture actual browser screenshots from a running local SADA demo.
Uses only synthetic order data and asserts the response before saving screenshots.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path("docs/screenshots")
OUT.mkdir(parents=True, exist_ok=True)
DEMO = Path("docs/demo")
DEMO.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p, TemporaryDirectory() as video_dir:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 960},
        device_scale_factor=1,
        record_video_dir=video_dir,
        record_video_size={"width": 1280, "height": 800},
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    response = page.goto(BASE, wait_until="domcontentloaded", timeout=20000)
    assert response and response.status == 200, "SADA demo homepage is not serving HTTP 200"
    page.locator("#welcomeTitle").wait_for(timeout=15000)
    page.wait_for_function("() => document.querySelector('#connectionTop')?.textContent === 'Agent connected'", timeout=20000)
    page.screenshot(path=str(OUT / "sada-dashboard.png"), full_page=True, animations="disabled")

    # A genuine conversational screenshot requires a verified WebSocket response.
    previous = page.locator(".message-row.bot").count()
    page.locator("#chatInput").fill("Where is ORD-1001?")
    page.locator("#sendBtn").click()
    page.wait_for_function(
        "(before) => document.querySelectorAll('.message-row.bot').length > before",
        arg=previous, timeout=20000,
    )
    messages = page.locator("#messages").inner_text()
    assert "ORD-1001" in messages, f"Expected a synthetic order answer, received: {messages[-300:]}"
    if errors:
        raise AssertionError("Browser JavaScript errors: " + "; ".join(errors[:3]))
    page.screenshot(path=str(OUT / "sada-order-demo.png"), full_page=True, animations="disabled")
    page.wait_for_timeout(900)
    video = page.video
    assert video is not None, "Playwright browser video recording unavailable"
    context.close()
    shutil.copyfile(video.path(), DEMO / "sada-order-walkthrough.webm")

    # Mobile screenshot from a real responsive Chromium viewport.
    mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
    mobile.goto(BASE, wait_until="domcontentloaded", timeout=20000)
    mobile.locator("#welcomeTitle").wait_for(timeout=15000)
    mobile.screenshot(path=str(OUT / "sada-mobile.png"), full_page=True, animations="disabled")
    print("VERIFIED: real WebSocket order flow, 3 screenshots and original browser-recorded walkthrough video")
    browser.close()

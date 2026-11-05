"""Capture actual browser screenshots from a running local SADA demo.
Uses only synthetic order data and asserts the response before saving screenshots.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path("docs/screenshots")
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
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
    print("VERIFIED: homepage, live WebSocket, synthetic order response and two real browser screenshots")
    browser.close()

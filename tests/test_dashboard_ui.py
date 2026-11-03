"""Cheap UI contract checks to protect IDs and security boundaries during design updates."""
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


class Markup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.controls = {}
        self.links = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
            if tag in {"button", "textarea", "select"}:
                self.controls[a["id"]] = (tag, a)
        if tag == "a":
            self.links.append(a)


def test_dashboard_preserves_voice_and_chat_bindings():
    html = (ROOT / "web/index.html").read_text()
    js = (ROOT / "web/app.js").read_text()
    parsed = Markup()
    parsed.feed(html)
    assert len(parsed.ids) == len(set(parsed.ids)), "Duplicate DOM IDs"
    for identifier in re.findall(r"\$\('([A-Za-z0-9]+)'\)", js):
        assert identifier in parsed.ids, f"Missing browser control {identifier}"
    for identifier in ("mobileMenuBtn", "sidebarBackdrop", "quickVoiceBtn",
                       "voicePanelBtn", "copyLinkBtn", "voiceCapability", "modelStatus"):
        assert identifier in parsed.ids
    assert parsed.controls["micBtn"][0] == "button"
    assert parsed.controls["voicePanelBtn"][0] == "button"
    assert 'value="cloud"' in html
    assert 'value="ar"' in html
    assert 'data-prompt="Where is my order ORD-1001?"' in html


def test_public_site_clearly_labeled_demo_and_no_secrets():
    html = (ROOT / "web/index.html").read_text()
    css = (ROOT / "web/style.css").read_text()
    assert "Public demo" in html
    assert "synthetic" in html.lower()
    assert "Do not enter private information" in html
    assert "GROQ_API_KEY" not in html and "GROQ_API_KEY" not in css
    assert "fonts.googleapis.com" not in css, "UI should not require external fonts"
    parsed = Markup()
    parsed.feed(html)
    for anchor in parsed.links:
        if anchor.get("target") == "_blank":
            assert "noopener" in anchor.get("rel", "")
    # The browser makes all service calls to same-origin FastAPI endpoints.
    assert 'src="/static/app.js"' in html

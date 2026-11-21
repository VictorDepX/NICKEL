"""Arquivos estáticos da UI: a aba Monitor é servida e referenciada sem CDN nem build."""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from nickel.app import STATIC_DIR, create_app
from nickel.skills import build_registry


@pytest.fixture
def client(services):
    app = create_app(services=services, registry=build_registry(), background=False)
    with TestClient(app) as test_client:
        yield test_client


def test_static_monitor_assets_are_served_and_referenced(client):
    for path in ("/static/monitor.js", "/static/monitor-core.js", "/static/monitor.css"):
        response = client.get(path)
        assert response.status_code == 200, path
    assert "javascript" in client.get("/static/monitor.js").headers["content-type"]

    html = client.get("/").text
    assert 'id="monitor"' in html
    assert '<script type="module" src="/static/monitor.js"></script>' in html
    assert 'href="/static/monitor.css"' in html
    assert "/static/monitor-core.js" in client.get("/static/monitor.js").text


def test_index_has_tabs_think_toggle_and_live_phase_label(client):
    html = client.get("/").text
    assert 'role="tablist"' in html
    assert ">Conversa<" in html and ">Monitor<" in html
    assert 'id="think"' in html and "Mostrar raciocínio" in html
    assert re.search(r'id="phase-label"[^>]*aria-live="polite"', html)
    assert 'id="reasoning-empty-text"' in html and 'id="reasoning-steps"' in html


def test_monitor_never_injects_html_and_uses_no_cdn():
    monitor = (STATIC_DIR / "monitor.js").read_text(encoding="utf-8")
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert forbidden not in monitor, forbidden
    assert "Baixar relatório" in monitor
    for text in ("Sem raciocínio expandido (think desligado)", "Aguardando o modelo…", "Nenhum turno ainda."):
        assert text in monitor, text
    for name in ("index.html", "monitor.js", "monitor.css", "app.js"):
        text = (STATIC_DIR / name).read_text(encoding="utf-8")
        assert not re.search(r"(src|href)=\"https?://", text), name
        assert "cdn" not in text.lower(), name


def test_monitor_css_respects_reduced_motion():
    css = (STATIC_DIR / "monitor.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in css


def test_app_sends_think_and_translates_voice_state():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 'think: $("think").checked' in app_js
    assert "think: true" not in app_js
    assert "localStorage" in app_js
    assert "transcrevendo" in app_js

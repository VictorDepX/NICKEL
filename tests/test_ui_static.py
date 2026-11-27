"""UI estática: o build do React (web/) é servido em `/` e em `/static/*` com revalidação."""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from nickel.app import create_app
from nickel.skills import build_registry


@pytest.fixture
def client(services):
    app = create_app(services=services, registry=build_registry(), background=False)
    with TestClient(app) as test_client:
        yield test_client


def test_index_is_the_react_build_and_assets_are_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    html = response.text
    assert '<div id="root">' in html
    script = re.search(r'<script type="module"[^>]* src="(/static/assets/[^"]+)"', html)
    assert script, "script do bundle ausente"
    asset = client.get(script.group(1))
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "no-cache"
    assert "javascript" in asset.headers["content-type"]


def test_index_references_only_local_assets(client):
    html = client.get("/").text
    assert not re.search(r"(src|href)=\"https?://", html)


def test_sphere_gif_is_served(client):
    response = client.get("/static/esfera.gif")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/gif"

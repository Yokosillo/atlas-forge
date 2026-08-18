"""Tests de integración para cache-busting en index.html y agent-pane.html
(T-FB021-US01-03)."""

import pytest
from starlette.testclient import TestClient

from brain.api.app import create_app


@pytest.fixture
def client():
    """Cliente HTTP para la app."""
    app = create_app()
    return TestClient(app)


def test_index_html_has_cache_bust_version_injected(client):
    """GET /ui/index.html inyecta un cache-bust version real."""
    response = client.get("/ui/index.html")

    assert response.status_code == 200
    html = response.text

    # Verifica que el placeholder se reemplazó
    assert "{{CACHE_BUST_VERSION}}" not in html

    # Verifica que todas las referencias tienen un version tag
    assert "app.js?v=" in html
    assert "style.css?v=" in html
    assert "backend-client.js?v=" in html
    assert "reconnecting-websocket.js?v=" in html

    # Extrae una versión (todas deben ser iguales)
    import re
    versions = re.findall(r'\?v=([a-z0-9]+)', html)
    assert len(versions) >= 4
    # Todas las versiones deben ser iguales (mismo timestamp + hash combinado)
    assert all(v == versions[0] for v in versions)


def test_root_ui_serves_index_html_with_cache_bust_injected(client):
    """GET /ui/ (raíz, la ruta que abre el navegador) también inyecta el
    cache-bust version — Starlette pasa `path=""` para el directorio y antes
    de T-FB021-US01-03-fix el placeholder llegaba literal."""
    response = client.get("/ui/")

    assert response.status_code == 200
    html = response.text

    assert "{{CACHE_BUST_VERSION}}" not in html
    assert "app.js?v=" in html
    assert "backend-client.js?v=" in html


def test_agent_pane_html_has_cache_bust_version_injected(client):
    """GET /ui/agent-pane.html inyecta un cache-bust version real."""
    response = client.get("/ui/agent-pane.html")

    assert response.status_code == 200
    html = response.text

    # Verifica que el placeholder se reemplazó
    assert "{{CACHE_BUST_VERSION}}" not in html

    # Verifica que la referencia de style.css tiene version tag
    assert "style.css?v=" in html

    # Extrae la versión
    import re
    versions = re.findall(r'\?v=([a-z0-9]+)', html)
    assert len(versions) >= 1
    # La versión debe tener formato YYYYMMDD + 6 chars hex
    v = versions[0]
    assert len(v) == 14
    assert v[:8].isdigit()


def test_cache_bust_version_format_is_valid(client):
    """El cache-bust version tiene formato YYYYMMDD + 6 chars hex."""
    response = client.get("/ui/index.html")
    assert response.status_code == 200

    import re
    versions = re.findall(r'\?v=([a-z0-9]+)', response.text)
    assert len(versions) > 0

    for v in versions:
        # YYYYMMDD (8 dígitos) + 6 caracteres hex
        assert len(v) == 14
        assert v[:8].isdigit()
        assert all(c in "0123456789abcdef" for c in v[8:])


def test_static_files_without_placeholders_are_unchanged(client):
    """GET /ui/app.js y otros assets se sirven sin modificación."""
    response = client.get("/ui/app.js")

    assert response.status_code == 200
    # app.js no debe contener el placeholder
    assert "{{CACHE_BUST_VERSION}}" not in response.text
    # Debe ser JavaScript válido (contiene 'function' o 'var' típicamente)
    assert len(response.text) > 100

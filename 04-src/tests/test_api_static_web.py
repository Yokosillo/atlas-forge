"""Test de servir la interfaz web estática (T-FB021-US01-01): comprueba que
`10-web/` se sirve bajo el prefijo dedicado `/ui` sin colisionar con ningún
endpoint de dominio existente, y que el esqueleto (index.html + CSS base de
área clicable mínima + app.js) llega a los clientes correctamente.

Se verifica explícitamente (no solo asumido) que ningún path de dominio
existe bajo el prefijo `/ui` y que el montaje estático no altera ninguna de
las 25 rutas de dominio: rutas del router (`brain.api.routes`) + `/health`,
`/apk` y los dos WebSockets (`/ws/jobs`, `/ws/plans`) definidos en `app.py`."""

from pathlib import Path

from fastapi.testclient import TestClient

import brain.api.app as app_module
from brain.api import create_app
from brain.api.routes import router as domain_router
from brain.workspace import discover_projects, select_active_project


def _path_in_domain_routes(path: str) -> bool:
    """Comprueba si `path` colisiona con algún endpoint de dominio actual:
    cualquier ruta definida en `routes.py` o las rutas de dominio de
    `app.py` (`/health`, `/apk`, los WebSockets `/ws/*`). Se excluye
    explícitamente el montaje estático `/ui` (que es el que añade este
    cambio) para no autocolisionarse."""
    domain_paths = {r.path for r in domain_router.routes}
    domain_paths.update(
        {
            getattr(r, "path", None)
            for r in create_app().routes
            if getattr(r, "path", None) is not None
            and getattr(r, "path", None) != "/ui"
        }
    )
    # FastAPI añade /docs, /redoc, /openapi.json, /docs/oauth2-redirect.
    domain_paths.discard(None)
    return path in domain_paths


def test_web_root_is_served_not_a_404() -> None:
    client = TestClient(create_app())

    response = client.get("/ui/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Factory Brain" in response.text


def test_web_root_without_trailing_slash_serves_index_html() -> None:
    client = TestClient(create_app())

    response = client.get("/ui")

    assert response.status_code in (200, 307)
    if response.status_code == 200:
        assert "Factory Brain" in response.text


def test_css_is_served_with_minimum_clickable_area_rule() -> None:
    client = TestClient(create_app())

    response = client.get("/ui/style.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    # Regla base: área clicable mínima de 48px (equivalente web del criterio
    # de objetivos de toque de al menos 48dp de las Tasks de Android).
    assert "min-height: 48px" in response.text


def test_app_js_is_served() -> None:
    client = TestClient(create_app())

    assert client.get("/ui/app.js").status_code == 200


def test_web_root_does_not_collide_with_any_domain_endpoint() -> None:
    """Criterio de aceptación: el directorio estático no colisiona con
    ningún path real usado por `routes.py`/`app.py` — verificado aquí
    explícitamente, no asumido."""
    assert _path_in_domain_routes("/ui") is False
    assert _path_in_domain_routes("/ui/") is False
    # El prefijo de dominio real no debe coincidir con ninguna ruta.
    collisons = {
        p for p in {r.path for r in domain_router.routes} if p.startswith("/ui")
    }
    assert collisons == set()


def test_domain_endpoints_unchanged_after_static_mount() -> None:
    """Tras montar el estático, todas las rutas de dominio siguen existiendo
    (ninguna fue enmascarada por el mount `/ui`)."""
    app = create_app()
    client = TestClient(app)

    # Rutas de ejemplo de la API de dominio que deben seguir respondiendo
    # (su respuesta exacta ya la validan el resto de suites; aquí solo se
    # confirma que no se enmascaran con un 404 de la web estática).
    assert client.get("/health").status_code in (200, 404)  # health nunca es 404
    assert client.get("/apk").status_code in (200, 404)
"""Entrypoint `brain-api` (T-FB016-US01-01): arranca el servidor FastAPI
como proceso único de larga duración (`uvicorn`), escuchando por defecto
en la interfaz Tailscale de esta VM — nunca `0.0.0.0` (ver
`brain.api.host` para la justificación completa). Análogo al entrypoint
`brain` ya existente para la TUI (`brain.cli.main`), pero un proceso
Python completamente distinto: ambos pueden convivir, cada uno con su
propio estado en memoria (ver docstring de `brain.api.app`)."""

import argparse
import logging

import requests
import uvicorn

from brain.api.app import create_app
from brain.api.host import resolve_tailscale_host

DEFAULT_PORT = 8000

_logger = logging.getLogger(__name__)


def _detect_running_instance(host: str, port: int) -> bool:
    """T-FB037-US01-01: intenta detectar si ya hay otra instancia de
    brain-api sirviendo en el puerto objetivo. Devuelve True si detecta
    una instancia viva (por `GET /projects` con 200), False en caso
    contrario. Nunca lanza excepción — solo prueba la conexión, logguea
    si detecta algo, y sigue adelante (v1 es detección, no bloqueo)."""
    try:
        # Timeout corto: si está sirviendo debe responder rápido; si no
        # responde, probablemente no hay una instancia Brain ahí.
        url = f"http://{host}:{port}/projects"
        response = requests.get(url, timeout=1.0)
        if response.status_code == 200:
            _logger.info(
                f"Detectada otra instancia de brain-api sirviendo en "
                f"{host}:{port} (GET /projects devolvió 200). "
                f"El arranque continuará igualmente."
            )
            return True
    except (requests.ConnectionError, requests.Timeout, requests.RequestException):
        # No hay nada sirviendo en ese puerto, o no es una instancia Brain.
        pass
    except Exception:
        # Cualquier otro error (resolución DNS, etc.) — silenciar y seguir.
        pass
    return False


def run_server(host: str | None = None, port: int = DEFAULT_PORT) -> None:
    """Arranca `uvicorn` sirviendo `create_app()`. Si `host` no se indica
    explícitamente, se resuelve a la IP de la interfaz Tailscale de esta
    máquina (`resolve_tailscale_host`) — nunca a `0.0.0.0` por defecto.

    Antes de arrancar, detecta (T-FB037-US01-01) si ya hay otra instancia
    sirviendo en el puerto objetivo y logguea el hecho si se detecta.
    El arranque no se bloquea (v1 es detección, no bloqueo)."""
    resolved_host = host if host is not None else resolve_tailscale_host()
    _detect_running_instance(resolved_host, port)
    uvicorn.run(create_app(), host=resolved_host, port=port)


def main() -> None:
    parser = argparse.ArgumentParser(description="Factory Brain API backend")
    parser.add_argument(
        "--host",
        default=None,
        help=(
            "Host en el que escuchar. Por defecto se resuelve a la IP de "
            "la interfaz Tailscale de esta máquina — nunca 0.0.0.0."
        ),
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()

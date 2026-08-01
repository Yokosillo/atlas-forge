"""Entrypoint `brain-api` (T-FB016-US01-01): arranca el servidor FastAPI
como proceso único de larga duración (`uvicorn`), escuchando por defecto
en la interfaz Tailscale de esta VM — nunca `0.0.0.0` (ver
`brain.api.host` para la justificación completa). Análogo al entrypoint
`brain` ya existente para la TUI (`brain.cli.main`), pero un proceso
Python completamente distinto: ambos pueden convivir, cada uno con su
propio estado en memoria (ver docstring de `brain.api.app`)."""

import argparse

import uvicorn

from brain.api.app import create_app
from brain.api.host import resolve_tailscale_host

DEFAULT_PORT = 8000


def run_server(host: str | None = None, port: int = DEFAULT_PORT) -> None:
    """Arranca `uvicorn` sirviendo `create_app()`. Si `host` no se indica
    explícitamente, se resuelve a la IP de la interfaz Tailscale de esta
    máquina (`resolve_tailscale_host`) — nunca a `0.0.0.0` por defecto."""
    resolved_host = host if host is not None else resolve_tailscale_host()
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

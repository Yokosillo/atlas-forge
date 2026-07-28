"""Entrypoint `brain` (T-FB002-US02-05): arranca la TUI real, reutilizando
`brain.tui.app.run` sin reimplementar el arranque. El comando CLI suelto
`brain-launch-agent` (T-FB002-US01-04, con `input()` de terminal) se
retiró en esta misma Task — su funcionalidad vive ahora en la pantalla
Agentes de la TUI unificada (T-FB002-US02-04), alcanzable navegando
desde este mismo entrypoint."""

from brain.tui.app import run


def main() -> None:
    run()


if __name__ == "__main__":
    main()

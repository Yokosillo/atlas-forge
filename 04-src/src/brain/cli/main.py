"""Entrypoint `brain` (T-FB002-US02-05): arranca la TUI real, reutilizando
`brain.tui.app.run` sin reimplementar el arranque. El comando CLI suelto
`brain-launch-agent` (T-FB002-US01-04, con `input()` de terminal) se
retiró en esta misma Task — su funcionalidad vive ahora en la pantalla
Agentes de la TUI unificada (T-FB002-US02-04), alcanzable navegando
desde este mismo entrypoint.

Desde T-FB018-US02-02 el entrypoint admite también el subcomando
`brain backlog-status <backlog_path> [--json]`: se delega en
`brain.cli.backlog_status.run_backlog_status` (que comparte el cálculo con
la entrada `backlog_status` del catálogo de scripts genéricos) y solo si no
hay subcomando se arranca la TUI.

Desde T-FB018-US02-03 se admite además el subcomando
`brain scribe resumir-backlog` (capa OPTIONAL de síntesis en prosa sobre el
JSON de `backlog-status`, vía Scribe): se delega en
`brain.cli.scribe_resumir_backlog.run_resumir_backlog`. Si Scribe/Ollama no
está disponible, ese subcomando lo degrada explícitamente — `brain
backlog-status` nunca depende de él."""

import sys

from brain.cli.backlog_status import run_backlog_status
from brain.cli.scribe_resumir_backlog import run_resumir_backlog
from brain.tui.app import run


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "backlog-status":
        return run_backlog_status(sys.argv[2:])
    if len(sys.argv) > 2 and sys.argv[1] == "scribe" and sys.argv[2] == "resumir-backlog":
        return run_resumir_backlog(sys.argv[3:])
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

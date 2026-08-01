from dataclasses import dataclass


@dataclass(frozen=True)
class ScriptEntry:
    """Un script particular declarado por el proyecto activo en su
    manifiesto (T-FB001-US03-01) — `id` es el identificador estable por el
    que `run_project_script` (T-FB001-US03-02) lo localizará para
    ejecutarlo, `command` es la línea de comando a ejecutar tal cual
    (mismo criterio de "string de shell, no lista de argumentos" ya usado
    en `Runtime.command`/`run_command`, `brain.tmux.manager`)."""

    id: str
    name: str
    command: str
    description: str = ""

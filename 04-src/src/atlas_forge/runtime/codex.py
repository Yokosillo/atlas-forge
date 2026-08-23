import shlex

from atlas_forge.models import Runtime

# Configuración por defecto de Codex como Runtime (T-AF024-US11-13,
# 2026-08-17, ampliación de alcance explícita del usuario — Codex estaba
# fuera del roadmap v1 original, ver nota histórica en `.atlas-forge/
# models.yml`). El comando real de la CLI no se ejecuta en los tests de
# esta Task (mismo patrón ya usado para Claude Code/OpenCode): se
# verifica el mecanismo de tmux con un comando de prueba inocuo.
DEFAULT_CODEX_COMMAND = "codex"

# Flags de máxima autonomía/mínima fricción, equivalentes funcionales a
# `--dangerously-skip-permissions` (Claude Code) / `--auto` (OpenCode) —
# investigado explícitamente antes de implementar (`codex --help` en esta
# VM, binario real instalado, no documentación externa):
#   -a never          → nunca pide aprobación humana antes de ejecutar un
#                        comando (equivalente a "never ask for approval").
#   -s workspace-write → sandbox de escritura acotado al workspace, NO
#                        `danger-full-access` (ese es el equivalente real
#                        a un bypass total, pero el propio --help lo
#                        describe como parte de un flag separado
#                        `--dangerously-bypass-approvals-and-sandbox`
#                        marcado "EXTREMELY DANGEROUS" — no se usa aquí,
#                        mismo criterio de prudencia que ya aplicó
#                        OpenCode al preferir `--auto` sobre un bypass
#                        total inexistente).
DEFAULT_CODEX_ARGS: list[str] = ["-a", "never", "-s", "workspace-write"]


def register_codex_runtime(runtime_id: str = "codex", model: str | None = None) -> Runtime:
    """Registra Codex como Runtime disponible, con su configuración
    mínima por defecto, incluyendo los flags de autonomía por defecto.

    Si se indica `model` (slug del catálogo, p. ej. "gpt-5.6-terra"), se
    añade `--model <model>` a los `args` construidos — mismo patrón que
    `register_opencode_runtime`/`register_claude_code_runtime`. Sin
    `model`, arranca con el modelo por defecto de la CLI.
    """
    args = list(DEFAULT_CODEX_ARGS)
    if model is not None:
        args += ["--model", model]

    return Runtime(
        id=runtime_id,
        name="Codex",
        type="codex",
        command=DEFAULT_CODEX_COMMAND,
        args=args,
    )


def build_prompt_args(prompt: str) -> list[str]:
    """Construye los argumentos adicionales para arrancar Codex con
    `prompt` ya cargado como primer mensaje de la sesión interactiva.

    Verificado directamente contra `codex --help` en esta VM: `Usage:
    codex [OPTIONS] [PROMPT]` — el prompt es un argumento posicional
    (`[PROMPT]  Optional user prompt to start the session`), mismo patrón
    que Claude Code (`build_prompt_args` de `claude_code.py`)."""
    return [shlex.quote(prompt)]

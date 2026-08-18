import shlex

from brain.models import Runtime

# Configuración por defecto de Claude Code como Runtime (T-FB004-US01-02).
# El comando real de la CLI no se ejecuta en los tests de esta Task (ver
# test_claude_code_runtime.py): se verifica el mecanismo de tmux con un
# comando de prueba inocuo, evitando lanzar el binario `claude` real dentro
# de sesiones tmux de prueba — este mismo entorno de trabajo ya usa
# sesiones tmux reales con `claude` para el ciclo worker/crítico.
DEFAULT_CLAUDE_CODE_COMMAND = "claude"

# Flag de máxima autonomía/mínima fricción (T-FB002-US01-01): evita que el
# agente quede bloqueado pidiendo confirmación de cada acción. Mismo
# criterio ya en uso en la sesión tmux real `claude-factory-brain` de este
# proyecto (verificado con `ps aux`: el comando real es
# `claude --remote-control --dangerously-skip-permissions`). No se incluye
# `--remote-control` aquí: es específico de esa sesión de trabajo concreta
# (worker/crítico), no un requisito general de todo Runtime Claude Code
# lanzado por Factory Brain.
DEFAULT_CLAUDE_CODE_ARGS: list[str] = ["--dangerously-skip-permissions"]


def register_claude_code_runtime(
    runtime_id: str = "claude-code", model: str | None = None
) -> Runtime:
    """Registra Claude Code como Runtime disponible, con su configuración
    mínima por defecto, incluyendo la flag de autonomía por defecto.

    Corrección T-FB024-US11-13 (2026-08-17): la premisa original ("Claude
    Code no expone selección de modelo por flag") estaba desactualizada —
    verificado directamente contra `claude --help` en esta VM: SÍ existe
    `--model <model>` como flag real de arranque. Si se indica `model`
    (alias corto: "sonnet"/"opus"/"haiku", o el id completo), se añade
    `--model <model>` a los `args` construidos, mismo patrón que
    `register_opencode_runtime`. Sin `model`, el comportamiento es el
    mismo que antes (solo la flag de autonomía).
    """
    args = list(DEFAULT_CLAUDE_CODE_ARGS)
    if model is not None:
        args += ["--model", model]

    return Runtime(
        id=runtime_id,
        name="Claude Code",
        type="claude-code",
        command=DEFAULT_CLAUDE_CODE_COMMAND,
        args=args,
    )


def build_prompt_args(prompt: str) -> list[str]:
    """Construye los argumentos adicionales para arrancar Claude Code con
    `prompt` ya cargado como primer mensaje de la sesión interactiva
    (T-FB005-US01-03).

    Verificado directamente contra `claude --help` en esta VM (versión real
    instalada, no documentación externa): `Usage: claude [options]
    [command] [prompt]` — el prompt es un **argumento posicional**, no un
    flag. En modo interactivo (sin `-p`/`--print`, que fuerza salida no
    interactiva y no es lo que se quiere aquí), arrancar con ese argumento
    ya presente carga el prompt en la sesión sin necesidad de teclearlo
    después — se prefiere sobre teclear tras un delay (criterio de
    aceptación explícito de la Task: más robusto, no depende de adivinar
    cuánto tarda la CLI en estar lista para aceptar input).

    `shlex.quote` evita que el propio contenido del prompt (puede incluir
    comillas, saltos de línea, etc.) rompa el comando de shell construido
    en `start_runtime` — el prompt viaja como un único argumento posicional
    tal cual lo vería el usuario, no se interpreta como shell."""
    return [shlex.quote(prompt)]

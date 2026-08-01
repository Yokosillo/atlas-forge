import shlex

from brain.models import Runtime

# Configuración por defecto de OpenCode como Runtime (T-FB004-US02-01).
# El comando real de la CLI no se ejecuta en los tests de esta Task (ver
# test_opencode_runtime.py): se verifica el mecanismo de tmux con un
# comando de prueba inocuo, evitando lanzar el binario `opencode` real
# dentro de sesiones tmux de prueba (misma precaución aplicada a Claude
# Code en T-FB004-US01-02).
DEFAULT_OPENCODE_COMMAND = "opencode"

# Flag de máxima autonomía/mínima fricción (T-FB002-US01-01), equivalente
# funcional a `--dangerously-skip-permissions` de Claude Code, pero NO el
# mismo nombre — investigado explícitamente antes de implementar (no se
# asumió el mismo flag): la documentación oficial de OpenCode
# (https://opencode.ai/docs/permissions/, verificado en julio 2026) expone
# `--auto` como el mecanismo para aprobar automáticamente solicitudes de
# permiso que de otro modo pedirían confirmación. A diferencia de
# `--dangerously-skip-permissions`, `--auto` respeta reglas "deny"
# explícitas ya configuradas — no es un bypass total, pero es el
# mecanismo de autonomía real que OpenCode expone hoy (no existe un
# `--yolo` ni `--dangerously-skip-permissions` real en OpenCode: son
# peticiones de feature históricas sin implementar, según la
# investigación realizada para esta Task).
DEFAULT_OPENCODE_AUTONOMY_FLAG = "--auto"
DEFAULT_OPENCODE_ARGS: list[str] = [DEFAULT_OPENCODE_AUTONOMY_FLAG]


def register_opencode_runtime(
    runtime_id: str = "opencode", model: str | None = None
) -> Runtime:
    """Registra OpenCode como Runtime disponible, con su configuración
    mínima por defecto, incluyendo la flag de autonomía por defecto.

    Si se indica `model` (formato `provider/model`, p. ej.
    `"deepseek/deepseek-chat"`), se añade `--model <model>` a los `args`
    construidos. Sin `model`, el comportamiento es el mismo que antes de
    esta Task (solo la flag de autonomía).
    """
    args = list(DEFAULT_OPENCODE_ARGS)
    if model is not None:
        args += ["--model", model]

    return Runtime(
        id=runtime_id,
        name="OpenCode",
        type="opencode",
        command=DEFAULT_OPENCODE_COMMAND,
        args=args,
    )


def build_prompt_args(prompt: str) -> list[str]:
    """Construye los argumentos adicionales para arrancar OpenCode con
    `prompt` ya cargado como primer mensaje de la sesión interactiva
    (T-FB005-US01-03).

    Verificado directamente contra `opencode --help` en esta VM (binario
    real instalado, no documentación externa): el comando por defecto
    (`opencode [project]`, modo TUI interactivo — no `opencode run
    [message..]`, que es un subcomando distinto y no interactivo) expone
    un flag explícito `--prompt <string>` ("prompt to use"). Se prefiere
    sobre teclear el prompt tras un delay (criterio de aceptación
    explícito de la Task), mismo criterio ya aplicado a Claude Code."""
    return ["--prompt", shlex.quote(prompt)]

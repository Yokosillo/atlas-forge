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


def register_claude_code_runtime(runtime_id: str = "claude-code") -> Runtime:
    """Registra Claude Code como Runtime disponible, con su configuración
    mínima por defecto, incluyendo la flag de autonomía por defecto.

    Claude Code no expone selección de modelo por flag de la misma forma
    que OpenCode (ver `01-documentacion/` y `US-FB002-01`) — esta función
    no acepta parámetro de modelo, para no introducir un parámetro sin
    efecto real.
    """
    return Runtime(
        id=runtime_id,
        name="Claude Code",
        type="claude-code",
        command=DEFAULT_CLAUDE_CODE_COMMAND,
        args=list(DEFAULT_CLAUDE_CODE_ARGS),
    )

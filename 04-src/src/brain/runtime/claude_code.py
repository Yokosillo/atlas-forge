from brain.models import Runtime

# Configuración por defecto de Claude Code como Runtime (T-FB004-US01-02).
# El comando real de la CLI no se ejecuta en los tests de esta Task (ver
# test_claude_code_runtime.py): se verifica el mecanismo de tmux con un
# comando de prueba inocuo, evitando lanzar el binario `claude` real dentro
# de sesiones tmux de prueba — este mismo entorno de trabajo ya usa
# sesiones tmux reales con `claude` para el ciclo worker/crítico.
DEFAULT_CLAUDE_CODE_COMMAND = "claude"
DEFAULT_CLAUDE_CODE_ARGS: list[str] = []


def register_claude_code_runtime(runtime_id: str = "claude-code") -> Runtime:
    """Registra Claude Code como Runtime disponible, con su configuración
    mínima por defecto."""
    return Runtime(
        id=runtime_id,
        name="Claude Code",
        type="claude-code",
        command=DEFAULT_CLAUDE_CODE_COMMAND,
        args=list(DEFAULT_CLAUDE_CODE_ARGS),
    )

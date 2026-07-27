from brain.models import Runtime

# Configuración por defecto de OpenCode como Runtime (T-FB004-US02-01).
# El comando real de la CLI no se ejecuta en los tests de esta Task (ver
# test_opencode_runtime.py): se verifica el mecanismo de tmux con un
# comando de prueba inocuo, evitando lanzar el binario `opencode` real
# dentro de sesiones tmux de prueba (misma precaución aplicada a Claude
# Code en T-FB004-US01-02).
DEFAULT_OPENCODE_COMMAND = "opencode"
DEFAULT_OPENCODE_ARGS: list[str] = []


def register_opencode_runtime(runtime_id: str = "opencode") -> Runtime:
    """Registra OpenCode como Runtime disponible, con su configuración
    mínima por defecto."""
    return Runtime(
        id=runtime_id,
        name="OpenCode",
        type="opencode",
        command=DEFAULT_OPENCODE_COMMAND,
        args=list(DEFAULT_OPENCODE_ARGS),
    )

from dataclasses import dataclass


@dataclass(frozen=True)
class ScriptRunResult:
    """Resultado de ejecutar un `ScriptEntry` catalogado
    (`run_project_script`, T-AF001-US03-02).

    `success` es explícito (no se infiere de `exit_code == 0` en cada
    llamador) para cubrir también el caso de que el script no llegara a
    ejecutarse (`script_id` desconocido, comando inexistente, timeout) —
    ahí `exit_code` es `None`, no `0` ni un valor inventado que sugeriría
    una ejecución real que no ocurrió."""

    success: bool
    exit_code: int | None
    stdout: str
    stderr: str
    error_message: str | None = None

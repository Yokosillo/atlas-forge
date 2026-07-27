from pathlib import Path

from brain.core.session_lifecycle import activate, close
from brain.models import DevelopmentSession
from brain.workspace.startup import ProjectRecovered, StartupOutcome, resolve_startup_project


class SessionAlreadyActiveError(RuntimeError):
    """Ya existe una sesión de desarrollo activa en esta ejecución."""


class _SessionRegistry:
    """Único punto de acceso a la sesión de desarrollo de la ejecución
    actual del proceso. Encapsula el estado en vez de exponer una variable
    global implícita, para que crear una segunda sesión mientras hay una
    `active` sea un error explícito y no una sustitución silenciosa."""

    def __init__(self) -> None:
        self._current_session: DevelopmentSession | None = None

    def start_session(self, project_id: str) -> DevelopmentSession:
        if (
            self._current_session is not None
            and self._current_session.status == "active"
        ):
            raise SessionAlreadyActiveError(
                "Ya existe una sesión de desarrollo activa "
                f"(id='{self._current_session.id}'). No se puede iniciar otra "
                "sin cerrar antes la actual."
            )

        session = DevelopmentSession(id=f"session-{project_id}", project_id=project_id)
        activate(session)
        self._current_session = session
        return session

    def get_current_session(self) -> DevelopmentSession | None:
        return self._current_session

    def shutdown_session(self) -> None:
        if self._current_session is None:
            return
        if self._current_session.status == "active":
            close(self._current_session)


_registry = _SessionRegistry()


def resolve_startup_session(
    workspace_root: Path | None = None, state_dir: Path | None = None
) -> DevelopmentSession | None:
    """Arranca la sesión de desarrollo de esta ejecución.

    Si hay un proyecto activo válido (T-FB001-US01-04), crea la sesión,
    la transiciona a `active`, y la devuelve. Si no hay proyecto activo
    (primera ejecución, o selección previa inválida), no crea ninguna
    sesión — el flujo de selección/reselección de proyecto (FB-001) debe
    completarse primero — y devuelve `None`.
    """
    outcome: StartupOutcome = resolve_startup_project(
        workspace_root=workspace_root, state_dir=state_dir
    )

    if not isinstance(outcome, ProjectRecovered):
        return None

    return _registry.start_session(outcome.project.id)


def get_current_session() -> DevelopmentSession | None:
    """Consulta la sesión de desarrollo activa de esta ejecución, o `None`
    si todavía no se ha arrancado ninguna."""
    return _registry.get_current_session()


def shutdown_current_session() -> None:
    """Cierra la sesión de desarrollo activa de esta ejecución (salida
    normal del proceso). No hace nada si no hay ninguna sesión."""
    _registry.shutdown_session()


def _reset_registry_for_tests() -> None:
    """Reinicia el registro interno. Uso exclusivo de la suite de tests,
    para que cada test parta de un estado limpio sin depender del orden
    de ejecución de otros tests."""
    global _registry
    _registry = _SessionRegistry()

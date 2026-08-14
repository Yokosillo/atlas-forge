from pathlib import Path

from brain.core.session_lifecycle import activate, close
from brain.models import DevelopmentSession
from brain.workspace.startup import ProjectRecovered, StartupOutcome, resolve_startup_project


class SessionAlreadyActiveError(RuntimeError):
    """Ya existe una sesión de desarrollo activa en esta ejecución."""


class _SessionRegistry:
    """Registro de las sesiones de desarrollo vivas de esta ejecución del
    proceso, una por `project_id` como máximo (FB-029), más un puntero de
    foco: el `project_id` sobre el que operan los endpoints que hoy asumen
    "la sesión actual" (`get_current_session`). Cambiar el foco no afecta a
    las sesiones de otros proyectos — siguen vivas y alcanzables en cuanto
    su proyecto recupera el foco."""

    def __init__(self) -> None:
        self._sessions: dict[str, DevelopmentSession] = {}
        self._focused_project_id: str | None = None

    def start_session(self, project_id: str) -> DevelopmentSession:
        existing = self._sessions.get(project_id)
        if existing is not None and existing.status == "active":
            self._focused_project_id = project_id
            return existing

        session = DevelopmentSession(id=f"session-{project_id}", project_id=project_id)
        activate(session)
        self._sessions[project_id] = session
        self._focused_project_id = project_id
        return session

    def get_current_session(self) -> DevelopmentSession | None:
        if self._focused_project_id is None:
            return None
        return self._sessions.get(self._focused_project_id)

    def shutdown_session(self) -> None:
        session = self.get_current_session()
        if session is None:
            return
        if session.status == "active":
            close(session)


_registry = _SessionRegistry()


def resolve_startup_session(
    workspace_root: Path | None = None, state_dir: Path | None = None
) -> DevelopmentSession | None:
    """Arranca la sesión de desarrollo de esta ejecución.

    Si hay un proyecto activo válido (T-FB001-US01-04), crea la sesión (o
    reutiliza la que ya estuviera viva para ese `project_id`, FB-029),
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


def focus_project_session(project_id: str) -> DevelopmentSession:
    """Da el foco a `project_id`: si ya tiene una sesión viva la reutiliza
    tal cual (mismos `session.id`/`session.agents`, sin relanzar nada); si
    no, la crea igual que `resolve_startup_session` (FB-029). Pensado para
    `POST /project` — sustituye a detener la sesión anterior."""
    return _registry.start_session(project_id)


def get_current_session() -> DevelopmentSession | None:
    """Consulta la sesión de desarrollo del proyecto con foco, o `None`
    si todavía no se ha arrancado/enfocado ninguna."""
    return _registry.get_current_session()


def shutdown_current_session() -> None:
    """Cierra la sesión de desarrollo del proyecto con foco (salida
    normal del proceso). No hace nada si no hay ninguna sesión con foco."""
    _registry.shutdown_session()


def _reset_registry_for_tests() -> None:
    """Reinicia el registro interno. Uso exclusivo de la suite de tests,
    para que cada test parta de un estado limpio sin depender del orden
    de ejecución de otros tests."""
    global _registry
    _registry = _SessionRegistry()

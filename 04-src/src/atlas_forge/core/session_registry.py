from pathlib import Path

from atlas_forge.core.session_lifecycle import activate, close
from atlas_forge.core.session_recovery import (
    build_session_snapshot,
    deserialize_snapshot,
    is_recoverable,
    serialize_snapshot,
)
from atlas_forge.models import DevelopmentSession
from atlas_forge.storage.session_snapshot_store import (
    load_session_snapshot,
    save_session_snapshot,
)
from atlas_forge.workspace.startup import ProjectRecovered, StartupOutcome, resolve_startup_project


class SessionAlreadyActiveError(RuntimeError):
    """Ya existe una sesión de desarrollo activa en esta ejecución."""


class _SessionRegistry:
    """Registro de las sesiones de desarrollo vivas de esta ejecución del
    proceso, una por `project_id` como máximo (AF-029), más un puntero de
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

        # T-AF003-US02-02: antes de crear una sesión "de cero", se intenta
        # recuperar la sesión persistida del proyecto (snapshot RECUPERABLE
        # guardado al cerrar/reabrir Atlas Forge). Reutiliza la lógica de
        # dominio (`deserialize_snapshot` + `is_recoverable` +
        # `record_activity`) — esta capa solo decide cuándo invocarla.
        recovered = self._recover_session(project_id)
        if recovered is not None:
            self._sessions[project_id] = recovered
            self._focused_project_id = project_id
            return recovered

        session = DevelopmentSession(id=f"session-{project_id}", project_id=project_id)
        activate(session)
        self._sessions[project_id] = session
        self._focused_project_id = project_id
        # T-AF003-US02-02 (carga/persistencia): en cuanto la sesión queda
        # activa, se persiste su snapshot recuperable — así la próxima vez
        # que se abra Atlas Forge sobre el mismo proyecto, `_recover_session`
        # la encuentra. Best-effort: un fallo de I/O no bloquea el arranque.
        self._persist_snapshot(project_id, session)
        return session

    def _recover_session(self, project_id: str) -> DevelopmentSession | None:
        """Recupera la sesión persistida de `project_id` si su snapshot
        guardado es recuperable. Conecta el módulo de dominio al flujo de
        arranque: la reconstrucción de la sesión NO duplica la lógica de
        negocio (decisión de recuperabilidad = `is_recoverable`), solo la
        invoca y registra el evento en el historial persistido."""
        data = load_session_snapshot(project_id)
        if data is None:
            return None
        snapshot = deserialize_snapshot(data)
        if not is_recoverable(snapshot):
            return None
        # La sesión recuperada se reconstruye como activa en esta ejecución;
        # los agentes reales vivos los reengancha AF-031
        # (`reconcile_session_agents`, arranque) sobre la sesión ya viva.
        session = DevelopmentSession(id=f"session-{project_id}", project_id=project_id)
        session.status = "active"
        # Registro en el historial persistido del propio evento de
        # recuperación (mismo patrón que `record_activity` del dominio).
        recovered = snapshot.record_activity(
            "sesion_recuperada",
            detail="recuperada de snapshot persistido al reabrir Atlas Forge",
        )
        self._persist_snapshot(project_id, session, override=serialize_snapshot(recovered))
        return session

    def _persist_snapshot(
        self,
        project_id: str,
        session: DevelopmentSession,
        override: dict | None = None,
    ) -> None:
        """Serializa y persiste el snapshot recuperable de `session` (usando
        `build_session_snapshot` + `serialize_snapshot` de la capa de
        dominio). Best-effort: un fallo de disco no debe abortar el flujo."""
        try:
            if override is not None:
                data = override
            else:
                data = serialize_snapshot(build_session_snapshot(session))
            save_session_snapshot(project_id, data)
        except Exception:
            pass

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

    Si hay un proyecto activo válido (T-AF001-US01-04), crea la sesión (o
    reutiliza la que ya estuviera viva para ese `project_id`, AF-029),
    la transiciona a `active`, y la devuelve. Si no hay proyecto activo
    (primera ejecución, o selección previa inválida), no crea ninguna
    sesión — el flujo de selección/reselección de proyecto (AF-001) debe
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
    no, la crea igual que `resolve_startup_session` (AF-029). Pensado para
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

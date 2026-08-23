"""Tests unitarios para `atlas_forge.actions.transversal` (AF-025 Hilo 3)."""
import uuid

import pytest

import atlas_forge.actions.transversal as transversal_module
from atlas_forge.actions.transversal import (
    ACCIONES_DISPONIBLES,
    ActionType,
    _ACTION_DESCRIPTIONS,
    _STORY_ID_MAP,
    _persist_action_report,
    dispatch_action,
)
from atlas_forge.agents.arquitecto import ARQUITECTO_ROLE
from atlas_forge.agents.auditor_oss import AUDITOR_OSS_ROLE
from atlas_forge.agents.documentador import DOCUMENTADOR_ROLE
from atlas_forge.agents.ux import UX_ROLE
from atlas_forge.models import Agent, DevelopmentSession, Job


class TestActionDefinitions:
    def test_eight_actions_defined(self):
        assert len(ACCIONES_DISPONIBLES) == 8
        assert ActionType.DOCUMENTAR in ACCIONES_DISPONIBLES
        assert ActionType.ANALIZAR_ARQUITECTURA in ACCIONES_DISPONIBLES
        assert ActionType.SUGERIR_IDEAS in ACCIONES_DISPONIBLES
        assert ActionType.TESTEAR in ACCIONES_DISPONIBLES
        assert ActionType.AUDITAR_UX in ACCIONES_DISPONIBLES
        assert ActionType.AUDITAR_OSS in ACCIONES_DISPONIBLES
        assert ActionType.TESTEAR_UI in ACCIONES_DISPONIBLES
        assert ActionType.INDEXAR in ACCIONES_DISPONIBLES

    def test_action_descriptions_exist(self):
        for action_id in ("documentar", "analizar-arquitectura", "sugerir-ideas", "auditar-ux", "auditar-oss", "indexar"):
            assert action_id in _ACTION_DESCRIPTIONS
            desc = _ACTION_DESCRIPTIONS[action_id]
            assert len(desc) > 50, f"descripción de '{action_id}' demasiado corta ({len(desc)} chars)"

    def test_story_id_map(self):
        assert _STORY_ID_MAP.get("documentar") == "US-AF025-01"
        assert _STORY_ID_MAP.get("analizar-arquitectura") == "US-AF025-02"
        assert _STORY_ID_MAP.get("sugerir-ideas") == "US-AF025-03"
        assert _STORY_ID_MAP.get("testear") == "US-AF025-04"
        assert _STORY_ID_MAP.get("auditar-ux") == "US-AF025-06"
        assert _STORY_ID_MAP.get("auditar-oss") == "US-AF025-08"
        assert _STORY_ID_MAP.get("indexar") == "US-AF025-07"


class TestPersistActionReport:
    def test_persist_creates_directory_and_file(self, tmp_path):
        job = Job(
            id=str(uuid.uuid4()),
            session_id="sess-1",
            agent_id="agent-1",
            description="Test description",
            status="completed",
            result="Test result",
        )
        path = _persist_action_report("documentar", job)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert job.id in content
        assert "Test result" in content

    def test_persist_two_executions_no_overwrite(self, tmp_path):
        import atlas_forge.actions.transversal as tmod
        orig = tmod._default_reports_root
        try:
            tmod._default_reports_root = lambda: tmp_path / "07-informes"
            job1 = Job(
                id=str(uuid.uuid4()),
                session_id="sess-1",
                agent_id="agent-1",
                description="desc",
                status="completed",
                result="r1",
            )
            path1 = _persist_action_report("analizar-arquitectura", job1)
            assert path1.exists()

            job2 = Job(
                id=str(uuid.uuid4()),
                session_id="sess-2",
                agent_id="agent-2",
                description="desc",
                status="completed",
                result="r2",
            )
            path2 = _persist_action_report("analizar-arquitectura", job2)
            assert path2.exists()
            assert path1 != path2

            md_files = list((tmp_path / "07-informes" / "US-AF025-02").glob("*.md"))
            assert len(md_files) >= 2
        finally:
            tmod._default_reports_root = orig

    def test_persist_uses_correct_story_dir(self, tmp_path):
        import atlas_forge.actions.transversal as tmod
        orig = tmod._default_reports_root
        try:
            tmod._default_reports_root = lambda: tmp_path / "07-informes"
            job = Job(
                id=str(uuid.uuid4()),
                session_id="sess-1",
                agent_id="agent-1",
                description="desc",
                status="completed",
                result="res",
            )
            _persist_action_report("sugerir-ideas", job)
            story_dir = tmp_path / "07-informes" / "US-AF025-03"
            assert story_dir.is_dir()
            assert any(story_dir.glob("*.md"))
        finally:
            tmod._default_reports_root = orig


class TestAuditarUxDispatchesToUxAgent:
    """T-AF024-US13-03: `auditar-ux` despacha un Job normal a la instancia
    de UX ya lanzada (mismo mecanismo genérico que `documentar` usa con
    Arquitecto vía `_dispatch_agent_action`), en vez del
    `subprocess.run(["opencode", "run", "--auto", ...])` headless previo."""

    def test_auditar_ux_with_ux_agent_launched_dispatches_a_real_job(
        self, monkeypatch, tmp_path
    ) -> None:
        session = DevelopmentSession(id="sess-1", project_id="proj-1")
        ux_agent = Agent(
            id="ux-1",
            name="UX",
            role=UX_ROLE,
            prompt="prompt",
            runtime_id="runtime-1",
            status="idle",
        )

        monkeypatch.setattr(
            transversal_module, "get_current_session", lambda: session
        )
        monkeypatch.setattr(
            transversal_module, "list_agents", lambda _session: [ux_agent]
        )
        monkeypatch.setattr(
            transversal_module, "_default_reports_root", lambda: tmp_path / "07-informes"
        )

        dispatch_calls = []

        def fake_create_and_record_job(description, agent, session_arg):
            assert agent is ux_agent
            return Job(
                id=str(uuid.uuid4()),
                session_id=session_arg.id,
                agent_id=agent.id,
                description=description,
                status="dispatched",
            )

        monkeypatch.setattr(
            transversal_module, "create_and_record_job", fake_create_and_record_job
        )
        monkeypatch.setattr(
            transversal_module,
            "get_runtime_instance_for_agent",
            lambda agent_id: object(),
        )

        def fake_dispatch_job(job, agent, runtime_instance, socket_name=None):
            dispatch_calls.append((job, agent, socket_name))
            job.status = "completed"
            job.result = "auditoría completada"

        monkeypatch.setattr(transversal_module, "dispatch_job", fake_dispatch_job)

        result = dispatch_action("auditar-ux", socket_name="test-socket")

        assert len(dispatch_calls) == 1
        dispatched_job, dispatched_agent, socket_name = dispatch_calls[0]
        assert dispatched_agent is ux_agent
        assert socket_name == "test-socket"
        assert result["action"] == "auditar-ux"
        assert result["status"] == "completed"
        assert result["result"] == "auditoría completada"

    def test_auditar_ux_without_ux_agent_launched_fails_explicitly(
        self, monkeypatch
    ) -> None:
        session = DevelopmentSession(id="sess-1", project_id="proj-1")
        monkeypatch.setattr(
            transversal_module, "get_current_session", lambda: session
        )
        monkeypatch.setattr(transversal_module, "list_agents", lambda _session: [])

        with pytest.raises(RuntimeError, match="UX"):
            dispatch_action("auditar-ux")

    def test_auditar_ux_with_stopped_ux_agent_fails_explicitly_not_500(
        self, monkeypatch
    ) -> None:
        """Bug real encontrado en verificación de navegador (2026-08-16):
        una instancia de UX registrada pero `stopped` (no `idle`) hacía que
        `create_and_record_job` lanzara `JobCreationError` sin traducir,
        propagándose como 500 en vez del `RuntimeError` explícito exigido
        por el criterio de aceptación 3 de la Task."""
        session = DevelopmentSession(id="sess-1", project_id="proj-1")
        stopped_ux_agent = Agent(
            id="ux-1",
            name="UX",
            role=UX_ROLE,
            prompt="prompt",
            runtime_id="runtime-1",
            status="stopped",
        )
        monkeypatch.setattr(
            transversal_module, "get_current_session", lambda: session
        )
        monkeypatch.setattr(
            transversal_module, "list_agents", lambda _session: [stopped_ux_agent]
        )

        with pytest.raises(RuntimeError, match="UX"):
            dispatch_action("auditar-ux")


class TestDocumentarDispatchesToDocumentadorAgent:
    """T-AF024-US20-01: `documentar` despacha un Job a la instancia de
    Documentador ya lanzada, NO al Arquitecto (comportamiento anterior a
    esta Task) — mismo mecanismo genérico
    `_dispatch_agent_action`/`_find_agent_by_role` que ya usa
    `auditar-ux` con UX."""

    def test_action_role_map_points_documentar_to_documentador(self) -> None:
        assert transversal_module._ACTION_ROLE_MAP["documentar"] == DOCUMENTADOR_ROLE
        assert transversal_module._ACTION_ROLE_MAP["documentar"] != ARQUITECTO_ROLE

    def test_role_display_name_includes_documentador(self) -> None:
        assert transversal_module._ROLE_DISPLAY_NAME[DOCUMENTADOR_ROLE] == "Documentador"

    def test_documentar_with_documentador_agent_launched_dispatches_a_real_job(
        self, monkeypatch, tmp_path
    ) -> None:
        session = DevelopmentSession(id="sess-1", project_id="proj-1")
        documentador_agent = Agent(
            id="documentador-1",
            name="Documentador",
            role=DOCUMENTADOR_ROLE,
            prompt="prompt",
            runtime_id="runtime-1",
            status="idle",
        )
        # Un Arquitecto también lanzado, para confirmar que el Job va al
        # Documentador y NUNCA al Arquitecto aunque ambos estén idle.
        arquitecto_agent = Agent(
            id="arquitecto-1",
            name="Arquitecto",
            role=ARQUITECTO_ROLE,
            prompt="prompt",
            runtime_id="runtime-2",
            status="idle",
        )

        monkeypatch.setattr(
            transversal_module, "get_current_session", lambda: session
        )
        monkeypatch.setattr(
            transversal_module,
            "list_agents",
            lambda _session: [documentador_agent, arquitecto_agent],
        )
        monkeypatch.setattr(
            transversal_module, "_default_reports_root", lambda: tmp_path / "07-informes"
        )

        dispatch_calls = []

        def fake_create_and_record_job(description, agent, session_arg):
            return Job(
                id=str(uuid.uuid4()),
                session_id=session_arg.id,
                agent_id=agent.id,
                description=description,
                status="dispatched",
            )

        monkeypatch.setattr(
            transversal_module, "create_and_record_job", fake_create_and_record_job
        )
        monkeypatch.setattr(
            transversal_module,
            "get_runtime_instance_for_agent",
            lambda agent_id: object(),
        )

        def fake_dispatch_job(job, agent, runtime_instance, socket_name=None):
            dispatch_calls.append((job, agent, socket_name))
            job.status = "completed"
            job.result = "documentación completada"

        monkeypatch.setattr(transversal_module, "dispatch_job", fake_dispatch_job)

        result = dispatch_action("documentar", socket_name="test-socket")

        assert len(dispatch_calls) == 1
        dispatched_job, dispatched_agent, socket_name = dispatch_calls[0]
        assert dispatched_agent is documentador_agent
        assert dispatched_agent is not arquitecto_agent
        assert socket_name == "test-socket"
        assert result["action"] == "documentar"
        assert result["status"] == "completed"
        assert result["result"] == "documentación completada"

    def test_documentar_without_documentador_agent_launched_fails_explicitly(
        self, monkeypatch
    ) -> None:
        """Un Arquitecto lanzado (idle) NO debe usarse como fallback — el
        criterio de aceptación exige un error explícito, nunca desviar al
        Arquitecto en silencio."""
        session = DevelopmentSession(id="sess-1", project_id="proj-1")
        arquitecto_agent = Agent(
            id="arquitecto-1",
            name="Arquitecto",
            role=ARQUITECTO_ROLE,
            prompt="prompt",
            runtime_id="runtime-1",
            status="idle",
        )
        monkeypatch.setattr(
            transversal_module, "get_current_session", lambda: session
        )
        monkeypatch.setattr(
            transversal_module, "list_agents", lambda _session: [arquitecto_agent]
        )

        dispatch_calls = []
        monkeypatch.setattr(
            transversal_module,
            "dispatch_job",
            lambda *a, **k: dispatch_calls.append(a),
        )

        with pytest.raises(RuntimeError, match="Documentador"):
            dispatch_action("documentar")

        assert dispatch_calls == []

    def test_documentar_with_stopped_documentador_agent_fails_explicitly(
        self, monkeypatch
    ) -> None:
        session = DevelopmentSession(id="sess-1", project_id="proj-1")
        stopped_documentador_agent = Agent(
            id="documentador-1",
            name="Documentador",
            role=DOCUMENTADOR_ROLE,
            prompt="prompt",
            runtime_id="runtime-1",
            status="stopped",
        )
        monkeypatch.setattr(
            transversal_module, "get_current_session", lambda: session
        )
        monkeypatch.setattr(
            transversal_module, "list_agents", lambda _session: [stopped_documentador_agent]
        )

        with pytest.raises(RuntimeError, match="Documentador"):
            dispatch_action("documentar")

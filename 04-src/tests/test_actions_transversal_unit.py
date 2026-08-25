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
    list_actions,
)
from atlas_forge.agents.arquitecto import ARQUITECTO_ROLE
from atlas_forge.agents.auditor_oss import AUDITOR_OSS_ROLE
from atlas_forge.agents.documentador import DOCUMENTADOR_ROLE
from atlas_forge.agents.ux import UX_ROLE
from atlas_forge.models import Agent, DevelopmentSession, Job


class TestActionDefinitions:
    def test_ten_actions_defined(self):
        assert len(ACCIONES_DISPONIBLES) == 10
        assert ActionType.DOCUMENTAR in ACCIONES_DISPONIBLES
        assert ActionType.ANALIZAR_ARQUITECTURA in ACCIONES_DISPONIBLES
        assert ActionType.SUGERIR_IDEAS in ACCIONES_DISPONIBLES
        assert ActionType.TESTEAR in ACCIONES_DISPONIBLES
        assert ActionType.AUDITAR_UX in ACCIONES_DISPONIBLES
        assert ActionType.AUDITAR_OSS in ACCIONES_DISPONIBLES
        assert ActionType.AUDITAR_BACKLOG in ACCIONES_DISPONIBLES
        assert ActionType.VERIFICAR_AUDITORIA in ACCIONES_DISPONIBLES
        assert ActionType.TESTEAR_UI in ACCIONES_DISPONIBLES
        assert ActionType.INDEXAR in ACCIONES_DISPONIBLES


class TestCatalogCombinado:
    """T-AF034-US01-01: catálogo combinado con tipo de ejecución y origen."""

    def test_list_actions_covers_all_available_actions(self):
        catalog = list_actions()
        assert [entry["id"] for entry in catalog] == list(ACCIONES_DISPONIBLES)
        assert len(catalog) == 10

    def test_list_actions_has_full_metadata(self):
        for entry in list_actions():
            assert set(entry) == {
                "id", "name", "description", "origin", "execution_type"
            }
            assert entry["id"]
            assert entry["name"]
            assert entry["description"]
            assert entry["origin"] == "generic"

    def test_execution_type_matches_real_nature(self):
        """Cada acción declara su execution_type según su naturaleza real en
        transversal.py (criterio de la Task)."""
        by_id = {entry["id"]: entry["execution_type"] for entry in list_actions()}
        # Deterministas (segundos).
        assert by_id["testear"] == "script"
        assert by_id["testear-ui"] == "script"
        # Despachan un Job a un agente persistente (minutos).
        assert by_id["documentar"] == "agent_job"
        assert by_id["analizar-arquitectura"] == "agent_job"
        assert by_id["sugerir-ideas"] == "agent_job"
        assert by_id["auditar-oss"] == "agent_job"
        assert by_id["auditar-ux"] == "agent_job"
        assert by_id["auditar-backlog"] == "agent_job"
        assert by_id["verificar-auditoria"] == "agent_job"
        # Proceso externo headless sin agente.
        assert by_id["indexar"] == "external_process"

    def test_origin_is_generic_for_all_actions(self):
        assert all(entry["origin"] == "generic" for entry in list_actions())

    def test_action_descriptions_exist(self):
        for action_id in ("documentar", "analizar-arquitectura", "sugerir-ideas", "auditar-ux", "auditar-oss", "auditar-backlog", "verificar-auditoria", "indexar"):
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
        assert _STORY_ID_MAP.get("auditar-backlog") == "US-AF018-03"
        assert _STORY_ID_MAP.get("verificar-auditoria") == "US-AF018-03"
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


class TestAuditarBacklogDispatchesToArquitecto:
    """T-AF018-US03-01: `auditar-backlog` despacha un Job al Arquitecto ya
    lanzado (paso 1 de la auditoría del backlog) vía
    `_dispatch_agent_action` y persiste el informe en
    `07-informes/US-AF018-03/` con nombre con fecha — nunca solo en
    pantalla/scrollback."""

    def test_description_requires_structured_findings(self) -> None:
        """Criterio 3: la descripción del paso 1 exige el formato de hallazgo
        estructurado (id, estado_declarado, evidencia, veredicto provisional)
        para que el paso 2 pueda consumirlo parseable."""
        desc = _ACTION_DESCRIPTIONS[ActionType.AUDITAR_BACKLOG]
        for token in (
            "id",
            "estado_declarado",
            "evidencia",
            "confirmado",
            "falso_positivo",
            "incompleto",
        ):
            assert token in desc, f"descripción de 'auditar-backlog' sin '{token}'"

    def test_auditar_backlog_with_arquitecto_launched_dispatches_and_persists(
        self, monkeypatch, tmp_path
    ) -> None:
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
        monkeypatch.setattr(
            transversal_module,
            "_default_reports_root",
            lambda: tmp_path / "07-informes",
        )

        dispatch_calls = []

        def fake_create_and_record_job(description, agent, session_arg):
            assert agent is arquitecto_agent
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
            job.result = (
                "hallazgo:\n"
                "- id: US-AF018-03\n"
                "- estado_declarado: READY\n"
                "- evidencia: transversal.py ActionType.AUDITAR_BACKLOG\n"
                "- veredicto: confirmado\n"
            )

        monkeypatch.setattr(transversal_module, "dispatch_job", fake_dispatch_job)

        result = dispatch_action("auditar-backlog", socket_name="test-socket")

        assert len(dispatch_calls) == 1
        dispatched_job, dispatched_agent, socket_name = dispatch_calls[0]
        assert dispatched_agent is arquitecto_agent
        assert socket_name == "test-socket"
        assert result["action"] == "auditar-backlog"
        assert result["status"] == "completed"
        assert "veredicto: confirmado" in result["result"]

        # Persistencia con nombre con fecha en 07-informes/US-AF018-03/
        story_dir = tmp_path / "07-informes" / "US-AF018-03"
        assert story_dir.is_dir()
        md_files = sorted(story_dir.glob("auditar-backlog-*.md"))
        assert len(md_files) == 1
        content = md_files[0].read_text(encoding="utf-8")
        assert dispatched_job.id in content
        assert "veredicto: confirmado" in content

    def test_auditar_backlog_without_arquitecto_fails_explicitly(
        self, monkeypatch
    ) -> None:
        """Criterio 4: si no hay un Arquitecto `idle` lanzado, la acción
        informa explícitamente ('Lanza el Arquitecto antes de auditar') — no
        falla en silencio."""
        session = DevelopmentSession(id="sess-1", project_id="proj-1")
        monkeypatch.setattr(
            transversal_module, "get_current_session", lambda: session
        )
        monkeypatch.setattr(transversal_module, "list_agents", lambda _session: [])

        with pytest.raises(RuntimeError, match="Lanza el Arquitecto antes de auditar"):
            dispatch_action("auditar-backlog")

    def test_auditar_backlog_with_stopped_arquitecto_fails_explicitly(
        self, monkeypatch
    ) -> None:
        session = DevelopmentSession(id="sess-1", project_id="proj-1")
        stopped_arquitecto = Agent(
            id="arquitecto-1",
            name="Arquitecto",
            role=ARQUITECTO_ROLE,
            prompt="prompt",
            runtime_id="runtime-1",
            status="stopped",
        )
        monkeypatch.setattr(
            transversal_module, "get_current_session", lambda: session
        )
        monkeypatch.setattr(
            transversal_module, "list_agents", lambda _session: [stopped_arquitecto]
        )

        dispatch_calls = []
        monkeypatch.setattr(
            transversal_module,
            "dispatch_job",
            lambda *a, **k: dispatch_calls.append(a),
        )

        with pytest.raises(RuntimeError, match="Arquitecto"):
            dispatch_action("auditar-backlog")

        assert dispatch_calls == []


class TestVerificarAuditoriaDispatchesToAuditor:
    """T-AF018-US03-02: `verificar-auditoria` (paso 2 de la auditoría del
    backlog, US-AF018-03) despacha un Job al rol Auditor (`auditor_oss`)
    cuya descripción incorpora la ruta del fichero de la auditoría del paso 1
    (`auditar-backlog`) como entrada, y persiste el informe en
    `07-informes/US-AF018-03/` con nombre con fecha referenciando ese
    fichero. Acción independiente: NO se ejecuta automáticamente tras
    `auditar-backlog`."""

    def test_action_role_map_points_verificar_auditoria_to_auditor(self) -> None:
        assert (
            transversal_module._ACTION_ROLE_MAP["verificar-auditoria"]
            == AUDITOR_OSS_ROLE
        )

    def test_description_requires_parseable_action_per_finding(self) -> None:
        """Criterio 3: la descripción exige una acción concreta y parseable
        por hallazgo (`corregir_estado` / `crear_task_correccion` /
        `descartar`), no solo opinión libre; y declara la ruta del fichero
        del paso 1 como entrada."""
        desc = _ACTION_DESCRIPTIONS[ActionType.VERIFICAR_AUDITORIA]
        for token in (
            "corregir_estado",
            "crear_task_correccion",
            "descartar",
            "INPUT_PATH",
            "accion",
        ):
            assert token in desc, (
                f"descripción de 'verificar-auditoria' sin '{token}'"
            )

    def test_verificar_auditoria_with_auditor_launched_dispatches_and_persists(
        self, monkeypatch, tmp_path
    ) -> None:
        """Criterios 1, 2 y 5: se despacha un Job al Auditor con la ruta del
        fichero del paso 1 en la descripción y el informe se persiste en
        `07-informes/US-AF018-03/` referenciando ese fichero."""
        session = DevelopmentSession(id="sess-1", project_id="proj-1")
        auditor_agent = Agent(
            id="auditor-1",
            name="Auditor-OSS",
            role=AUDITOR_OSS_ROLE,
            prompt="prompt",
            runtime_id="runtime-1",
            status="idle",
        )

        monkeypatch.setattr(
            transversal_module, "get_current_session", lambda: session
        )
        monkeypatch.setattr(
            transversal_module, "list_agents", lambda _session: [auditor_agent]
        )
        monkeypatch.setattr(
            transversal_module,
            "_default_reports_root",
            lambda: tmp_path / "07-informes",
        )

        input_path = "07-informes/US-AF018-03/auditar-backlog-2026-08-24T200000.md"
        created_descriptions = []
        dispatch_calls = []

        def fake_create_and_record_job(description, agent, session_arg):
            assert agent is auditor_agent
            created_descriptions.append(description)
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
            job.result = (
                "hallazgo:\n"
                "- id: US-AF018-03\n"
                "- accion: corregir_estado\n"
                "- estado_correcto: DONE\n"
            )

        monkeypatch.setattr(transversal_module, "dispatch_job", fake_dispatch_job)

        result = dispatch_action(
            "verificar-auditoria",
            socket_name="test-socket",
            input_path=input_path,
        )

        assert len(dispatch_calls) == 1
        dispatched_job, dispatched_agent, socket_name = dispatch_calls[0]
        assert dispatched_agent is auditor_agent
        assert socket_name == "test-socket"
        assert result["action"] == "verificar-auditoria"
        assert result["status"] == "completed"
        assert "accion: corregir_estado" in result["result"]

        # La descripción del Job incorpora la ruta del fichero del paso 1.
        assert len(created_descriptions) == 1
        assert input_path in created_descriptions[0]
        assert "corregir_estado" in created_descriptions[0]

        # Persistencia con nombre con fecha en 07-informes/US-AF018-03/,
        # referenciando el fichero del paso 1.
        story_dir = tmp_path / "07-informes" / "US-AF018-03"
        assert story_dir.is_dir()
        md_files = sorted(story_dir.glob("verificar-auditoria-*.md"))
        assert len(md_files) == 1
        content = md_files[0].read_text(encoding="utf-8")
        assert dispatched_job.id in content
        assert input_path in content
        assert "accion: corregir_estado" in content

    def test_verificar_auditoria_requires_input_path(self, monkeypatch) -> None:
        """Criterio 1: sin la ruta del fichero del paso 1 la acción falla
        explícitamente — no despacha un Job sin su entrada."""
        session = DevelopmentSession(id="sess-1", project_id="proj-1")
        auditor_agent = Agent(
            id="auditor-1",
            name="Auditor-OSS",
            role=AUDITOR_OSS_ROLE,
            prompt="prompt",
            runtime_id="runtime-1",
            status="idle",
        )
        monkeypatch.setattr(
            transversal_module, "get_current_session", lambda: session
        )
        monkeypatch.setattr(
            transversal_module, "list_agents", lambda _session: [auditor_agent]
        )

        dispatch_calls = []
        monkeypatch.setattr(
            transversal_module,
            "dispatch_job",
            lambda *a, **k: dispatch_calls.append(a),
        )

        with pytest.raises(ValueError, match="input_path"):
            dispatch_action("verificar-auditoria")

        assert dispatch_calls == []

    def test_verificar_auditoria_without_auditor_fails_explicitly(
        self, monkeypatch
    ) -> None:
        """Espejo del paso 1 (criterio 4 de T-AF018-US03-01): sin un Auditor
        `idle` lanzado la acción informa explícitamente, no falla en
        silencio."""
        session = DevelopmentSession(id="sess-1", project_id="proj-1")
        monkeypatch.setattr(
            transversal_module, "get_current_session", lambda: session
        )
        monkeypatch.setattr(transversal_module, "list_agents", lambda _session: [])

        with pytest.raises(RuntimeError, match="Auditor-OSS"):
            dispatch_action("verificar-auditoria", input_path="in.md")

    def test_verificar_auditoria_with_stopped_auditor_fails_explicitly(
        self, monkeypatch
    ) -> None:
        session = DevelopmentSession(id="sess-1", project_id="proj-1")
        stopped_auditor = Agent(
            id="auditor-1",
            name="Auditor-OSS",
            role=AUDITOR_OSS_ROLE,
            prompt="prompt",
            runtime_id="runtime-1",
            status="stopped",
        )
        monkeypatch.setattr(
            transversal_module, "get_current_session", lambda: session
        )
        monkeypatch.setattr(
            transversal_module, "list_agents", lambda _session: [stopped_auditor]
        )

        dispatch_calls = []
        monkeypatch.setattr(
            transversal_module,
            "dispatch_job",
            lambda *a, **k: dispatch_calls.append(a),
        )

        with pytest.raises(RuntimeError, match="Auditor-OSS"):
            dispatch_action("verificar-auditoria", input_path="in.md")

        assert dispatch_calls == []

    def test_auditar_backlog_does_not_auto_trigger_verificar_auditoria(
        self, monkeypatch, tmp_path
    ) -> None:
        """Criterio 4: `verificar-auditoria`**no** se ejecuta automáticamente
        tras `auditar-backlog` — despachar el paso 1 crea EXACTAMENTE un Job
        (el del arquitato para auditar-backlog), nunca un segundo Job de
        verificación."""
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
        monkeypatch.setattr(
            transversal_module,
            "_default_reports_root",
            lambda: tmp_path / "07-informes",
        )

        created_descriptions = []

        def fake_create_and_record_job(description, agent, session_arg):
            created_descriptions.append(description)
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
        monkeypatch.setattr(
            transversal_module,
            "dispatch_job",
            lambda job, agent, runtime_instance, socket_name=None: setattr(
                job, "status", "completed"
            ),
        )

        dispatch_action("auditar-backlog", socket_name="test-socket")

        assert len(created_descriptions) == 1
        assert "INPUT_PATH" not in created_descriptions[0]
        assert "corregir_estado" not in created_descriptions[0]
        # No se crea ningún informe de verificación.
        story_dir = tmp_path / "07-informes" / "US-AF018-03"
        verificar_files = list(story_dir.glob("verificar-auditoria-*.md"))
        assert verificar_files == []

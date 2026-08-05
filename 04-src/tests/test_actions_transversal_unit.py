"""Tests unitarios para `brain.actions.transversal` (FB-025 Hilo 3)."""
import uuid

import pytest

from brain.actions.transversal import (
    ACCIONES_DISPONIBLES,
    ActionType,
    _ACTION_DESCRIPTIONS,
    _STORY_ID_MAP,
    _persist_action_report,
    dispatch_action,
)
from brain.models import Job


class TestActionDefinitions:
    def test_six_actions_defined(self):
        assert len(ACCIONES_DISPONIBLES) == 6
        assert ActionType.DOCUMENTAR in ACCIONES_DISPONIBLES
        assert ActionType.ANALIZAR_ARQUITECTURA in ACCIONES_DISPONIBLES
        assert ActionType.SUGERIR_IDEAS in ACCIONES_DISPONIBLES
        assert ActionType.TESTEAR in ACCIONES_DISPONIBLES
        assert ActionType.AUDITAR_UX in ACCIONES_DISPONIBLES
        assert ActionType.INDEXAR in ACCIONES_DISPONIBLES

    def test_action_descriptions_exist(self):
        for action_id in ("documentar", "analizar-arquitectura", "sugerir-ideas", "auditar-ux", "indexar"):
            assert action_id in _ACTION_DESCRIPTIONS
            desc = _ACTION_DESCRIPTIONS[action_id]
            assert len(desc) > 50, f"descripción de '{action_id}' demasiado corta ({len(desc)} chars)"

    def test_story_id_map(self):
        assert _STORY_ID_MAP.get("documentar") == "US-FB025-01"
        assert _STORY_ID_MAP.get("analizar-arquitectura") == "US-FB025-02"
        assert _STORY_ID_MAP.get("sugerir-ideas") == "US-FB025-03"
        assert _STORY_ID_MAP.get("testear") == "US-FB025-04"
        assert _STORY_ID_MAP.get("auditar-ux") == "US-FB025-06"
        assert _STORY_ID_MAP.get("indexar") == "US-FB025-07"


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
        import brain.actions.transversal as tmod
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

            md_files = list((tmp_path / "07-informes" / "US-FB025-02").glob("*.md"))
            assert len(md_files) >= 2
        finally:
            tmod._default_reports_root = orig

    def test_persist_uses_correct_story_dir(self, tmp_path):
        import brain.actions.transversal as tmod
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
            story_dir = tmp_path / "07-informes" / "US-FB025-03"
            assert story_dir.is_dir()
            assert any(story_dir.glob("*.md"))
        finally:
            tmod._default_reports_root = orig

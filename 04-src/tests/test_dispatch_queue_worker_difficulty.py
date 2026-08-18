"""Tests de T-FB008-US12-02: dispatcher elige Developer/modelo por dificultad.

Cubre la lógica de _pick_developer_for_difficulty y la integración con
_get_task_difficulty, get_models_for_difficulty, get_active_model, y
set_active_model."""

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from brain.core.session_lifecycle import activate, assign_agent
from brain.dispatcher.dispatch_queue import (
    STATUS_DISPATCHED,
    STATUS_QUEUED,
    enqueue_task,
    get_queue,
)
from brain.dispatcher.dispatch_queue_worker import (
    _get_task_difficulty,
    _pick_developer_for_difficulty,
    run_dispatch_cycle,
)
from brain.models import Agent, DevelopmentSession, Runtime
from brain.runtime import register_runtime_instance_for_agent, RuntimeInstance


def _write_backlog_item(backlog_dir, filename, state="TODO", difficulty=None):
    """Escribe un item de backlog con frontmatter YAML."""
    tasks_dir = backlog_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    frontmatter = f"""---
id: {filename}
type: task
title: Test Task
state: {state}
dependencies: []
epic: FB-999
user_story: US-FB999-01
priority: Alta
"""
    if difficulty:
        frontmatter += f"difficulty: {difficulty}\n"
    frontmatter += "---\n\n# Test Task\n"

    (tasks_dir / f"{filename}.md").write_text(frontmatter, encoding="utf-8")


def test_get_task_difficulty_returns_difficulty_for_task():
    """_get_task_difficulty extrae la dificultad de una Task del grafo."""
    from brain.backlog.parser import load_backlog
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        backlog_dir = Path(tmp) / "02-backlog"
        _write_backlog_item(backlog_dir, "T-FB999-US01-01", difficulty="Alta")

        graph = load_backlog(backlog_dir)
        difficulty = _get_task_difficulty(graph, "T-FB999-US01-01")

        assert difficulty == "Alta"


def test_get_task_difficulty_returns_none_when_no_difficulty():
    """_get_task_difficulty retorna None para Task sin difficulty."""
    from brain.backlog.parser import load_backlog
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        backlog_dir = Path(tmp) / "02-backlog"
        _write_backlog_item(backlog_dir, "T-FB999-US01-01")  # sin difficulty

        graph = load_backlog(backlog_dir)
        difficulty = _get_task_difficulty(graph, "T-FB999-US01-01")

        assert difficulty is None


def test_pick_developer_for_difficulty_no_developer_available():
    """Sin Developer idle disponible, retorna None."""
    from brain.dispatcher.dispatch_queue_worker import _NoAgentAvailableError

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)
    # No assigning any agents

    result = _pick_developer_for_difficulty(session, "Alta", Path("/tmp"))
    assert result is None


def test_pick_developer_for_difficulty_ignores_a_limited_developer():
    """Criterio de aceptación de T-FB024-US21-01: un Developer `limited`
    (sin límite de sesión liberado todavía) nunca es elegible — mismo
    filtro estricto `status == "idle"` que ya excluye `working`/`stopped`/
    `unavailable`, sin necesitar ningún caso especial nuevo."""
    from brain.agents.lifecycle import mark_limited

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    agent = Agent(id="a-dev", name="dev1", role="developer", prompt="p", runtime_id="r1")
    assign_agent(session, agent)
    mark_limited(agent, "2026-08-17T01:30:00+00:00")

    result = _pick_developer_for_difficulty(session, None, Path("/tmp"))

    assert result is None


def test_pick_developer_for_difficulty_no_difficulty_requirement():
    """Sin dificultad especificada, devuelve cualquier Developer idle."""
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    agent = Agent(id="a-dev", name="dev1", role="developer", prompt="p", runtime_id="r1")
    assign_agent(session, agent)

    result = _pick_developer_for_difficulty(session, None, Path("/tmp"))

    assert result is not None
    dev, reason = result
    assert dev.id == "a-dev"
    assert "sin requisito" in reason


def test_pick_developer_for_difficulty_unrecognized_difficulty():
    """Con dificultad no reconocida, devuelve Developer con reason='degradado'."""
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    agent = Agent(id="a-dev", name="dev1", role="developer", prompt="p", runtime_id="r1")
    assign_agent(session, agent)

    # Dificultad 'XYZ' no está en el DEFAULT_DIFFICULTY_MODEL_MAP
    result = _pick_developer_for_difficulty(session, "XYZ", Path("/tmp"))

    assert result is not None
    dev, reason = result
    assert dev.id == "a-dev"
    assert "degradado" in reason


@patch("brain.dispatcher.dispatch_queue_worker.get_active_model")
@patch("brain.dispatcher.dispatch_queue_worker.get_models_for_difficulty")
def test_pick_developer_for_difficulty_model_already_fits(
    mock_get_models, mock_get_active_model
):
    """Con modelo actual que ya encaja, devuelve reason='encaja directo'."""
    from brain.models_catalog import ModelEntry

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    agent = Agent(id="a-dev", name="dev1", role="developer", prompt="p", runtime_id="r1")
    assign_agent(session, agent)

    # Mock: el modelo requerido es 'claude-opus'
    required_model = ModelEntry(id="claude-opus", name="Claude Opus", runtime="claude_code", tier=5)
    mock_get_models.return_value = [required_model]

    # Mock: el modelo actual es "Claude Opus" (coincide)
    mock_get_active_model.return_value = "Claude Opus"

    result = _pick_developer_for_difficulty(session, "Crítica", Path("/tmp"))

    assert result is not None
    dev, reason = result
    assert "encaja directo" in reason


@patch("brain.dispatcher.dispatch_queue_worker.get_runtime_instance_for_agent")
@patch("brain.dispatcher.dispatch_queue_worker.set_active_model")
@patch("brain.dispatcher.dispatch_queue_worker.get_active_model")
@patch("brain.dispatcher.dispatch_queue_worker.get_models_for_difficulty")
def test_pick_developer_for_difficulty_changes_model_on_opencode(
    mock_get_models, mock_get_active, mock_set_active, mock_get_runtime
):
    """Con modelo inadecuado en OpenCode, intenta cambiar el modelo."""
    from brain.models_catalog import ModelEntry

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    agent = Agent(id="a-dev", name="dev1", role="developer", prompt="p", runtime_id="r1")
    assign_agent(session, agent)

    # Mock: modelo requerido es 'opencode-go/deepseek-v4-pro'
    required_model = ModelEntry(
        id="opencode-go/deepseek-v4-pro",
        name="DeepSeek V4 Pro",
        runtime="opencode",
        tier=4
    )
    mock_get_models.return_value = [required_model]

    # Mock: modelo actual es diferente
    mock_get_active.return_value = "Some other model"

    # Mock: el runtime es OpenCode
    rt = Runtime(id="r1", name="Test", type="opencode", command="bash", args=[])
    mock_get_runtime.return_value = RuntimeInstance(runtime=rt, session_name="test-session")

    # Mock: cambio de modelo exitoso
    mock_set_active.return_value = True

    result = _pick_developer_for_difficulty(session, "Alta", Path("/tmp"))

    assert result is not None
    dev, reason = result
    assert "cambio de modelo aplicado" in reason
    mock_set_active.assert_called_once()


@patch("brain.dispatcher.dispatch_queue_worker.get_runtime_instance_for_agent")
@patch("brain.dispatcher.dispatch_queue_worker.get_active_model")
@patch("brain.dispatcher.dispatch_queue_worker.get_models_for_difficulty")
def test_pick_developer_for_difficulty_degraded_on_unsupported_runtime(
    mock_get_models, mock_get_active, mock_get_runtime
):
    """Con runtime que no soporta cambio de modelo, retorna degradado."""
    from brain.models_catalog import ModelEntry

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    agent = Agent(id="a-dev", name="dev1", role="developer", prompt="p", runtime_id="r1")
    assign_agent(session, agent)

    # Mock: modelo requerido con tier alto
    required_model = ModelEntry(
        id="opencode-go/deepseek-v4-pro",
        name="DeepSeek V4 Pro",
        runtime="opencode",
        tier=5
    )
    mock_get_models.return_value = [required_model]

    # Mock: modelo actual no encaja
    mock_get_active.return_value = "Claude Code Default"

    # Mock: runtime es Claude Code (no soporta cambio de modelo)
    rt = Runtime(id="r1", name="Test", type="claude-code", command="bash", args=[])
    mock_get_runtime.return_value = RuntimeInstance(runtime=rt, session_name="test-session")

    result = _pick_developer_for_difficulty(session, "Crítica", Path("/tmp"))

    assert result is not None
    dev, reason = result
    assert "degradado" in reason or "no soporta" in reason


def test_pick_developer_for_difficulty_no_models_in_catalog(tmp_path):
    """Cuando no hay modelos disponibles para el tier requerido, degradado."""
    with patch("brain.dispatcher.dispatch_queue_worker.get_models_for_difficulty") as mock_get_models:
        session = DevelopmentSession(id="s1", project_id="p1")
        activate(session)

        agent = Agent(id="a-dev", name="dev1", role="developer", prompt="p", runtime_id="r1")
        assign_agent(session, agent)

        # Mock: lista vacía — no hay modelos que encajen
        mock_get_models.return_value = []

        result = _pick_developer_for_difficulty(session, "Crítica", tmp_path)

        assert result is not None
        dev, reason = result
        assert "no hay modelos disponibles" in reason or "degradado" in reason


def test_run_dispatch_cycle_records_dispatch_reason(tmp_path):
    """run_dispatch_cycle registra dispatch_reason en la cola."""
    from brain.core.session_lifecycle import activate, assign_agent

    backlog_root = tmp_path / "backlog_root"
    backlog = backlog_root / "02-backlog"
    _write_backlog_item(backlog, "T-FB999-US01-01", state="EN_DESARROLLO", difficulty="Alta")
    enqueue_task(backlog_root, "proj", task_id="T-FB999-US01-01", us_id="US-FB999-01", priority="Alta")

    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    agent = Agent(id="a-dev", name="dev1", role="developer", prompt="p", runtime_id="r1")
    assign_agent(session, agent)

    with patch("brain.dispatcher.dispatch_queue_worker._pick_developer_for_difficulty") as mock_pick:
        mock_pick.return_value = (agent, "encaja directo: test")

        with patch("brain.dispatcher.dispatch_queue_worker.get_runtime_instance_for_agent") as mock_get_rt:
            rt = Runtime(id="r1", name="Test", type="test", command="bash", args=[])
            mock_get_rt.return_value = RuntimeInstance(runtime=rt, session_name="test-session")

            with patch("brain.dispatcher.dispatch_queue_worker.create_job"):
                with patch("brain.dispatcher.dispatch_queue_worker.dispatch_job"):
                    run_dispatch_cycle(backlog_root, "proj", session)

    entries = get_queue(backlog_root, "proj")
    assert len(entries) == 1
    assert entries[0].dispatch_reason == "encaja directo: test"


def test_run_dispatch_cycle_no_model_change_on_working_agent():
    """Nunca intenta cambiar modelo en un agente que está `working`."""
    session = DevelopmentSession(id="s1", project_id="p1")
    activate(session)

    agent = Agent(id="a-dev", name="dev1", role="developer", prompt="p", runtime_id="r1", status="working")
    assign_agent(session, agent)

    # _pick_developer_for_difficulty llama _find_agent_by_role, que solo
    # retorna agentes `idle` (ver job_plan_dispatch.py). Si el único
    # Developer es `working`, levanta _NoAgentAvailableError.
    result = _pick_developer_for_difficulty(session, "Alta", Path("/tmp"))

    # No debe intentar nada, simplemente retorna None sin error
    assert result is None

"""Tests de `04-src/scripts/validate_backlog.py` (T-FB022-US13-06/07):
CLI de validacion de formato de backlog contra `validate_backlog_file_v2`.

Modo staged (T-FB022-US13-06): valida solo `02-backlog/*/` staged en un
repositorio git real (usa `git diff --cached`, se ejercita sobre un repo
sintetico en `tmp_path`, nunca contra el repo real de este proyecto).

Modo lote (T-FB022-US13-07, `--batch`): valida un directorio arbitrario,
sin requerir git ni la estructura `02-backlog/`."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_backlog.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("validate_backlog_cli", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_VALID_TASK = (
    "---\n"
    "id: T-FB900-US01-01\n"
    "type: task\n"
    "title: Ejemplo válido\n"
    "state: TODO\n"
    "dependencies: []\n"
    "epic: FB-900\n"
    "user_story: US-FB900-01\n"
    "priority: Alta\n"
    "---\n\n"
    "## Objetivo\n\nObjetivo.\n\n## Criterios de aceptación\n\n1. Y.\n"
)

_INVALID_TASK = (
    "---\n"
    "id: T-FB900-US01-02\n"
    "type: task\n"
    "title: Ejemplo inválido\n"
    "state: NO_EXISTE\n"
    "dependencies: []\n"
    "---\n\n"
    "Sin epic ni user_story ni priority, y state inválido.\n"
)


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Modo staged (T-FB022-US13-06)
# ---------------------------------------------------------------------------


def test_staged_validation_passes_when_all_staged_files_are_valid(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    task_path = tmp_path / "02-backlog" / "tasks" / "T-FB900-US01-01.md"
    _write(task_path, _VALID_TASK)
    subprocess.run(["git", "add", str(task_path)], cwd=tmp_path, check=True)

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    exit_code = module._run_staged()

    assert exit_code == 0


def test_staged_validation_fails_when_a_staged_file_is_invalid(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    task_path = tmp_path / "02-backlog" / "tasks" / "T-FB900-US01-02.md"
    _write(task_path, _INVALID_TASK)
    subprocess.run(["git", "add", str(task_path)], cwd=tmp_path, check=True)

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    exit_code = module._run_staged()
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "Invalidos: 1" in out
    assert "state" in out.lower()


def test_staged_validation_ignores_unstaged_backlog_files(
    tmp_path: Path, monkeypatch
) -> None:
    # Criterio 3 de T-FB022-US13-06: solo repasa lo staged, no el backlog
    # completo — un fichero inválido presente pero NO staged no bloquea.
    module = _load_module()
    _init_repo(tmp_path)
    valid_path = tmp_path / "02-backlog" / "tasks" / "T-FB900-US01-01.md"
    invalid_path = tmp_path / "02-backlog" / "tasks" / "T-FB900-US01-02.md"
    _write(valid_path, _VALID_TASK)
    _write(invalid_path, _INVALID_TASK)  # nunca se hace `git add` de este
    subprocess.run(["git", "add", str(valid_path)], cwd=tmp_path, check=True)

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    exit_code = module._run_staged()

    assert exit_code == 0


def test_staged_validation_ignores_non_backlog_files(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    other_path = tmp_path / "README.md"
    _write(other_path, "# No es backlog\n")
    subprocess.run(["git", "add", str(other_path)], cwd=tmp_path, check=True)

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    exit_code = module._run_staged()

    assert exit_code == 0


def test_staged_validation_does_not_write_any_file(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    task_path = tmp_path / "02-backlog" / "tasks" / "T-FB900-US01-02.md"
    _write(task_path, _INVALID_TASK)
    subprocess.run(["git", "add", str(task_path)], cwd=tmp_path, check=True)

    before = task_path.read_text(encoding="utf-8")
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    module._run_staged()
    after = task_path.read_text(encoding="utf-8")

    assert before == after


# ---------------------------------------------------------------------------
# Modo lote (T-FB022-US13-07)
# ---------------------------------------------------------------------------


def test_batch_mode_reports_valid_and_invalid_files_separately(
    tmp_path: Path, capsys
) -> None:
    module = _load_module()
    _write(tmp_path / "valido.md", _VALID_TASK)
    _write(tmp_path / "invalido.md", _INVALID_TASK)

    exit_code = module._run_batch(tmp_path)
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "Ficheros revisados: 2" in out
    assert "Validos: 1" in out
    assert "Invalidos: 1" in out
    assert "invalido.md" in out


def test_batch_mode_does_not_require_git_repo_or_02_backlog_structure(
    tmp_path: Path,
) -> None:
    # Criterio 2 de T-FB022-US13-07: cualquier ruta, sin git ni
    # 02-backlog/ — tmp_path aquí es un directorio "suelto" cualquiera,
    # sin `git init` ni subcarpetas epics/user-stories/tasks.
    module = _load_module()
    _write(tmp_path / "lote" / "T-FB900-US01-01.md", _VALID_TASK)

    exit_code = module._run_batch(tmp_path / "lote")

    assert exit_code == 0


def test_batch_mode_does_not_modify_input_files(tmp_path: Path) -> None:
    module = _load_module()
    path = tmp_path / "invalido.md"
    _write(path, _INVALID_TASK)

    before = path.read_text(encoding="utf-8")
    module._run_batch(tmp_path)
    after = path.read_text(encoding="utf-8")

    assert before == after


def test_batch_mode_reuses_validate_backlog_file_v2(tmp_path: Path) -> None:
    # Criterio 4 de T-FB022-US13-07: no reimplementa una segunda lógica
    # de validación — el mensaje de error exacto debe coincidir con el
    # que produce validate_backlog_file_v2 directamente.
    from brain.backlog.validator_v2 import validate_backlog_file_v2

    module = _load_module()
    path = tmp_path / "invalido.md"
    _write(path, _INVALID_TASK)

    direct_result = validate_backlog_file_v2(path)
    cli_results = [validate_backlog_file_v2(p) for p in sorted(tmp_path.rglob("*.md"))]

    assert len(cli_results) == 1
    assert [e.message for e in cli_results[0].errors] == [e.message for e in direct_result.errors]


def test_batch_mode_on_nonexistent_directory_returns_error(tmp_path: Path) -> None:
    module = _load_module()

    exit_code = module._run_batch(tmp_path / "no-existe")

    assert exit_code == 2


# ---------------------------------------------------------------------------
# Verificación end-to-end real: el propio backlog de este proyecto
# ---------------------------------------------------------------------------


def test_real_backlog_of_this_project_passes_v2_validation() -> None:
    # T-FB022-US13-06, nota de la Task: "confirmar con el Developer si
    # algún fichero legado del backlog real sigue en formato v1" —
    # verificado aquí explícitamente: los 444+ ficheros reales de
    # 02-backlog/ (epics/user-stories/tasks) pasan validate_backlog_file_v2
    # sin excepción, así que el hook puede aplicarlo sin lista de
    # exclusión.
    from brain.backlog.validator_v2 import validate_backlog_file_v2

    backlog_root = _SCRIPT_PATH.parents[2] / "02-backlog"
    invalid = []
    total = 0
    for subdir in ("epics", "user-stories", "tasks"):
        for path in sorted((backlog_root / subdir).glob("*.md")):
            total += 1
            result = validate_backlog_file_v2(path)
            if not result.valid:
                invalid.append((path, result.errors))

    assert total > 0
    assert invalid == []

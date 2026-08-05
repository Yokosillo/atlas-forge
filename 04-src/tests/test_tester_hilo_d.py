"""Tests para el Hilo D de FB-022: contrato de entrada/salida del Tester
(T-FB022-US12-01, -02, -03, -04)."""

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from brain.dispatcher.job_report import read_job_report, write_job_report
from brain.dispatcher.tester_input import (
    _extract_acceptance_criteria,
    build_tester_input_package,
    build_tester_job_description,
    collect_changed_files,
    collect_developer_code_diff,
    read_acceptance_criteria,
)
from brain.models import Job
from brain.models.script_run_result import ScriptRunResult
from brain.workspace.generic_scripts import (
    _find_test_runner,
    _run_project_tests,
    list_generic_scripts,
    run_generic_script,
)


# ─── helpers ───────────────────────────────────────────────────────────

def _init_repo(repo_path: Path) -> None:
    subprocess.run(
        ["git", "-C", str(repo_path), "init"],
        capture_output=True, text=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "config", "user.name", "Test"],
        capture_output=True, text=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "config", "user.email", "test@test.com"],
        capture_output=True, text=True, check=True,
    )


def _write_task_file(tasks_dir: Path, task_id: str, content: str) -> Path:
    tasks_dir.mkdir(parents=True, exist_ok=True)
    path = tasks_dir / f"{task_id}.md"
    path.write_text(content, encoding="utf-8")
    return path


# ─── T-FB022-US12-01: Empaquetar entrada del Tester ────────────────────

class TestExtractAcceptanceCriteria:
    def test_extracts_from_task_with_criteria(self):
        text = (
            "## Objetivo\n\nHacer algo.\n\n"
            "## Criterios de aceptación\n\n"
            "1. Debe pasar el lint.\n"
            "2. Debe cubrir el caso borde.\n\n"
            "## Prioridad\n\nAlta.\n"
        )
        result = _extract_acceptance_criteria(text)
        assert "1. Debe pasar el lint." in result
        assert "2. Debe cubrir el caso borde." in result
        assert "Objetivo" not in result
        assert "Prioridad" not in result

    def test_returns_empty_when_no_criteria(self):
        text = "## Objetivo\n\nHacer algo.\n\n## Prioridad\n\nAlta.\n"
        assert _extract_acceptance_criteria(text) == ""

    def test_returns_empty_when_empty_text(self):
        assert _extract_acceptance_criteria("") == ""


class TestReadAcceptanceCriteria:
    def test_reads_criteria_from_task_files(self, tmp_path: Path):
        tasks_dir = tmp_path / "02-backlog" / "tasks"
        _write_task_file(tasks_dir, "T-FB022-US12-01-test", (
            "## Criterios de aceptación\n\n1. Criterio A.\n"
        ))
        _write_task_file(tasks_dir, "T-FB022-US12-02-test", (
            "## Criterios de aceptación\n\n1. Criterio B.\n2. Criterio C.\n"
        ))

        result = read_acceptance_criteria("FB022-US12", tasks_dir=tasks_dir)
        assert len(result) == 2
        assert result[0][0] == "T-FB022-US12-01-test"
        assert "Criterio A" in result[0][1]
        assert result[1][0] == "T-FB022-US12-02-test"
        assert "Criterio C" in result[1][1]

    def test_skips_tasks_without_criteria(self, tmp_path: Path):
        tasks_dir = tmp_path / "02-backlog" / "tasks"
        _write_task_file(tasks_dir, "T-FB022-US12-01-test", (
            "## Objetivo\n\nUn objetivo.\n## Estado\n\nTODO\n"
        ))

        result = read_acceptance_criteria("FB022-US12", tasks_dir=tasks_dir)
        assert len(result) == 0

    def test_returns_empty_for_missing_dir(self, tmp_path: Path):
        result = read_acceptance_criteria(
            "FB022-US12", tasks_dir=tmp_path / "nonexistent"
        )
        assert result == []

    def test_returns_empty_for_no_matching_tasks(self, tmp_path: Path):
        tasks_dir = tmp_path / "02-backlog" / "tasks"
        _write_task_file(tasks_dir, "T-FB999-US01-task", (
            "## Criterios de aceptación\n\n1. X.\n"
        ))

        result = read_acceptance_criteria("FB022-US12", tasks_dir=tasks_dir)
        assert result == []


class TestCollectDeveloperCodeDiff:
    def test_returns_diff_from_git_repo(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)
        (repo / "file.py").write_text("initial")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True)
        (repo / "file.py").write_text("modified")

        diff = collect_developer_code_diff(str(repo))
        assert "modified" in diff
        assert "initial" in diff

    def test_returns_empty_for_non_git_repo(self, tmp_path: Path):
        diff = collect_developer_code_diff(str(tmp_path))
        assert diff == ""

    def test_returns_empty_for_nonexistent_path(self):
        diff = collect_developer_code_diff("/nonexistent/path/12345")
        assert diff == ""


class TestCollectChangedFiles:
    def test_lists_changed_files(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)
        (repo / "a.py").write_text("a")
        (repo / "b.py").write_text("b")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True)
        (repo / "a.py").write_text("modified a")
        (repo / "b.py").write_text("modified b")

        files = collect_changed_files(str(repo))
        assert "a.py" in files
        assert "b.py" in files

    def test_returns_empty_for_non_git_repo(self, tmp_path: Path):
        files = collect_changed_files(str(tmp_path))
        assert files == []


class TestBuildTesterInputPackage:
    def test_package_includes_code_criteria_and_report(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)
        (repo / "src.py").write_text("print('hello')")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True)
        (repo / "src.py").write_text("print('hello world')")

        tasks_dir = tmp_path / "tasks"
        _write_task_file(tasks_dir, "T-FB022-US12-01-test", (
            "## Criterios de aceptación\n\n1. Criterio X.\n"
        ))

        reports_root = tmp_path / "07-informes"
        dev_job = Job(
            id="dev-job-123",
            session_id="s1",
            agent_id="dev-1",
            description="x",
            status="completed",
            result="Tests: 5/5 pasan.",
            story_id="FB022-US12",
        )
        write_job_report(dev_job, reports_root=reports_root)

        pkg = build_tester_input_package(
            "FB022-US12",
            "dev-job-123",
            str(repo),
            reports_root=reports_root,
            tasks_dir=tasks_dir,
        )

        assert pkg["story_id"] == "FB022-US12"
        assert pkg["developer_job_id"] == "dev-job-123"
        assert "hello world" in pkg["code_diff"]
        assert len(pkg["changed_files"]) >= 1
        assert len(pkg["acceptance_criteria"]) == 1
        assert "Tests: 5/5 pasan." in pkg["developer_report"]

    def test_package_does_not_include_epic(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)
        (repo / "f.py").write_text("x")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True)
        (repo / "f.py").write_text("y")

        reports_root = tmp_path / "07-informes"
        dev_job = Job(
            id="dev-job-456", session_id="s1", agent_id="dev-1",
            description="x", status="completed", result="ok",
            story_id="FB022-US12",
        )
        write_job_report(dev_job, reports_root=reports_root)

        pkg = build_tester_input_package(
            "FB022-US12", "dev-job-456", str(repo),
            reports_root=reports_root, tasks_dir=tmp_path / "tasks",
        )

        combined = str(pkg)
        assert "Epic" not in combined
        assert "FB-022" not in combined or "FB022-US12" in combined


# ─── T-FB022-US12-02: Generación de tests dirigidos a huecos ───────────

class TestBuildTesterJobDescription:
    def test_includes_gap_analysis_instruction(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)
        (repo / "x.py").write_text("x")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True)

        reports_root = tmp_path / "07-informes"
        dev_job = Job(
            id="dev-job-789", session_id="s1", agent_id="dev-1",
            description="x", status="completed",
            result="Tests ejecutados: test_a, test_b, test_c.",
            story_id="FB022-US12",
        )
        write_job_report(dev_job, reports_root=reports_root)

        tasks_dir = tmp_path / "tasks"
        _write_task_file(tasks_dir, "T-FB022-US12-01-test", (
            "## Criterios de aceptación\n\n1. El sistema debe validar X.\n"
        ))

        description = build_tester_job_description(
            "FB022-US12", "dev-job-789", str(repo),
            reports_root=reports_root, tasks_dir=tasks_dir,
        )

        assert "huecos de cobertura" in description
        assert "NO dupliques" in description
        assert "Tests ejecutados: test_a, test_b, test_c." in description
        assert "Criterios de aceptación" in description
        assert "Tester" in description

    def test_instruction_directs_not_to_duplicate(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)
        (repo / "x.py").write_text("x")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True)

        reports_root = tmp_path / "07-informes"
        dev_job = Job(
            id="dev-job-dup", session_id="s1", agent_id="dev-1",
            description="x", status="completed",
            result="Tests: test_login, test_logout.",
            story_id="FB022-US12",
        )
        write_job_report(dev_job, reports_root=reports_root)

        description = build_tester_job_description(
            "FB022-US12", "dev-job-dup", str(repo),
            reports_root=reports_root, tasks_dir=tmp_path / "tasks",
        )

        assert "NO dupliques" in description
        assert "test_login" in description

    def test_acceptance_criteria_fallback_message(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)
        (repo / "x.py").write_text("x")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True)

        reports_root = tmp_path / "07-informes"
        dev_job = Job(
            id="dev-job-fb", session_id="s1", agent_id="dev-1",
            description="x", status="completed", result="ok",
            story_id="FB022-US12",
        )
        write_job_report(dev_job, reports_root=reports_root)

        description = build_tester_job_description(
            "FB022-US12", "dev-job-fb", str(repo),
            reports_root=reports_root, tasks_dir=tmp_path / "tasks",
        )

        assert "no se encontraron criterios" in description.lower()


# ─── T-FB022-US12-03: Ejecución determinista de tests ──────────────────

class TestRunTestsGenericScript:
    def test_run_tests_appears_in_catalog(self):
        scripts = list_generic_scripts()
        ids = [s.id for s in scripts]
        assert "run_tests" in ids

    def test_run_tests_in_catalog_has_name(self):
        scripts = list_generic_scripts()
        run_entry = next(s for s in scripts if s.id == "run_tests")
        assert run_entry.name
        assert len(run_entry.name) > 0

    def test_find_test_runner_returns_pytest_if_available(self, tmp_path: Path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_dummy.py").write_text("def test_pass(): pass")

        command = _find_test_runner(str(tmp_path))
        assert command is not None
        assert "pytest" in command[0] or "pytest" in " ".join(command)

    def test_find_test_runner_returns_none_without_tests_dir(self, tmp_path: Path):
        command = _find_test_runner(str(tmp_path))
        assert command is None

    def test_run_project_tests_deterministic_on_pass(self, tmp_path: Path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_pass.py").write_text("def test_pass(): assert True")

        result = _run_project_tests(str(tmp_path))
        assert isinstance(result, ScriptRunResult)
        assert result.success
        assert result.exit_code == 0

    def test_run_project_tests_deterministic_on_fail(self, tmp_path: Path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_fail.py").write_text("def test_fail(): assert False")

        result = _run_project_tests(str(tmp_path))
        assert isinstance(result, ScriptRunResult)
        assert not result.success
        assert result.exit_code is not None
        assert result.exit_code != 0

    def test_run_project_tests_captures_output(self, tmp_path: Path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_output.py").write_text(
            "def test_output(): assert True"
        )

        result = _run_project_tests(str(tmp_path))
        assert "test_output" in result.stdout

    def test_run_generic_script_run_tests_integration(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)
        (repo / "readme.md").write_text("test project")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True)

        tests_dir = repo / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_dummy.py").write_text("def test_dummy(): assert True")

        result = run_generic_script("run_tests", str(repo))
        assert result.success
        assert result.exit_code == 0


# ─── T-FB022-US12-04: Informe de cierre del Tester ─────────────────────

class TestTesterReport:
    def test_tester_report_uses_same_mechanism_as_developer(self, tmp_path: Path):
        dev_job = Job(
            id="dev-001", session_id="s1", agent_id="dev-1",
            description="implementar", status="completed",
            result="Tests del Developer: test_a, test_b.",
            story_id="FB022-US12",
        )
        tester_job = Job(
            id="tester-001", session_id="s1", agent_id="tester-1",
            description="verificar", status="completed",
            result=(
                "Huecos detectados: falta test de borde.\n"
                "Tests generados: test_borde en test_edge.py.\n"
                "Resultado ejecución: test_borde PASSED."
            ),
            story_id="FB022-US12",
        )

        dev_path = write_job_report(dev_job, reports_root=tmp_path)
        tester_path = write_job_report(tester_job, reports_root=tmp_path)

        assert dev_path.exists()
        assert tester_path.exists()
        assert dev_path.parent == tester_path.parent

    def test_tester_report_never_in_same_file_as_developer(self, tmp_path: Path):
        dev_job = Job(
            id="dev-002", session_id="s1", agent_id="dev-2",
            description="x", status="completed", result="dev result",
            story_id="FB022-US12",
        )
        tester_job = Job(
            id="tester-002", session_id="s1", agent_id="tester-2",
            description="y", status="completed", result="tester result",
            story_id="FB022-US12",
        )

        write_job_report(dev_job, reports_root=tmp_path)
        write_job_report(tester_job, reports_root=tmp_path)

        dev_content = read_job_report(
            "FB022-US12", "dev-002", reports_root=tmp_path
        )
        tester_content = read_job_report(
            "FB022-US12", "tester-002", reports_root=tmp_path
        )

        assert "tester result" not in dev_content
        assert "dev result" not in tester_content

    def test_tester_report_has_own_job_id(self, tmp_path: Path):
        tester_job = Job(
            id="tester-uuid-1234", session_id="s1", agent_id="tester-3",
            description="test", status="completed",
            result="Huecos: ninguno. Tests: 0 nuevos.",
            story_id="FB022-US12",
        )

        path = write_job_report(tester_job, reports_root=tmp_path)
        assert "tester-uuid-1234" in path.name
        content = path.read_text()
        assert "tester-uuid-1234" in content

    def test_tester_report_documents_gaps_tests_and_execution(self, tmp_path: Path):
        tester_job = Job(
            id="tester-rpt", session_id="s1", agent_id="tester-4",
            description="test", status="completed",
            result=(
                "Huecos de cobertura detectados:\n"
                "- Caso borde: entrada vacía\n"
                "- Path: error handling en save()\n\n"
                "Tests generados:\n"
                "- test_empty_input en test_edge.py\n"
                "- test_save_error en test_error.py\n\n"
                "Resultado de ejecución:\n"
                "- test_empty_input: PASSED\n"
                "- test_save_error: FAILED (mock no configurado)"
            ),
            story_id="FB022-US12",
        )

        path = write_job_report(tester_job, reports_root=tmp_path)
        content = path.read_text()

        assert "Huecos de cobertura detectados" in content
        assert "test_empty_input" in content
        assert "test_save_error" in content
        assert "PASSED" in content
        assert "FAILED" in content
        assert "mock no configurado" in content

    def test_concurrent_dev_and_tester_reports_do_not_collide(self, tmp_path: Path):
        import threading

        dev_job = Job(
            id="dev-concurrent", session_id="s1", agent_id="dev-5",
            description="x", status="completed", result="dev concurrent",
            story_id="FB022-US12",
        )
        tester_job = Job(
            id="tester-concurrent", session_id="s1", agent_id="tester-5",
            description="y", status="completed", result="tester concurrent",
            story_id="FB022-US12",
        )

        errors: list[Exception] = []

        def _write(job):
            try:
                write_job_report(job, reports_root=tmp_path)
            except Exception as e:
                errors.append(e)

        t0 = threading.Thread(target=_write, args=(dev_job,))
        t1 = threading.Thread(target=_write, args=(tester_job,))
        t0.start()
        t1.start()
        t0.join()
        t1.join()

        assert len(errors) == 0

        dev_content = read_job_report(
            "FB022-US12", "dev-concurrent", reports_root=tmp_path
        )
        tester_content = read_job_report(
            "FB022-US12", "tester-concurrent", reports_root=tmp_path
        )

        assert "dev concurrent" in dev_content
        assert "tester concurrent" in tester_content
        assert "tester concurrent" not in dev_content
        assert "dev concurrent" not in tester_content

"""Tests de T-FB001-US03-02: ejecutar un script catalogado del proyecto
como subproceso real — nunca mockeando `subprocess.run` ni el comando en
sí (mismo criterio de "comportamiento real" ya aplicado en el resto del
proyecto, ver `test_project_scripts.py`): se escribe un manifiesto real a
disco y se ejecuta un comando de shell real e inocuo (`echo`/`exit`,
nunca un binario externo con efectos)."""

from pathlib import Path

from brain.workspace.project_scripts import MANIFEST_RELATIVE_PATH, run_project_script


def _write_manifest(project_path: Path, content: str) -> None:
    manifest_path = project_path / MANIFEST_RELATIVE_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(content, encoding="utf-8")


def test_running_a_valid_catalogued_script_returns_its_output_and_exit_code(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        """
        scripts:
          - id: greet
            name: "Greet"
            command: "echo hello-from-script"
        """,
    )

    result = run_project_script("greet", str(tmp_path))

    assert result.success is True
    assert result.exit_code == 0
    assert "hello-from-script" in result.stdout
    assert result.error_message is None


def test_running_an_unknown_script_id_returns_an_explicit_error_result(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        """
        scripts:
          - id: greet
            name: "Greet"
            command: "echo hello"
        """,
    )

    result = run_project_script("does-not-exist", str(tmp_path))

    assert result.success is False
    assert result.exit_code is None
    assert result.error_message is not None
    assert "does-not-exist" in result.error_message


def test_running_a_script_id_when_there_is_no_manifest_at_all_returns_an_explicit_error(
    tmp_path: Path,
) -> None:
    result = run_project_script("anything", str(tmp_path))

    assert result.success is False
    assert result.exit_code is None
    assert result.error_message is not None


def test_a_script_that_fails_reports_its_nonzero_exit_code_and_output_for_diagnosis(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        """
        scripts:
          - id: broken
            name: "Broken"
            command: "echo something-went-wrong >&2; exit 3"
        """,
    )

    result = run_project_script("broken", str(tmp_path))

    assert result.success is False
    assert result.exit_code == 3
    assert "something-went-wrong" in result.stderr


def test_a_malformed_manifest_returns_an_explicit_error_result_not_an_unhandled_exception(
    tmp_path: Path,
) -> None:
    _write_manifest(tmp_path, "scripts: not-a-list\n")

    result = run_project_script("anything", str(tmp_path))

    assert result.success is False
    assert result.exit_code is None
    assert result.error_message is not None


def test_a_script_that_exceeds_the_timeout_returns_an_explicit_error_result(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        """
        scripts:
          - id: slow
            name: "Slow"
            command: "sleep 5"
        """,
    )

    result = run_project_script("slow", str(tmp_path), timeout_seconds=0.2)

    assert result.success is False
    assert result.exit_code is None
    assert "timeout" in result.error_message.lower()


def test_the_script_runs_with_the_project_path_as_its_working_directory(
    tmp_path: Path,
) -> None:
    (tmp_path / "marker.txt").write_text("found-me", encoding="utf-8")
    _write_manifest(
        tmp_path,
        """
        scripts:
          - id: read-marker
            name: "Read marker"
            command: "cat marker.txt"
        """,
    )

    result = run_project_script("read-marker", str(tmp_path))

    assert result.success is True
    assert "found-me" in result.stdout

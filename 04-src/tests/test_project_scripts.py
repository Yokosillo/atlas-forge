"""Tests de T-FB001-US03-01: catalogación de scripts particulares del
proyecto activo — `discover_project_scripts(project_path) -> list[ScriptEntry]`,
leyendo el manifiesto real `.factory-brain/scripts.yml` (nunca un mock del
parseo YAML: se escribe el fichero real a disco y se lee con el parser
real, mismo criterio de "comportamiento real" ya aplicado en el resto del
proyecto)."""

from pathlib import Path

import pytest

from brain.models import ScriptEntry
from brain.workspace.project_scripts import (
    MANIFEST_RELATIVE_PATH,
    MalformedScriptManifestError,
    discover_project_scripts,
)


def _write_manifest(project_path: Path, content: str) -> None:
    manifest_path = project_path / MANIFEST_RELATIVE_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(content, encoding="utf-8")


def test_a_project_without_a_manifest_returns_an_empty_list_without_error(
    tmp_path: Path,
) -> None:
    result = discover_project_scripts(str(tmp_path))

    assert result == []


def test_a_valid_manifest_returns_the_declared_scripts_with_their_minimum_fields(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        """
        scripts:
          - id: lint
            name: "Lint del proyecto"
            command: "ruff check ."
            description: "Ejecuta el linter sobre todo el código."
          - id: tests
            name: "Suite de tests"
            command: "pytest"
        """,
    )

    result = discover_project_scripts(str(tmp_path))

    assert result == [
        ScriptEntry(
            id="lint",
            name="Lint del proyecto",
            command="ruff check .",
            description="Ejecuta el linter sobre todo el código.",
        ),
        ScriptEntry(id="tests", name="Suite de tests", command="pytest"),
    ]


def test_description_defaults_to_empty_string_when_omitted(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        """
        scripts:
          - id: build
            name: "Build"
            command: "make build"
        """,
    )

    result = discover_project_scripts(str(tmp_path))

    assert result[0].description == ""


def test_an_empty_manifest_file_is_treated_as_no_scripts_declared(
    tmp_path: Path,
) -> None:
    _write_manifest(tmp_path, "")

    result = discover_project_scripts(str(tmp_path))

    assert result == []


def test_invalid_yaml_raises_malformed_manifest_error_with_a_clear_message(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        """
        scripts:
          - id: lint
            name: [this is not valid yaml
        """,
    )

    with pytest.raises(MalformedScriptManifestError) as excinfo:
        discover_project_scripts(str(tmp_path))

    assert "no es YAML válido" in str(excinfo.value)


def test_manifest_without_a_scripts_root_key_raises_malformed_manifest_error(
    tmp_path: Path,
) -> None:
    _write_manifest(tmp_path, "not_scripts:\n  - id: lint\n")

    with pytest.raises(MalformedScriptManifestError) as excinfo:
        discover_project_scripts(str(tmp_path))

    assert "scripts" in str(excinfo.value)


def test_manifest_where_scripts_is_not_a_list_raises_malformed_manifest_error(
    tmp_path: Path,
) -> None:
    _write_manifest(tmp_path, "scripts: not-a-list\n")

    with pytest.raises(MalformedScriptManifestError):
        discover_project_scripts(str(tmp_path))


def test_a_script_entry_missing_a_required_field_raises_malformed_manifest_error(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        """
        scripts:
          - id: lint
            name: "Lint del proyecto"
        """,
    )

    with pytest.raises(MalformedScriptManifestError) as excinfo:
        discover_project_scripts(str(tmp_path))

    assert "command" in str(excinfo.value)


def test_a_script_entry_that_is_not_an_object_raises_malformed_manifest_error(
    tmp_path: Path,
) -> None:
    _write_manifest(tmp_path, "scripts:\n  - just a string, not an object\n")

    with pytest.raises(MalformedScriptManifestError):
        discover_project_scripts(str(tmp_path))

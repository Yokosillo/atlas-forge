"""Tests de T-AF036-US25-03 (US-AF036-25): la validación de `version` como
conjunto cerrado {0.9, 0.9.1, 0.9.2} en validador/parser/creación/endpoint, y
la deprecación de `fase` (no asignable por creación).

Cubre los 4 criterios de la Task:
1. Validador: `version` válidas aceptadas; fuera del conjunto rechazadas
   (Epic y User Story).
2. Parser y creación con `version` válida/ilegal.
3. Endpoint `PUT /backlog/{item_id}/version` (200 válida, 400 ilegal sin tocar
   disco).
4. `fase` ya no es asignable por creación (deprecación).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import atlas_forge.api.routes as routes_module
from atlas_forge.api import create_app
from atlas_forge.backlog.create import create_epic, create_user_story
from atlas_forge.backlog.parser import parse_backlog_item
from atlas_forge.backlog.validator_v2 import validate_backlog_content_v2
from atlas_forge.models import Project

from atlas_forge.backlog.create import InvalidFieldValueError


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _epic_file(backlog: Path, epic_id: str = "AF-100", version: str | None = "0.9") -> Path:
    version_line = f"version: {version}\n" if version is not None else ""
    path = backlog / "epics" / f"{epic_id}-epic.md"
    _write(
        path,
        "---\n"
        f"id: {epic_id}\ntype: epic\ntitle: {epic_id}\nstate: TO_DO\n"
        f"dependencies: []\n{version_line}"
        "---\n\n## Objetivo\n\nObjetivo.\n",
    )
    return path


def _us_file(
    backlog: Path,
    us_id: str = "US-AF100-01",
    version: str | None = "0.9",
    fase: str | None = None,
) -> Path:
    version_line = f"version: {version}\n" if version is not None else ""
    fase_line = f"fase: {fase}\n" if fase is not None else ""
    path = backlog / "user-stories" / f"{us_id}.md"
    _write(
        path,
        "---\n"
        f"id: {us_id}\ntype: user_story\ntitle: {us_id}\nstate: READY\n"
        f"dependencies: []\nepic: AF-100\npriority: Alta\n{version_line}{fase_line}"
        "---\n\n## Historia\n\nHistoria.\n",
    )
    return path


# ---------------------------------------------------------------------------
# Criterio 1: validador — version válida/ilegal para Epic y User Story.
# ---------------------------------------------------------------------------


def test_validator_accepts_valid_versions_for_epic_and_us() -> None:
    # (filename, id, version)
    cases = [
        ("AF-100.md", "AF-100", "0.9"),
        ("US-AF100-01.md", "US-AF100-01", "0.9.1"),
        ("US-AF100-01.md", "US-AF100-01", "0.9.2"),
    ]
    for filename, item_id, version in cases:
        body = (
            "---\n"
            f"id: {item_id}\ntype: user_story\ntitle: X\nstate: READY\n"
            f"dependencies: []\nepic: AF-100\npriority: Alta\nversion: {version}\n"
            "---\n\n## Historia\n\nH.\n"
        )
        result = validate_backlog_content_v2(body, filename)
        assert result.valid, f"{filename} {version}: {result.errors}"


def test_validator_rejects_out_of_set_version_for_epic_and_us() -> None:
    for bad in ("0.8", "1.0", "Fase 0.9"):
        # Epic
        epic = (
            "---\nid: AF-100\ntype: epic\ntitle: X\nstate: TO_DO\n"
            f"dependencies: []\nversion: {bad}\n---\n\n## Objetivo\n\nO.\n"
        )
        res = validate_backlog_content_v2(epic, "AF-100.md")
        assert not res.valid, f"epic version {bad} debía ser inválida"
        assert any("version" in e.message.lower() for e in res.errors)
        # User Story
        us = (
            "---\nid: US-AF100-01\ntype: user_story\ntitle: X\nstate: READY\n"
            f"dependencies: []\nepic: AF-100\npriority: Alta\nversion: {bad}\n"
            "---\n\n## Historia\n\nH.\n"
        )
        res = validate_backlog_content_v2(us, "US-AF100-01.md")
        assert not res.valid, f"us version {bad} debía ser inválida"
        assert any("version" in e.message.lower() for e in res.errors)


def test_validator_accepts_float_version_0_9_normalized() -> None:
    # `version: 0.9` sin comillas lo lee PyYAML como float — se normaliza a
    # "0.9" y pasa (mismo criterio que el parser).
    epic = (
        "---\nid: AF-100\ntype: epic\ntitle: X\nstate: TO_DO\n"
        "dependencies: []\nversion: 0.9\n---\n\n## Objetivo\n\nO.\n"
    )
    result = validate_backlog_content_v2(epic, "AF-100.md")
    assert result.valid, f"Errores: {result.errors}"


# ---------------------------------------------------------------------------
# Criterio 2: parser y creación con version válida/ilegal.
# ---------------------------------------------------------------------------


def test_parser_reads_version_for_epic_and_us(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    _epic_file(backlog, version="0.9.1")
    _us_file(backlog, version="0.9.2")

    epic = parse_backlog_item(backlog / "epics" / "AF-100-epic.md")
    assert epic.version == "0.9.1"
    us = parse_backlog_item(backlog / "user-stories" / "US-AF100-01.md")
    assert us.version == "0.9.2"


def test_parser_normalizes_float_version(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    path = _epic_file(backlog, version="0.9")
    content = path.read_text(encoding="utf-8").replace("version: 0.9", "version: 0.9")
    # Reescritura explícita con valor numérico sin comillas.
    _write(path, content)
    epic = parse_backlog_item(path)
    assert epic.version == "0.9"


def test_create_user_story_writes_valid_version_and_no_fase(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-100", "Epic", "Objetivo.")
    path = create_user_story(
        backlog, "AF-100", "US-AF100-01", "US", "Historia.", "Criterios.", version="0.9.2"
    )
    content = path.read_text(encoding="utf-8")
    assert "version: 0.9.2" in content
    assert "fase:" not in content  # `fase` ya no se escribe por creación.
    assert validate_backlog_content_v2(content, path.name).valid


def test_create_user_story_rejects_out_of_set_version_without_touching_disk(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-100", "Epic", "Objetivo.")
    with pytest.raises(InvalidFieldValueError):
        create_user_story(
            backlog, "AF-100", "US-AF100-01", "US", "Historia.", "Criterios.", version="1.0"
        )
    assert not (backlog / "user-stories").exists()


# ---------------------------------------------------------------------------
# Criterio 3: endpoint PUT /backlog/{item_id}/version.
# ---------------------------------------------------------------------------


def _active_project(tmp_path: Path, monkeypatch) -> Path:
    project_path = tmp_path / "workspace" / "project-a"
    project_path.mkdir(parents=True, exist_ok=True)
    project = Project(
        id=str(project_path), name="project-a", path=str(project_path),
        repository="", workspace_id="ws-test",
    )
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)
    return project_path


def _seed_backlog(project_path: Path) -> None:
    backlog = project_path / "02-backlog"
    (backlog / "epics").mkdir(parents=True, exist_ok=True)
    (backlog / "user-stories").mkdir(parents=True, exist_ok=True)
    _epic_file(backlog)
    _us_file(backlog)


def test_endpoint_put_version_200_valid(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    resp = client.put("/backlog/US-AF100-01/version", json={"version": "0.9.2"})
    assert resp.status_code == 200
    assert resp.json()["version"] == "0.9.2"
    assert "version: 0.9.2" in (project_path / "02-backlog" / "user-stories" / "US-AF100-01.md").read_text(encoding="utf-8")


def test_endpoint_put_version_400_illegal_without_touching_disk(tmp_path: Path, monkeypatch) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(project_path)
    client = TestClient(create_app())

    resp = client.put("/backlog/US-AF100-01/version", json={"version": "0.8"})
    assert resp.status_code == 400
    assert "no es una versión válida" in resp.json()["detail"]
    # No se tocó disco: sigue con la version original.
    content = (project_path / "02-backlog" / "user-stories" / "US-AF100-01.md").read_text(encoding="utf-8")
    assert "version: 0.9" in content
    assert "version: 0.8" not in content


# ---------------------------------------------------------------------------
# Criterio 4: `fase` deprecada — no asignable por creación.
# ---------------------------------------------------------------------------


def test_create_user_story_no_longer_accepts_fase_kwarg(tmp_path: Path) -> None:
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-100", "Epic", "Objetivo.")
    # `fase` ya no es parámetro de `create_user_story` (se sustituyó por
    # `version`): pasarla es un TypeError, no una asignación silenciosa.
    with pytest.raises(TypeError):
        create_user_story(  # type: ignore[call-arg]
            backlog, "AF-100", "US-AF100-01", "US", "Historia.", "Criterios.", fase="Fase 0.9"
        )


def test_validator_tolerates_legacy_fase_but_creation_never_writes_it(tmp_path: Path) -> None:
    # `fase` legacy en datos persistidos se tolera (validación)...
    legacy = (
        "---\nid: US-AF100-01\ntype: user_story\ntitle: X\nstate: READY\n"
        "dependencies: []\nepic: AF-100\npriority: Alta\nfase: Fase 0.9\n"
        "---\n\n## Historia\n\nH.\n"
    )
    assert validate_backlog_content_v2(legacy, "US-AF100-01.md").valid
    # ...pero la creación con `version` nunca escribe `fase`.
    backlog = tmp_path / "02-backlog"
    create_epic(backlog, "AF-100", "Epic", "Objetivo.")
    path = create_user_story(
        backlog, "AF-100", "US-AF100-01", "US", "Historia.", "Criterios.", version="0.9"
    )
    assert "fase:" not in path.read_text(encoding="utf-8")
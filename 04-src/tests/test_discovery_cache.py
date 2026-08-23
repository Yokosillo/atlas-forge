"""Tests de T-AF001-US01-06: caché TTL para `discover_projects` y
`discover_project_scripts` — verifica que varias llamadas seguidas no repiten
el recorrido del filesystem, que los cambios se ven tras expirar el TTL, y
que los errores NO se cachean."""

import os
import time
from pathlib import Path

import pytest

import atlas_forge.workspace.discovery as discovery_module
import atlas_forge.workspace.project_scripts as project_scripts_module
from atlas_forge.workspace import discover_projects
from atlas_forge.workspace.discovery import invalidate_discovery_cache
from atlas_forge.workspace.project_scripts import (
    MANIFEST_RELATIVE_PATH,
    MalformedScriptManifestError,
    discover_project_scripts,
    invalidate_project_scripts_cache,
)


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def _write_manifest(project_path: Path, content: str) -> None:
    manifest_path = project_path / MANIFEST_RELATIVE_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(content, encoding="utf-8")


@pytest.fixture(autouse=True)
def _short_ttl(monkeypatch):
    """TTL corto para que los tests no esperen 5s reales."""
    monkeypatch.setattr(discovery_module._PROJECTS_CACHE, "_ttl_seconds", 0.05)
    monkeypatch.setattr(project_scripts_module._SCRIPTS_CACHE, "_ttl_seconds", 0.05)
    yield
    invalidate_discovery_cache()
    invalidate_project_scripts_cache()


def test_discover_projects_does_not_repeat_os_walk_within_ttl(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio 1: llamadas seguidas dentro del TTL no repiten el recorrido
    del filesystem (contador sobre `os.walk`)."""
    _make_git_repo(tmp_path / "alfa")
    calls = {"n": 0}
    real_walk = os.walk

    def counting_walk(*args, **kwargs):
        calls["n"] += 1
        return real_walk(*args, **kwargs)

    monkeypatch.setattr(discovery_module.os, "walk", counting_walk)

    first = discover_projects(tmp_path)
    second = discover_projects(tmp_path)
    third = discover_projects(tmp_path)

    assert [p.name for p in first] == ["alfa"]
    assert second == first
    assert third == first
    # Solo la primera llamada recorrió el filesystem: las otras dos vinieron
    # de la caché dentro del TTL.
    assert calls["n"] == 1


def test_discover_projects_walks_again_after_ttl_expires(tmp_path: Path) -> None:
    """Criterio 2: un repo nuevo se ve tras expirar el TTL (sin reiniciar
    nada) — el estado en disco gana al caché caducado."""
    _make_git_repo(tmp_path / "alfa")
    assert [p.name for p in discover_projects(tmp_path)] == ["alfa"]

    time.sleep(0.07)  # > TTL
    _make_git_repo(tmp_path / "zeta")

    assert {p.name for p in discover_projects(tmp_path)} == {"alfa", "zeta"}


def test_new_script_appears_after_ttl_expires(tmp_path: Path) -> None:
    """Criterio 2 (scripts): un script añadido al manifiesto aparece en el
    catálogo tras expirar el TTL, sin reiniciar el backend."""
    project = tmp_path / "proj"
    project.mkdir()
    _write_manifest(
        project,
        "scripts:\n  - id: lint\n    name: Lint\n    command: ruff\n",
    )
    assert [s.id for s in discover_project_scripts(str(project))] == ["lint"]

    time.sleep(0.07)  # > TTL
    _write_manifest(
        project,
        "scripts:\n"
        "  - id: lint\n    name: Lint\n    command: ruff\n"
        "  - id: tests\n    name: Tests\n    command: pytest\n",
    )

    assert {s.id for s in discover_project_scripts(str(project))} == {"lint", "tests"}


def test_a_new_repo_is_seen_without_waiting_for_ttl(tmp_path: Path) -> None:
    """Criterio 3 (proyectos): crear un repo a primer nivel se ve al instante
    gracias al validador de contenido del root, sin esperar al TTL (mismo
    efecto que invalidar — cubre el patrón de los tests/uso real que crean o
    borran repos a mitad de sesión)."""
    _make_git_repo(tmp_path / "alfa")
    assert [p.name for p in discover_projects(tmp_path)] == ["alfa"]

    _make_git_repo(tmp_path / "zeta")  # sin esperar al TTL
    assert {p.name for p in discover_projects(tmp_path)} == {"alfa", "zeta"}

    # Borrar un repo también se refleja al instante (no sirve el viejo).
    import shutil

    shutil.rmtree(tmp_path / "alfa")
    assert [p.name for p in discover_projects(tmp_path)] == ["zeta"]


def test_invalidating_the_cache_reflects_changes_without_waiting_for_ttl(
    tmp_path: Path,
) -> None:
    """Criterio 3: invalidar la caché (lo que hace `POST /project` al cambiar
    de proyecto activo) refleja los cambios sin esperar al TTL anterior."""
    project = tmp_path / "proj"
    project.mkdir()
    _write_manifest(project, "scripts:\n  - id: lint\n    name: Lint\n    command: ruff\n")
    assert [s.id for s in discover_project_scripts(str(project))] == ["lint"]

    # Sin esperar al TTL: invalidar y añadir un script -> se ve al instante.
    invalidate_project_scripts_cache()
    _write_manifest(
        project,
        "scripts:\n"
        "  - id: lint\n    name: Lint\n    command: ruff\n"
        "  - id: tests\n    name: Tests\n    command: pytest\n",
    )
    assert {s.id for s in discover_project_scripts(str(project))} == {"lint", "tests"}

    # Mismo comportamiento para discovery de proyectos.
    _make_git_repo(tmp_path / "alfa")
    discover_projects(tmp_path)
    invalidate_discovery_cache()
    _make_git_repo(tmp_path / "zeta")
    assert {p.name for p in discover_projects(tmp_path)} == {"alfa", "zeta"}


def test_errors_are_not_cached(tmp_path: Path) -> None:
    """Criterio: no cachear errores — un manifiesto roto se reintenta de
    verdad en el siguiente intento, no se sirve el fallo cacheado."""
    project = tmp_path / "proj"
    project.mkdir()
    _write_manifest(project, "scripts: [esto no es yaml válido\n")

    with pytest.raises(MalformedScriptManifestError):
        discover_project_scripts(str(project))

    # Arreglar el manifiesto: la siguiente llamada (dentro del TTL) debe
    # releer el fichero y devolver el contenido válido, no el fallo anterior.
    _write_manifest(project, "scripts:\n  - id: lint\n    name: Lint\n    command: ruff\n")
    assert [s.id for s in discover_project_scripts(str(project))] == ["lint"]

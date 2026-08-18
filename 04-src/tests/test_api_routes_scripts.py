"""Tests de `GET /scripts`/`POST /scripts/{script_id}/run` (T-FB001-US03-03,
T-FB018-US01-03): envoltura fina de `discover_project_scripts`/
`run_project_script` (T-FB001-US03-01/02) y `list_generic_scripts`/
`run_generic_script` (T-FB018-US01-01/02) sobre el proyecto activo — nunca
contra un manifiesto mockeado, se escribe uno real a disco y se ejecutan
comandos de shell reales (mismo criterio de "comportamiento real" ya
aplicado en el resto del proyecto).

## ADVERTENCIA DE SEGURIDAD (heredada de `test_generic_scripts.py`)

Los tests que ejecutan `commit`/`push` (scripts genéricos) operan SIEMPRE
sobre un repositorio git temporal aislado creado con `tmp_path` + `git
init`, NUNCA sobre el repositorio real de Factory Brain: `commit`/`push`
tienen efectos reales, y ningún test debe tocarlos sobre un repo real."""

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import brain.api.routes as routes_module
from brain.api import create_app
from brain.workspace.project_scripts import MANIFEST_RELATIVE_PATH


def _make_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def _init_real_git_repo(path: Path) -> None:
    """Crea un repositorio git REAL y aislado en `path` (con identidad de
    usuario configurada para que `git commit` funcione) — los tests de
    `commit`/`push` SIEMPRE usan esto, nunca el repo real de Factory
    Brain."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test Worker"], check=True
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test-worker@example.invalid"],
        check=True,
    )


def _write_manifest(project_path: Path, content: str) -> None:
    manifest_path = project_path / MANIFEST_RELATIVE_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(content, encoding="utf-8")


def _active_project(tmp_path: Path, monkeypatch) -> Path:
    """Activa un proyecto real y aislado (nunca el filesystem real del
    usuario) haciendo que `routes.get_active_project` (el que consulta
    el endpoint) lo devuelva — mismo patrón ya usado en
    `test_api_routes_agents.py`."""
    project_path = tmp_path / "workspace" / "project-a"
    _make_git_repo(project_path)

    from brain.models import Project

    project = Project(id=str(project_path), name="project-a", path=str(project_path), repository="", workspace_id="ws-test")
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)
    return project_path


def _generic_ids() -> list[str]:
    from brain.workspace.generic_scripts import list_generic_scripts

    return [entry.id for entry in list_generic_scripts()]


def test_get_scripts_returns_404_when_no_project_is_active(monkeypatch) -> None:
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: None)
    client = TestClient(create_app())

    response = client.get("/scripts")

    assert response.status_code == 404


def test_get_scripts_returns_the_generic_catalog_for_a_project_without_a_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación de T-FB018-US01-03: "un proyecto sin scripts
    particulares sigue mostrando el catálogo genérico con normalidad (no
    depende de que existan ambos)" — sin manifiesto, `GET /scripts` devuelve
    el catálogo genérico completo, cada entrada con `origin: "generic"`."""
    _active_project(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.get("/scripts")

    assert response.status_code == 200
    body = response.json()
    assert [entry["id"] for entry in body] == _generic_ids()
    assert all(entry["origin"] == "generic" for entry in body)
    # Los genéricos no tienen comando (ninguno ejecuta un subproceso declarado
    # externamente), pero sí descripción (T-FB024-US03-01).
    assert all(entry["command"] is None for entry in body)
    assert all(
        isinstance(entry.get("description"), str) and entry["description"].strip()
        for entry in body
    )


def test_get_scripts_returns_both_catalogs_distinguishable_by_origin(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio 1 de T-FB018-US01-03: `GET /scripts` devuelve ambos
    catálogos (genéricos + particulares) juntos, distinguibles por el campo
    `origin` — no fusionados en una lista indistinguible."""
    project_path = _active_project(tmp_path, monkeypatch)
    _write_manifest(
        project_path,
        """
        scripts:
          - id: lint
            name: "Lint"
            command: "ruff check ."
            description: "Ejecuta el linter."
        """,
    )
    client = TestClient(create_app())

    response = client.get("/scripts")

    assert response.status_code == 200
    body = response.json()
    by_id = {entry["id"]: entry for entry in body}
    # Ambos catálogos presentes, cada entrada con su origen.
    assert set(by_id) == set(_generic_ids()) | {"lint"}
    assert by_id["lint"]["origin"] == "particular"
    assert by_id["lint"]["command"] == "ruff check ."
    assert by_id["commit"]["origin"] == "generic"
    assert by_id["commit"]["command"] is None


def test_get_scripts_returns_400_with_the_real_domain_message_for_a_malformed_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _write_manifest(project_path, "scripts: not-a-list\n")
    client = TestClient(create_app())

    response = client.get("/scripts")

    assert response.status_code == 400
    assert "scripts" in response.json()["detail"]


def test_post_script_run_returns_404_when_no_project_is_active(monkeypatch) -> None:
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: None)
    client = TestClient(create_app())

    response = client.post("/scripts/anything/run")

    assert response.status_code == 404


def test_post_script_run_executes_a_valid_script_and_returns_its_output(
    tmp_path: Path, monkeypatch
) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _write_manifest(
        project_path,
        """
        scripts:
          - id: greet
            name: "Greet"
            command: "echo hello-from-api"
        """,
    )
    client = TestClient(create_app())

    response = client.post("/scripts/greet/run")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["exit_code"] == 0
    assert "hello-from-api" in body["stdout"]


def test_post_script_run_with_unknown_script_id_returns_200_with_an_error_result(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación explícito: 'un script_id que no existe se
    rechaza con un mensaje claro, sin excepción no controlada' — a nivel
    HTTP esto es un resultado estructurado (200 con `success=False`), no
    un código de error HTTP: la petición en sí fue válida, el catalogado
    simplemente no encontró el id (mismo criterio ya verificado en
    dominio, `run_project_script`, T-FB001-US03-02)."""
    _active_project(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post("/scripts/does-not-exist/run")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["exit_code"] is None
    assert "does-not-exist" in body["error_message"]


def test_post_script_run_reflects_a_failing_script_with_its_reason_without_breaking(
    tmp_path: Path, monkeypatch
) -> None:
    project_path = _active_project(tmp_path, monkeypatch)
    _write_manifest(
        project_path,
        """
        scripts:
          - id: broken
            name: "Broken"
            command: "echo failure-reason >&2; exit 3"
        """,
    )
    client = TestClient(create_app())

    response = client.post("/scripts/broken/run")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["exit_code"] == 3
    assert "failure-reason" in body["stderr"]


# ---------------------------------------------------------------------------
# T-FB018-US01-03: ejecutar scripts GENÉRICOS vía API. `commit`/`push`
# SIEMPRE sobre un repo git temporal aislado, nunca sobre el repo real.
# ---------------------------------------------------------------------------


def test_post_script_run_executes_a_generic_script_without_params(tmp_path: Path, monkeypatch) -> None:
    """Un script genérico sin parámetros (`changed_files`) se ejecuta con un
    POST sin body, igual que los particulares."""
    repo_path = tmp_path / "workspace" / "project-a"
    _init_real_git_repo(repo_path)
    (repo_path / "file.txt").write_text("v1", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_path), "add", "file.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-q", "-m", "add file.txt"], check=True
    )
    # Modificación real tras el commit (sin commitearla).
    (repo_path / "file.txt").write_text("v2", encoding="utf-8")

    from brain.models import Project

    project = Project(id=str(repo_path), name="project-a", path=str(repo_path), repository="", workspace_id="ws-test")
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)
    client = TestClient(create_app())

    response = client.post("/scripts/changed_files/run")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["exit_code"] == 0
    assert "file.txt" in body["stdout"]


def test_post_script_run_commit_requires_a_message_and_performs_a_real_commit(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio 2 de T-FB018-US01-03: ejecutar `commit` pide el mensaje, y
    el commit REAL se realiza con ese mensaje — SIEMPRE sobre un repo git
    temporal aislado (`git init` + identidad configurada), nunca sobre el
    repo real de Factory Brain."""
    repo_path = tmp_path / "workspace" / "project-a"
    _init_real_git_repo(repo_path)
    (repo_path / "file.txt").write_text("v1", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_path), "add", "file.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-q", "-m", "add file.txt"], check=True
    )
    # Cambio real pendiente de comitear.
    (repo_path / "file.txt").write_text("v2", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_path), "add", "file.txt"], check=True)

    from brain.models import Project

    project = Project(id=str(repo_path), name="project-a", path=str(repo_path), repository="", workspace_id="ws-test")
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)
    client = TestClient(create_app())

    response = client.post(
        "/scripts/commit/run", json={"message": "mi commit desde la API"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["exit_code"] == 0
    # Verificación real: el último commit del repo temporal aislado tiene el
    # mensaje pedido.
    log = subprocess.run(
        ["git", "-C", str(repo_path), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert log == "mi commit desde la API"


def test_post_script_run_commit_without_a_message_is_rejected_with_an_explicit_result(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio 2: `commit` sin mensaje se rechaza de forma explícita — como
    resultado estructurado (200 con `success=False`), no un error de HTTP:
    la petición fue válida, el script simplemente no se pudo ejecutar sin su
    parámetro. Mismo criterio que el resto de fallos de `ScriptRunResult`."""
    repo_path = tmp_path / "workspace" / "project-a"
    _init_real_git_repo(repo_path)

    from brain.models import Project

    project = Project(id=str(repo_path), name="project-a", path=str(repo_path), repository="", workspace_id="ws-test")
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)
    client = TestClient(create_app())

    response = client.post("/scripts/commit/run")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["exit_code"] is None
    assert "message" in body["error_message"]


def test_post_script_run_commit_with_an_empty_message_is_rejected(tmp_path: Path, monkeypatch) -> None:
    """`message` vacío cuenta como ausente (mismo criterio que
    `run_generic_script`, T-FB018-US01-01)."""
    repo_path = tmp_path / "workspace" / "project-a"
    _init_real_git_repo(repo_path)

    from brain.models import Project

    project = Project(id=str(repo_path), name="project-a", path=str(repo_path), repository="", workspace_id="ws-test")
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)
    client = TestClient(create_app())

    response = client.post("/scripts/commit/run", json={"message": "   "})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert "message" in body["error_message"]


# ---------------------------------------------------------------------------
# T-FB018-US02-04: backlog_status expuesto en la API (datos estructurados +
# síntesis opcional en prosa). Ningún fichero del `02-backlog/` real se toca:
# se escribe un mini-backlog sintético aislado en `tmp_path`.
# ---------------------------------------------------------------------------


def _write_backlog_file(path: Path, item_id: str, *, state: str, priority: str) -> None:
    path.write_text(
        f"# {item_id}\n"
        f"**Epic:** FB-999 · Epic de prueba\n"
        f"## Estado\n\n{state}\n\n"
        f"## Dependencias\n\nNinguna.\n\n"
        f"## Prioridad\n\n{priority}\n",
        encoding="utf-8",
    )


def _active_project_with_backlog(tmp_path: Path, monkeypatch) -> Path:
    """Proyecto activo aislado con un mini-backlog sintético real (2 US +
    1 Task TODO sin dependencias -> 3 LISTA, sin BLOQUEADAS, sin cadena)."""
    repo_path = _active_project(tmp_path, monkeypatch)
    backlog = repo_path / "02-backlog"
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)
    _write_backlog_file(backlog / "user-stories" / "US-FB999-01.md", "US-FB999-01", state="DONE", priority="Alta.")
    _write_backlog_file(backlog / "user-stories" / "US-FB999-02.md", "US-FB999-02", state="TO_DO", priority="Alta.")
    _write_backlog_file(backlog / "tasks" / "T-FB999-01.md", "T-FB999-01", state="TO_DO", priority="Crítica.")
    return repo_path


def test_post_script_run_backlog_status_returns_the_structured_report(
    tmp_path: Path, monkeypatch,
) -> None:
    """Criterio 1 y 2 de T-FB018-US02-04: `POST /scripts/backlog_status/run`
    devuelve el informe estructurado (campo `data`, no solo texto plano)
    para que el cliente lo presente con formato."""
    _active_project_with_backlog(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post("/scripts/backlog_status/run")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    # `data` trae el informe parseado (conteo por Epic, Tasks listas, cadena).
    assert body["data"]["total"]["items"] == 3
    assert body["data"]["total"]["errors"] == 0
    assert [entry["id"] for entry in body["data"]["items_lista"]] == [
        "T-FB999-01",
        "US-FB999-02",
    ]
    assert body["data"]["max_leverage_chain"] == []
    assert len(body["data"]["by_epic"]) == 1
    # Sin Scribe disponible (Ollama no corre en este entorno) -> prose null,
    # y la respuesta no pierde nada (la síntesis es opcional).
    assert body["prose"] is None


def test_post_script_run_backlog_status_includes_prose_when_scribe_is_available(
    tmp_path: Path, monkeypatch,
) -> None:
    """Criterio 4 de T-FB018-US02-04: la capa opcional de síntesis en prosa
    (T-FB018-US02-03) se incluye en la misma respuesta cuando Scribe está
    disponible; si no, `prose` es `null` sin romper nada."""
    _active_project_with_backlog(tmp_path, monkeypatch)

    from unittest.mock import patch

    with patch.object(
        routes_module,
        "resumir_estado_backlog",
        return_value="Hay 3 items en el backlog.",
    ):
        client = TestClient(create_app())
        response = client.post("/scripts/backlog_status/run")

    assert response.status_code == 200
    body = response.json()
    assert body["prose"] == "Hay 3 items en el backlog."


def test_post_script_run_backlog_status_with_an_empty_backlog_returns_empty_data_and_no_prose(
    tmp_path: Path, monkeypatch,
) -> None:
    """Criterio 3: un backlog vacío/recién creado no es una excepción — el
    informe estructurado llega con `empty=True` y no se intenta la síntesis
    en prosa."""
    _active_project(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post("/scripts/backlog_status/run")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["empty"] is True
    assert body["prose"] is None

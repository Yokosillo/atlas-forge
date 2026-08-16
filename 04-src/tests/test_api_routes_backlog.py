"""Tests de `GET /backlog`/`GET /backlog/{item_id}` (T-FB020-US01-01):
envoltura fina de `build_backlog_report`/`load_backlog` (T-FB018-US02-01/02)
sobre el proyecto activo — nunca contra un backlog mockeado, se escriben
ficheros `.md` reales a un `tmp_path` aislado (mismo patrón que
`test_api_routes_scripts.py`)."""

from pathlib import Path

from fastapi.testclient import TestClient

import brain.api.routes as routes_module
from brain.api import create_app
from brain.backlog.report import build_backlog_report

# Ruta del proyecto real (padre de `02-backlog/`) — mismo cálculo que
# `REAL_BACKLOG_PATH` de `test_backlog.py`, aquí como raíz de proyecto
# (no de `02-backlog/` directamente) porque `GET /backlog/{item_id}`
# recibe `project.path` y añade `02-backlog` internamente.
REAL_PROJECT_PATH = Path(__file__).resolve().parents[2]


def _active_project(tmp_path: Path, monkeypatch) -> Path:
    project_path = tmp_path / "workspace" / "project-a"
    project_path.mkdir(parents=True, exist_ok=True)

    from brain.models import Project

    project = Project(id=str(project_path), name="project-a", path=str(project_path), repository="", workspace_id="ws-test")
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)
    return project_path


def _write_task(
    path: Path,
    item_id: str,
    *,
    epic: str,
    state: str,
    dependencies: str = "Ninguna.",
    priority: str = "Alta.",
    objetivo: str = "Objetivo de prueba.",
    criterios: str = "- Criterio uno.\n- Criterio dos.",
) -> None:
    path.write_text(
        f"# {item_id}\n"
        f"**Epic:** {epic}\n\n"
        f"## Objetivo\n\n{objetivo}\n\n"
        f"## Criterios de aceptación\n\n{criterios}\n\n"
        f"## Estado\n\n{state}\n\n"
        f"## Dependencias\n\n{dependencies}\n\n"
        f"## Prioridad\n\n{priority}\n",
        encoding="utf-8",
    )


def _write_user_story(
    path: Path,
    item_id: str,
    *,
    epic: str,
    state: str,
    dependencies: str = "Ninguna.",
    priority: str = "Alta.",
    historia: str = "Como usuario quiero X para lograr Y.",
    criterios: str = "- Criterio uno.\n- Criterio dos.",
) -> None:
    path.write_text(
        f"# {item_id}\n"
        f"**Epic:** {epic}\n\n"
        f"## Historia\n\n{historia}\n\n"
        f"## Criterios de aceptación\n\n{criterios}\n\n"
        f"## Estado\n\n{state}\n\n"
        f"## Dependencias\n\n{dependencies}\n\n"
        f"## Prioridad\n\n{priority}\n",
        encoding="utf-8",
    )


def _write_epic_file(path: Path, epic_id: str, *, objetivo: str = "Objetivo de la Epic.") -> None:
    """Fixture de Epic fiel al formato REAL de `02-backlog/epics/*.md`:
    título en `#`, `## Objetivo` (único H2 del fichero), y el resto del
    contenido (Contexto, Alcance, Diferido a v2, ...) en secciones `#`
    (H1), no `##` — verificado sobre `FB-020-gestion-de-backlog.md` real
    (`# FB-020 ...` / `## Objetivo` / `# Contexto` / `# Alcance` / ...).
    Antes de la corrección del Crítico esta fixture solo tenía `##
    Objetivo` + un párrafo sin nada detrás — nunca ejercitó el caso real
    de secciones en `#` tras el Objetivo, por eso el bug pasó los 11 tests
    originales sin ser detectado."""
    path.write_text(
        f"# {epic_id} Epic de prueba\n\n"
        f"## Objetivo\n\n{objetivo}\n\n"
        "---\n\n"
        "# Contexto\n\n"
        "Investigación previa que NO debe colarse en `objetivo` — si "
        "`_read_section` no corta en `#`, este párrafo aparecería\n"
        "arrastrado dentro del objetivo devuelto por la API.\n\n"
        "# Alcance\n\n"
        "Más contenido de otra sección en H1, mismo caso.\n\n"
        "## Un subtítulo dentro de Alcance\n\n"
        "Subsección real en H2 dentro de una sección en H1 (mismo patrón "
        "que `## Listado y detalle de backlog` dentro de `# "
        "Responsabilidades` en `FB-020` real) — tampoco debe colarse.\n",
        encoding="utf-8",
    )


def _seed_backlog(repo_path: Path) -> Path:
    """Backlog sintético: 1 Epic (FB-999) con 1 US (2 variantes de label de
    Epic, como pasa en el backlog real) y 2 Tasks, una de ellas dependiente
    de la US."""
    backlog = repo_path / "02-backlog"
    (backlog / "epics").mkdir(parents=True)
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)

    _write_epic_file(backlog / "epics" / "FB-999-epic-de-prueba.md", "FB-999")

    _write_user_story(
        backlog / "user-stories" / "US-FB999-01.md",
        "US-FB999-01",
        epic="FB-999 · Epic de prueba",
        state="TODO",
        historia="Como desarrollador quiero ver el backlog para saber su estado.",
        criterios="- El listado muestra el conteo.\n- El detalle muestra la historia.",
    )
    _write_task(
        backlog / "tasks" / "T-FB999-US01-01.md",
        "T-FB999-US01-01",
        epic="FB-999 · Epic de prueba (alcance v1)",
        state="TODO",
        dependencies="**US-FB999-01**",
    )
    _write_task(
        backlog / "tasks" / "T-FB999-US01-02.md",
        "T-FB999-US01-02",
        epic="FB-999 · Epic de prueba",
        state="DONE",
        dependencies="Ninguna.",
    )
    return backlog


def test_get_backlog_returns_404_when_no_project_is_active(monkeypatch) -> None:
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: None)
    client = TestClient(create_app())

    response = client.get("/backlog")

    assert response.status_code == 404


def test_get_backlog_matches_build_backlog_report_on_the_same_backlog(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación explícito: `GET /backlog` produce los mismos
    números que `build_backlog_report()` invocado directamente sobre el
    mismo `02-backlog/` — comparación real, no solo 'parece razonable'."""
    repo_path = _active_project(tmp_path, monkeypatch)
    backlog_path = _seed_backlog(repo_path)
    client = TestClient(create_app())

    response = client.get("/backlog")

    assert response.status_code == 200
    expected = build_backlog_report(backlog_path)
    assert response.json() == expected
    assert response.json()["total"]["items"] == 3


def test_get_backlog_item_returns_404_when_no_project_is_active(monkeypatch) -> None:
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: None)
    client = TestClient(create_app())

    response = client.get("/backlog/US-FB999-01")

    assert response.status_code == 404


def test_get_backlog_item_for_unknown_id_returns_404_with_explicit_detail(
    tmp_path: Path, monkeypatch
) -> None:
    repo_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(repo_path)
    client = TestClient(create_app())

    response = client.get("/backlog/US-FB999-99")

    assert response.status_code == 404
    assert "US-FB999-99" in response.json()["detail"]


def test_get_backlog_item_with_a_malformed_estado_returns_404_with_the_parse_reason(
    tmp_path: Path, monkeypatch
) -> None:
    """Un item cuyo `## Estado` está mal formado no llega a `graph.items`
    (se reporta en `graph.errors`, `BacklogParseError` — criterio 6 de
    US-FB018-02) — el detalle sigue siendo 404 (no es consultable), pero
    con el motivo real del fallo de parseo en vez de 'no existe', para no
    confundir 'fichero roto' con 'nunca existió'."""
    repo_path = _active_project(tmp_path, monkeypatch)
    backlog = _seed_backlog(repo_path)
    (backlog / "tasks" / "T-FB999-US01-04.md").write_text(
        "# T-FB999-US01-04\n"
        "**Epic:** FB-999 · Epic de prueba\n\n"
        "## Dependencias\n\nNinguna.\n",
        encoding="utf-8",
    )
    client = TestClient(create_app())

    response = client.get("/backlog/T-FB999-US01-04")

    assert response.status_code == 404
    assert "T-FB999-US01-04" in response.json()["detail"]
    assert "Estado" in response.json()["detail"]


def test_get_backlog_item_for_epic_task_count_reflects_real_tasks_in_yaml_format(
    tmp_path: Path, monkeypatch
) -> None:
    # T-FB036-US01-09, vía HTTP end-to-end (no solo build_epic_detail en
    # aislamiento, ya cubierto en test_backlog_detail.py): dos User
    # Stories reales de la misma Epic, una con 2 Tasks (una TODO, una
    # DONE — ambas cuentan) y otra sin ninguna — usa formato frontmatter
    # YAML vigente (con user_story: real), a diferencia de _seed_backlog
    # (formato antiguo, sin ese campo).
    repo_path = _active_project(tmp_path, monkeypatch)
    backlog = repo_path / "02-backlog"
    (backlog / "epics").mkdir(parents=True)
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)

    (backlog / "epics" / "FB-999-epic.md").write_text(
        "---\nid: FB-999\ntype: epic\ntitle: Epic\nstate: TODO\n"
        "dependencies: []\n---\n\n## Objetivo\n\nObjetivo.\n",
        encoding="utf-8",
    )

    def _us_yaml(us_id: str) -> str:
        return (
            "---\n"
            f"id: {us_id}\ntype: user_story\ntitle: Historia\nstate: TODO\n"
            "dependencies: []\nepic: FB-999\npriority: Alta\n---\n\n"
            "## Historia\n\nHistoria.\n\n## Criterios de aceptación\n\n1. Y.\n"
        )

    def _task_yaml(task_id: str, us_id: str, state: str) -> str:
        return (
            "---\n"
            f"id: {task_id}\ntype: task\ntitle: Task\nstate: {state}\n"
            f"dependencies: []\nepic: FB-999\nuser_story: {us_id}\n"
            "priority: Alta\n---\n\n"
            "## Objetivo\n\nObjetivo.\n\n## Criterios de aceptación\n\n1. Y.\n"
        )

    (backlog / "user-stories" / "US-FB999-01.md").write_text(_us_yaml("US-FB999-01"), encoding="utf-8")
    (backlog / "user-stories" / "US-FB999-02.md").write_text(_us_yaml("US-FB999-02"), encoding="utf-8")
    (backlog / "tasks" / "T-FB999-US01-01.md").write_text(
        _task_yaml("T-FB999-US01-01", "US-FB999-01", "TODO"), encoding="utf-8"
    )
    (backlog / "tasks" / "T-FB999-US01-02.md").write_text(
        _task_yaml("T-FB999-US01-02", "US-FB999-01", "DONE"), encoding="utf-8"
    )

    client = TestClient(create_app())
    response = client.get("/backlog/FB-999")

    assert response.status_code == 200
    body = response.json()
    counts = {us["id"]: us["task_count"] for us in body["user_stories"]}
    assert counts == {"US-FB999-01": 2, "US-FB999-02": 0}


def test_get_backlog_item_for_epic_returns_objective_and_user_stories_breakdown(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación: detalle de una Epic devuelve su objetivo y
    el desglose de sus User Stories — agrupa por el prefijo `FB-xxx` del
    label libre de `## Epic`, no por el string completo (distintas
    Tasks/US de la misma Epic real pueden traer sufijos distintos, como
    en el backlog real de este proyecto)."""
    repo_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(repo_path)
    client = TestClient(create_app())

    response = client.get("/backlog/FB-999")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "FB-999"
    assert body["kind"] == "epic"
    # Regresión del hallazgo del Crítico: `_write_epic_file` escribe varias
    # secciones en `#` (Contexto, Alcance, subtítulo en `##` dentro de
    # Alcance) DESPUÉS de `## Objetivo`, fiel al formato real de
    # `02-backlog/epics/*.md`. Antes del fix, `_read_section` solo cortaba
    # en `##` — el `#` de "Contexto"/"Alcance" no lo detenía, así que todo
    # ese texto quedaba arrastrado dentro de `objetivo`. La igualdad exacta
    # (no un `in`) es la prueba de que nada se coló.
    assert body["objetivo"] == "Objetivo de la Epic."
    assert "Contexto" not in body["objetivo"]
    assert "Alcance" not in body["objetivo"]
    # T-FB036-US01-09: task_count nuevo — 0 aquí pese a que `_seed_backlog`
    # sí crea 2 Tasks reales, porque usa el formato Markdown ANTIGUO
    # (`_write_task`, sin frontmatter YAML) — ninguna de esas Tasks
    # declara `user_story:` (campo del que depende `task_count`, solo
    # existe en el frontmatter vigente), así que no cuentan aquí. Ver
    # `test_backlog_detail.py` para el caso con Tasks en formato YAML
    # vigente sí contadas.
    assert body["user_stories"] == [
        {"id": "US-FB999-01", "state": "TODO", "priority": "Alta.", "task_count": 0}
    ]


def test_get_backlog_item_for_unknown_epic_returns_404(tmp_path: Path, monkeypatch) -> None:
    repo_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(repo_path)
    client = TestClient(create_app())

    response = client.get("/backlog/FB-001")

    assert response.status_code == 404
    assert "FB-001" in response.json()["detail"]


def test_get_backlog_item_for_user_story_returns_objective_and_criteria(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación: detalle de una US devuelve objetivo y
    criterios de aceptación.

    T-FB008-US04-05 (corrección, 2026-08-16): este test antes afirmaba
    que `tasks` se derivaba de qué Tasks declaran la US en su
    `## Dependencias` — ese era exactamente el bug real reportado por el
    usuario (`GET /backlog/{us_id}` devolvía `tasks: []` para CUALQUIER
    User Story real del proyecto, verificado sobre el backlog real:
    ninguna Task ha usado jamás `dependencies` para esto). La relación
    real vive en el campo `user_story:` del frontmatter YAML — ausente
    por completo en el formato Markdown legacy que usa `_seed_backlog`
    de este fichero (sin frontmatter), así que con el fix correcto
    `tasks` sale vacío aquí: es la consecuencia correcta de un fixture en
    formato legacy sin ese campo, no un bug. La cobertura del camino
    correcto (Task en formato YAML vigente con `user_story:` poblado)
    vive en `test_backlog_detail.py`, con fixtures que sí representan el
    formato real de `02-backlog/`."""
    repo_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(repo_path)
    client = TestClient(create_app())

    response = client.get("/backlog/US-FB999-01")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "US-FB999-01"
    assert body["kind"] == "US"
    assert body["state"] == "TODO"
    assert body["objetivo"] == "Como desarrollador quiero ver el backlog para saber su estado."
    assert body["criterios_aceptacion"] == (
        "- El listado muestra el conteo.\n- El detalle muestra la historia."
    )
    assert body["tasks"] == []
    assert "parse_warning" not in body


def test_get_backlog_item_for_task_returns_objective_and_criteria_without_tasks_field(
    tmp_path: Path, monkeypatch
) -> None:
    repo_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(repo_path)
    client = TestClient(create_app())

    response = client.get("/backlog/T-FB999-US01-02")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "T-FB999-US01-02"
    assert body["kind"] == "T"
    assert body["objetivo"] == "Objetivo de prueba."
    assert "tasks" not in body


def test_get_backlog_item_with_malformed_optional_section_returns_content_with_warning(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación: un fichero con sección mal formada (aquí,
    sin `## Objetivo` ni `## Criterios de aceptación`) no rompe el
    endpoint — el resto del contenido sigue siendo consultable, con
    `parse_warning` explícito."""
    repo_path = _active_project(tmp_path, monkeypatch)
    backlog = _seed_backlog(repo_path)
    (backlog / "tasks" / "T-FB999-US01-03.md").write_text(
        "# T-FB999-US01-03\n"
        "**Epic:** FB-999 · Epic de prueba\n\n"
        "## Estado\n\nTODO\n\n"
        "## Dependencias\n\nNinguna.\n\n"
        "## Prioridad\n\nMedia.\n",
        encoding="utf-8",
    )
    client = TestClient(create_app())

    response = client.get("/backlog/T-FB999-US01-03")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "T-FB999-US01-03"
    assert body["state"] == "TODO"
    assert body["objetivo"] is None
    assert body["criterios_aceptacion"] is None
    assert "parse_warning" in body
    assert "Objetivo" in body["parse_warning"]
    assert "Criterios de aceptación" in body["parse_warning"]


def test_get_backlog_item_for_epic_without_epic_file_but_with_referencing_user_stories(
    tmp_path: Path, monkeypatch
) -> None:
    """Una Epic sin fichero propio en `02-backlog/epics/` pero referenciada
    por alguna US igualmente se resuelve (objetivo `None` +
    `parse_warning`), en vez de un 404 — hay evidencia real de que la
    Epic existe en el backlog (US que la declaran)."""
    repo_path = _active_project(tmp_path, monkeypatch)
    backlog = _seed_backlog(repo_path)
    (backlog / "epics" / "FB-999-epic-de-prueba.md").unlink()
    client = TestClient(create_app())

    response = client.get("/backlog/FB-999")

    assert response.status_code == 200
    body = response.json()
    assert body["objetivo"] is None
    assert "parse_warning" in body
    # T-FB036-US01-09: task_count nuevo — 0 aquí pese a que `_seed_backlog`
    # sí crea 2 Tasks reales, porque usa el formato Markdown ANTIGUO
    # (`_write_task`, sin frontmatter YAML) — ninguna de esas Tasks
    # declara `user_story:` (campo del que depende `task_count`, solo
    # existe en el frontmatter vigente), así que no cuentan aquí. Ver
    # `test_backlog_detail.py` para el caso con Tasks en formato YAML
    # vigente sí contadas.
    assert body["user_stories"] == [
        {"id": "US-FB999-01", "state": "TODO", "priority": "Alta.", "task_count": 0}
    ]


# ---------------------------------------------------------------------------
# Reverificación del hallazgo del Crítico contra el `02-backlog/` REAL de
# este proyecto (no solo el sintético): antes del fix, `GET /backlog/FB-020`
# devolvía 7218 caracteres de `objetivo` (Contexto/Alcance/Alcance v1/
# Diferido a v2 arrastrados enteros). Estos tests activan el proyecto REAL
# (`REAL_PROJECT_PATH`, solo lectura — ningún fichero de `02-backlog/` se
# escribe ni se modifica) para confirmar el fix sobre el caso exacto que
# lo detectó, no solo sobre una fixture sintética.
# ---------------------------------------------------------------------------


def _active_real_project(monkeypatch) -> None:
    from brain.models import Project

    project = Project(
        id=str(REAL_PROJECT_PATH),
        name=REAL_PROJECT_PATH.name,
        path=str(REAL_PROJECT_PATH),
        repository="",
        workspace_id="ws-real",
    )
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)


def test_get_backlog_item_fb020_on_the_real_backlog_returns_only_the_objetivo_section(
    monkeypatch,
) -> None:
    """Reverificación directa del hallazgo del Crítico: `GET /backlog/FB-020`
    contra el `02-backlog/epics/FB-020-gestion-de-backlog.md` real ya NO
    arrastra `# Contexto`/`# Alcance`/`# Alcance v1`/`# Diferido a v2` —
    ninguno de esos títulos aparece dentro de `objetivo`, y su longitud es
    la del párrafo real (unos pocos cientos de caracteres), no miles."""
    _active_real_project(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/backlog/FB-020")

    assert response.status_code == 200
    body = response.json()
    objetivo = body["objetivo"]
    assert objetivo is not None
    # El objetivo real de FB-020 (verificado leyendo el fichero) empieza
    # así — si esto cambia junto con el fichero real, el test debe
    # actualizarse, no relajarse a un `startswith` más laxo.
    assert objetivo.startswith('Convertir la pantalla "Plan del Critic"')
    for leaked_heading in ("# Contexto", "# Alcance", "# Diferido a v2", "# Responsabilidades"):
        assert leaked_heading not in objetivo
    # Antes del fix eran 7218 caracteres; el párrafo real cabe holgado
    # bajo 1000 sin arrastrar el resto del fichero.
    assert len(objetivo) < 1000


def test_get_backlog_real_matches_build_backlog_report_on_the_real_backlog(
    monkeypatch,
) -> None:
    """`GET /backlog` también se reverifica contra el `02-backlog/` real
    completo (no solo el sintético) — mismos números que
    `build_backlog_report()` invocado directamente."""
    _active_real_project(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/backlog")

    assert response.status_code == 200
    expected = build_backlog_report(REAL_PROJECT_PATH / "02-backlog")
    assert response.json() == expected


def test_get_backlog_item_reconciles_user_story_done_with_reopened_task(
    tmp_path: Path, monkeypatch
) -> None:
    """T-FB022-US13-05, criterio 1: reproduce el caso real de hoy (US con
    `state: DONE` en disco y una Task hija con `state: TODO`, sin pasar
    por ningún commit) contra `GET /backlog/{us_id}` real — no la
    presenta como completada sin matiz."""
    repo_path = _active_project(tmp_path, monkeypatch)
    backlog = repo_path / "02-backlog"
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)
    (backlog / "user-stories" / "US-FB997-01.md").write_text(
        "---\nid: US-FB997-01\ntype: user_story\ntitle: Historia\nstate: DONE\n"
        "dependencies: []\nepic: FB-997\npriority: Alta\n---\n\n"
        "## Historia\n\nHistoria.\n\n## Criterios de aceptación\n\n1. Y.\n",
        encoding="utf-8",
    )
    (backlog / "tasks" / "T-FB997-US01-01.md").write_text(
        "---\nid: T-FB997-US01-01\ntype: task\ntitle: Task\nstate: TODO\n"
        "dependencies: []\nepic: FB-997\nuser_story: US-FB997-01\npriority: Alta\n---\n\n"
        "## Objetivo\n\nObjetivo.\n\n## Criterios de aceptación\n\n1. Y.\n",
        encoding="utf-8",
    )
    client = TestClient(create_app())

    response = client.get("/backlog/US-FB997-01")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "IN_PROGRESS"
    assert body["drift"] is True
    assert body["tasks"] == [{"id": "T-FB997-US01-01", "state": "TODO", "priority": "Alta"}]

    # No se escribió nada en disco (solo lectura).
    on_disk = (backlog / "user-stories" / "US-FB997-01.md").read_text(encoding="utf-8")
    assert "state: DONE" in on_disk

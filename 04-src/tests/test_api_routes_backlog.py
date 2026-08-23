"""Tests de `GET /backlog`/`GET /backlog/{item_id}` (T-AF020-US01-01):
envoltura fina de `build_backlog_report`/`load_backlog` (T-AF018-US02-01/02)
sobre el proyecto activo — nunca contra un backlog mockeado, se escriben
ficheros `.md` reales a un `tmp_path` aislado (mismo patrón que
`test_api_routes_scripts.py`)."""

from pathlib import Path

from fastapi.testclient import TestClient

import atlas_forge.api.routes as routes_module
from atlas_forge.api import create_app
from atlas_forge.backlog.report import build_backlog_report

# Ruta del proyecto real (padre de `02-backlog/`) — mismo cálculo que
# `REAL_BACKLOG_PATH` de `test_backlog.py`, aquí como raíz de proyecto
# (no de `02-backlog/` directamente) porque `GET /backlog/{item_id}`
# recibe `project.path` y añade `02-backlog` internamente.
REAL_PROJECT_PATH = Path(__file__).resolve().parents[2]


def _active_project(tmp_path: Path, monkeypatch) -> Path:
    project_path = tmp_path / "workspace" / "project-a"
    project_path.mkdir(parents=True, exist_ok=True)

    from atlas_forge.models import Project

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
    (H1), no `##` — verificado sobre `AF-020-gestion-de-backlog.md` real
    (`# AF-020 ...` / `## Objetivo` / `# Contexto` / `# Alcance` / ...).
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
        "Responsabilidades` en `AF-020` real) — tampoco debe colarse.\n",
        encoding="utf-8",
    )


def _seed_backlog(repo_path: Path) -> Path:
    """Backlog sintético: 1 Epic (AF-999) con 1 US (2 variantes de label de
    Epic, como pasa en el backlog real) y 2 Tasks, una de ellas dependiente
    de la US."""
    backlog = repo_path / "02-backlog"
    (backlog / "epics").mkdir(parents=True)
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)

    _write_epic_file(backlog / "epics" / "AF-999-epic-de-prueba.md", "AF-999")

    _write_user_story(
        backlog / "user-stories" / "US-AF999-01.md",
        "US-AF999-01",
        epic="AF-999 · Epic de prueba",
        state="READY",
        historia="Como desarrollador quiero ver el backlog para saber su estado.",
        criterios="- El listado muestra el conteo.\n- El detalle muestra la historia.",
    )
    _write_task(
        backlog / "tasks" / "T-AF999-US01-01.md",
        "T-AF999-US01-01",
        epic="AF-999 · Epic de prueba (alcance v1)",
        state="READY",
        dependencies="**US-AF999-01**",
    )
    _write_task(
        backlog / "tasks" / "T-AF999-US01-02.md",
        "T-AF999-US01-02",
        epic="AF-999 · Epic de prueba",
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

    response = client.get("/backlog/US-AF999-01")

    assert response.status_code == 404


def test_get_backlog_item_for_unknown_id_returns_404_with_explicit_detail(
    tmp_path: Path, monkeypatch
) -> None:
    repo_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(repo_path)
    client = TestClient(create_app())

    response = client.get("/backlog/US-AF999-99")

    assert response.status_code == 404
    assert "US-AF999-99" in response.json()["detail"]


def test_get_backlog_item_with_a_malformed_estado_returns_404_with_the_parse_reason(
    tmp_path: Path, monkeypatch
) -> None:
    """Un item cuyo `## Estado` está mal formado no llega a `graph.items`
    (se reporta en `graph.errors`, `BacklogParseError` — criterio 6 de
    US-AF018-02) — el detalle sigue siendo 404 (no es consultable), pero
    con el motivo real del fallo de parseo en vez de 'no existe', para no
    confundir 'fichero roto' con 'nunca existió'."""
    repo_path = _active_project(tmp_path, monkeypatch)
    backlog = _seed_backlog(repo_path)
    (backlog / "tasks" / "T-AF999-US01-04.md").write_text(
        "# T-AF999-US01-04\n"
        "**Epic:** AF-999 · Epic de prueba\n\n"
        "## Dependencias\n\nNinguna.\n",
        encoding="utf-8",
    )
    client = TestClient(create_app())

    response = client.get("/backlog/T-AF999-US01-04")

    assert response.status_code == 404
    assert "T-AF999-US01-04" in response.json()["detail"]
    assert "Estado" in response.json()["detail"]


def test_get_backlog_item_for_epic_task_count_reflects_real_tasks_in_yaml_format(
    tmp_path: Path, monkeypatch
) -> None:
    # T-AF036-US01-09, vía HTTP end-to-end (no solo build_epic_detail en
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

    (backlog / "epics" / "AF-999-epic.md").write_text(
        "---\nid: AF-999\ntype: epic\ntitle: Epic\nstate: TODO\n"
        "dependencies: []\n---\n\n## Objetivo\n\nObjetivo.\n",
        encoding="utf-8",
    )

    def _us_yaml(us_id: str) -> str:
        return (
            "---\n"
            f"id: {us_id}\ntype: user_story\ntitle: Historia\nstate: READY\n"
            "dependencies: []\nepic: AF-999\npriority: Alta\n---\n\n"
            "## Historia\n\nHistoria.\n\n## Criterios de aceptación\n\n1. Y.\n"
        )

    def _task_yaml(task_id: str, us_id: str, state: str) -> str:
        return (
            "---\n"
            f"id: {task_id}\ntype: task\ntitle: Task\nstate: {state}\n"
            f"dependencies: []\nepic: AF-999\nuser_story: {us_id}\n"
            "priority: Alta\n---\n\n"
            "## Objetivo\n\nObjetivo.\n\n## Criterios de aceptación\n\n1. Y.\n"
        )

    (backlog / "user-stories" / "US-AF999-01.md").write_text(_us_yaml("US-AF999-01"), encoding="utf-8")
    (backlog / "user-stories" / "US-AF999-02.md").write_text(_us_yaml("US-AF999-02"), encoding="utf-8")
    (backlog / "tasks" / "T-AF999-US01-01.md").write_text(
        _task_yaml("T-AF999-US01-01", "US-AF999-01", "READY"), encoding="utf-8"
    )
    (backlog / "tasks" / "T-AF999-US01-02.md").write_text(
        _task_yaml("T-AF999-US01-02", "US-AF999-01", "DONE"), encoding="utf-8"
    )

    client = TestClient(create_app())
    response = client.get("/backlog/AF-999")

    assert response.status_code == 200
    body = response.json()
    counts = {us["id"]: us["task_count"] for us in body["user_stories"]}
    assert counts == {"US-AF999-01": 2, "US-AF999-02": 0}


def test_get_backlog_item_for_epic_returns_objective_and_user_stories_breakdown(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación: detalle de una Epic devuelve su objetivo y
    el desglose de sus User Stories — agrupa por el prefijo `AF-xxx` del
    label libre de `## Epic`, no por el string completo (distintas
    Tasks/US de la misma Epic real pueden traer sufijos distintos, como
    en el backlog real de este proyecto)."""
    repo_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(repo_path)
    client = TestClient(create_app())

    response = client.get("/backlog/AF-999")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "AF-999"
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
    # T-AF036-US01-09: task_count nuevo — 0 aquí pese a que `_seed_backlog`
    # sí crea 2 Tasks reales, porque usa el formato Markdown ANTIGUO
    # (`_write_task`, sin frontmatter YAML) — ninguna de esas Tasks
    # declara `user_story:` (campo del que depende `task_count`, solo
    # existe en el frontmatter vigente), así que no cuentan aquí. Ver
    # `test_backlog_detail.py` para el caso con Tasks en formato YAML
    # vigente sí contadas.
    assert body["user_stories"] == [
        {
            "id": "US-AF999-01",
            # T-AF022-US13-09: US sin Tasks vinculadas (formato legacy) -> NO_TASKS.
            "state": "NO_TASKS",
            "priority": "Alta.",
            # T-AF036-US19-01: title (formato legacy sin `title:` -> fallback al id).
            "title": "US-AF999-01",
            "fase": None,
            "updated_at": None,
            "task_count": 0,
            "drift": True,
        }
    ]


def test_get_backlog_item_for_epic_exposes_version_and_not_fase(
    tmp_path: Path, monkeypatch
) -> None:
    """T-AF036-US18-01, criterio 2: `GET /backlog/{epic_id}` de una Epic
    versionada (creada con `create_epic`, que escribe `version: 0.9` y no
    `fase`) devuelve `version` y NO `fase` a nivel de Epic."""
    project_path = _active_project(tmp_path, monkeypatch)
    backlog = project_path / "02-backlog"

    from atlas_forge.backlog.create import create_epic

    create_epic(backlog, "AF-900", "Epic versionada", "Objetivo real.")

    client = TestClient(create_app())
    response = client.get("/backlog/AF-900")

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "epic"
    assert body.get("version") == "0.9"
    assert "fase" not in body


def test_get_backlog_item_for_unknown_epic_returns_404(tmp_path: Path, monkeypatch) -> None:
    repo_path = _active_project(tmp_path, monkeypatch)
    _seed_backlog(repo_path)
    client = TestClient(create_app())

    response = client.get("/backlog/AF-001")

    assert response.status_code == 404
    assert "AF-001" in response.json()["detail"]


def test_get_backlog_item_for_user_story_returns_objective_and_criteria(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación: detalle de una US devuelve objetivo y
    criterios de aceptación.

    T-AF008-US04-05 (corrección, 2026-08-16): este test antes afirmaba
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

    response = client.get("/backlog/US-AF999-01")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "US-AF999-01"
    assert body["kind"] == "US"
    # T-AF022-US13-09: US sin Tasks (formato legacy) deriva a NO_TASKS.
    assert body["state"] == "NO_TASKS"
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

    response = client.get("/backlog/T-AF999-US01-02")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "T-AF999-US01-02"
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
    (backlog / "tasks" / "T-AF999-US01-03.md").write_text(
        "# T-AF999-US01-03\n"
        "**Epic:** AF-999 · Epic de prueba\n\n"
        "## Estado\n\nREADY\n\n"
        "## Dependencias\n\nNinguna.\n\n"
        "## Prioridad\n\nMedia.\n",
        encoding="utf-8",
    )
    client = TestClient(create_app())

    response = client.get("/backlog/T-AF999-US01-03")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "T-AF999-US01-03"
    assert body["state"] == "READY"
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
    (backlog / "epics" / "AF-999-epic-de-prueba.md").unlink()
    client = TestClient(create_app())

    response = client.get("/backlog/AF-999")

    assert response.status_code == 200
    body = response.json()
    assert body["objetivo"] is None
    assert "parse_warning" in body
    # T-AF036-US01-09: task_count nuevo — 0 aquí pese a que `_seed_backlog`
    # sí crea 2 Tasks reales, porque usa el formato Markdown ANTIGUO
    # (`_write_task`, sin frontmatter YAML) — ninguna de esas Tasks
    # declara `user_story:` (campo del que depende `task_count`, solo
    # existe en el frontmatter vigente), así que no cuentan aquí. Ver
    # `test_backlog_detail.py` para el caso con Tasks en formato YAML
    # vigente sí contadas.
    assert body["user_stories"] == [
        {
            "id": "US-AF999-01",
            # T-AF022-US13-09: US sin Tasks vinculadas (formato legacy) -> NO_TASKS.
            "state": "NO_TASKS",
            "priority": "Alta.",
            # T-AF036-US19-01: title (formato legacy sin `title:` -> fallback al id).
            "title": "US-AF999-01",
            "fase": None,
            "updated_at": None,
            "task_count": 0,
            "drift": True,
        }
    ]


# ---------------------------------------------------------------------------
# Reverificación del hallazgo del Crítico contra el `02-backlog/` REAL de
# este proyecto (no solo el sintético): antes del fix, `GET /backlog/AF-020`
# devolvía 7218 caracteres de `objetivo` (Contexto/Alcance/Alcance v1/
# Diferido a v2 arrastrados enteros). Estos tests activan el proyecto REAL
# (`REAL_PROJECT_PATH`, solo lectura — ningún fichero de `02-backlog/` se
# escribe ni se modifica) para confirmar el fix sobre el caso exacto que
# lo detectó, no solo sobre una fixture sintética.
# ---------------------------------------------------------------------------


def _active_real_project(monkeypatch) -> None:
    from atlas_forge.models import Project

    project = Project(
        id=str(REAL_PROJECT_PATH),
        name=REAL_PROJECT_PATH.name,
        path=str(REAL_PROJECT_PATH),
        repository="",
        workspace_id="ws-real",
    )
    monkeypatch.setattr(routes_module, "get_active_project", lambda **_kwargs: project)


def test_get_backlog_item_af020_on_the_real_backlog_returns_only_the_objetivo_section(
    monkeypatch,
) -> None:
    """Reverificación directa del hallazgo del Crítico: `GET /backlog/AF-020`
    contra el `02-backlog/epics/AF-020-gestion-de-backlog.md` real ya NO
    arrastra `# Contexto`/`# Alcance`/`# Alcance v1`/`# Diferido a v2` —
    ninguno de esos títulos aparece dentro de `objetivo`, y su longitud es
    la del párrafo real (unos pocos cientos de caracteres), no miles."""
    _active_real_project(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/backlog/AF-020")

    assert response.status_code == 200
    body = response.json()
    objetivo = body["objetivo"]
    assert objetivo is not None
    # El objetivo real de AF-020 (verificado leyendo el fichero) empieza
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
    """T-AF022-US13-05, criterio 1: reproduce el caso real de hoy (US con
    `state: DONE` en disco y una Task hija con `state: READY`, sin pasar
    por ningún commit) contra `GET /backlog/{us_id}` real — no la
    presenta como completada sin matiz."""
    repo_path = _active_project(tmp_path, monkeypatch)
    backlog = repo_path / "02-backlog"
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)
    (backlog / "user-stories" / "US-AF997-01.md").write_text(
        "---\nid: US-AF997-01\ntype: user_story\ntitle: Historia\nstate: DONE\n"
        "dependencies: []\nepic: AF-997\npriority: Alta\n---\n\n"
        "## Historia\n\nHistoria.\n\n## Criterios de aceptación\n\n1. Y.\n",
        encoding="utf-8",
    )
    (backlog / "tasks" / "T-AF997-US01-01.md").write_text(
        "---\nid: T-AF997-US01-01\ntype: task\ntitle: Task\nstate: READY\n"
        "dependencies: []\nepic: AF-997\nuser_story: US-AF997-01\npriority: Alta\n---\n\n"
        "## Objetivo\n\nObjetivo.\n\n## Criterios de aceptación\n\n1. Y.\n",
        encoding="utf-8",
    )
    client = TestClient(create_app())

    response = client.get("/backlog/US-AF997-01")

    assert response.status_code == 200
    body = response.json()
    # T-AF022-US13-09: la US DONE con una Task reabierta (READY) deriva a
    # READY, no al grueso IN_PROGRESS.
    assert body["state"] == "READY"
    assert body["drift"] is True
    assert body["tasks"] == [
        {
            "id": "T-AF997-US01-01",
            "state": "READY",
            "priority": "Alta",
            # T-AF036-US19-01: title de la Task.
            "title": "Task",
            "fase": None,
            "updated_at": None,
        }
    ]

    # No se escribió nada en disco (solo lectura).
    on_disk = (backlog / "user-stories" / "US-AF997-01.md").read_text(encoding="utf-8")
    assert "state: DONE" in on_disk


# ---------------------------------------------------------------------------
# T-AF036-US06-01: GET /backlog/us/{us_id}/report — informe de cierre real.
# ---------------------------------------------------------------------------


def _write_us_for_report(tmp_path: Path, monkeypatch, us_id: str = "US-AF996-01") -> Path:
    repo_path = _active_project(tmp_path, monkeypatch)
    backlog = repo_path / "02-backlog"
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "user-stories" / f"{us_id}.md").write_text(
        "---\n"
        f"id: {us_id}\n"
        "type: user_story\n"
        "title: Historia\n"
        "state: DONE\n"
        "dependencies: []\n"
        "epic: AF-996\n"
        "priority: Alta\n"
        "---\n\n"
        "## Historia\n\nHistoria.\n\n"
        "## Criterios de aceptación\n\n1. Y.\n",
        encoding="utf-8",
    )
    return repo_path


def test_get_us_closing_report_resolves_real_file_without_assuming_filename(
    tmp_path: Path, monkeypatch,
) -> None:
    """T-AF036-US06-01: el endpoint resuelve el fichero REAL dentro de
    `07-informes/<us_id>/` por GLOB del directorio, NO por construcción de
    nombre — el nombre real no coincide con `<story_id>.md` (caso real
    confirmado, p. ej. `US-AF002-04/T-AF002-US04-01.md`)."""
    repo_path = _write_us_for_report(tmp_path, monkeypatch)
    reports_dir = repo_path / "07-informes" / "US-AF996-01"
    reports_dir.mkdir(parents=True)
    # Nombre de fichero deliberadamente DISTINTO de `US-AF996-01.md`.
    report_path = reports_dir / "informe-final-2026.md"
    report_path.write_text(
        "# Informe de cierre\n\n## T-AF996-US01-01 · Implementar cola\n\nCerrada.\n",
        encoding="utf-8",
    )
    client = TestClient(create_app())

    response = client.get("/backlog/us/US-AF996-01/report")

    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["us_id"] == "US-AF996-01"
    assert body["path"].endswith("informe-final-2026.md")
    assert "Cerrada." in body["content"]


def test_get_us_closing_report_returns_exists_false_when_no_report_dir(
    tmp_path: Path, monkeypatch,
) -> None:
    """T-AF036-US06-01: sin directorio `07-informes/<us_id>/` (o vacío) el
    endpoint devuelve `{"exists": false}` — distinguible de un error real,
    nunca un 404 por "no hay informe"."""
    repo_path = _write_us_for_report(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.get("/backlog/us/US-AF996-01/report")

    assert response.status_code == 200
    assert response.json() == {"exists": False, "us_id": "US-AF996-01"}


def test_get_us_closing_report_returns_exists_false_for_empty_report_dir(
    tmp_path: Path, monkeypatch,
) -> None:
    repo_path = _write_us_for_report(tmp_path, monkeypatch)
    (repo_path / "07-informes" / "US-AF996-01").mkdir(parents=True)
    client = TestClient(create_app())

    response = client.get("/backlog/us/US-AF996-01/report")

    assert response.status_code == 200
    assert response.json() == {"exists": False, "us_id": "US-AF996-01"}


def test_get_us_closing_report_returns_404_for_unknown_us(tmp_path: Path, monkeypatch) -> None:
    """T-AF036-US06-01: una US inexistente en el backlog es un error real
    (404 verbatim), distinto del caso "informe ausente"."""
    _active_project(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.get("/backlog/us/US-AF996-99/report")

    assert response.status_code == 404
    assert "US-AF996-99" in response.json()["detail"]


# ---------------------------------------------------------------------------
# T-AF036-US19-03: tests de ENDPOINT (pytest) del contrato de cabeceras — el
# `title` que la web usa para pintar `ID + nombre` en las filas de US y Task.
# `GET /backlog/{epic_id}` debe exponer `title` en cada `user_stories[i]`;
# `GET /backlog/{us_id}` en el propio item y en cada `tasks[i]` (T-AF036-US19-01).
# Ejercitan el endpoint HTTP real (TestClient), no solo `build_*_detail` en
# aislamiento (esa cobertura ya vive en `test_backlog_detail.py`), y cubren
# el caso borde: US sin `title` en frontmatter no rompe y cae al id.
# ---------------------------------------------------------------------------


def _seed_yaml_cabeceras(repo_path: Path) -> Path:
    """Backlog sintético en formato frontmatter YAML vigente (el que sí
    declara `user_story:` y `title:`): 1 Epic (AF-777), 1 US con título y
    2 Tasks con título."""
    backlog = repo_path / "02-backlog"
    (backlog / "epics").mkdir(parents=True)
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)

    (backlog / "epics" / "AF-777-epic.md").write_text(
        "---\nid: AF-777\ntype: epic\ntitle: Epic de prueba\nstate: READY\n"
        "dependencies: []\n---\n\n## Objetivo\n\nObjetivo.\n",
        encoding="utf-8",
    )
    (backlog / "user-stories" / "US-AF777-01.md").write_text(
        "---\nid: US-AF777-01\ntype: user_story\ntitle: Historia real\nstate: READY\n"
        "dependencies: []\nepic: AF-777\npriority: Media\n---\n\n"
        "## Historia\n\nHistoria.\n\n## Criterios de aceptación\n\n1. Y.\n",
        encoding="utf-8",
    )
    (backlog / "tasks" / "T-AF777-US01-01.md").write_text(
        "---\nid: T-AF777-US01-01\ntype: task\ntitle: Task real\nstate: READY\n"
        "dependencies: []\nepic: AF-777\nuser_story: US-AF777-01\npriority: Alta\n---\n\n"
        "## Objetivo\n\nObjetivo.\n\n## Criterios de aceptación\n\n1. Y.\n",
        encoding="utf-8",
    )
    (backlog / "tasks" / "T-AF777-US01-02.md").write_text(
        "---\nid: T-AF777-US01-02\ntype: task\ntitle: Segunda task\nstate: DONE\n"
        "dependencies: []\nepic: AF-777\nuser_story: US-AF777-01\npriority: Baja\n---\n\n"
        "## Objetivo\n\nObjetivo.\n\n## Criterios de aceptación\n\n1. Y.\n",
        encoding="utf-8",
    )
    return backlog


def test_get_backlog_epic_returns_title_in_each_user_story(tmp_path: Path, monkeypatch) -> None:
    """T-AF036-US19-03: `GET /backlog/{epic_id}` devuelve `title` en cada
    entrada de `user_stories[]` — el contrato que la web usa para pintar
    `ID + nombre` en las filas de User Story."""
    repo_path = _active_project(tmp_path, monkeypatch)
    _seed_yaml_cabeceras(repo_path)
    client = TestClient(create_app())

    response = client.get("/backlog/AF-777")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "AF-777"
    titles = {us["id"]: us["title"] for us in body["user_stories"]}
    assert titles == {"US-AF777-01": "Historia real"}


def test_get_backlog_user_story_returns_title_in_item_and_tasks(tmp_path: Path, monkeypatch) -> None:
    """T-AF036-US19-03: `GET /backlog/{us_id}` devuelve `title` en el propio
    item y en cada `tasks[i]` — el contrato de la fila de Task anidada."""
    repo_path = _active_project(tmp_path, monkeypatch)
    _seed_yaml_cabeceras(repo_path)
    client = TestClient(create_app())

    response = client.get("/backlog/US-AF777-01")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "US-AF777-01"
    assert body["title"] == "Historia real"
    task_titles = {t["id"]: t["title"] for t in body["tasks"]}
    assert task_titles == {
        "T-AF777-US01-01": "Task real",
        "T-AF777-US01-02": "Segunda task",
    }


def test_get_backlog_user_story_without_title_falls_back_to_id(tmp_path: Path, monkeypatch) -> None:
    """T-AF036-US19-03 (caso borde): una US cuyo frontmatter no declara
    `title` no rompe el endpoint — `title` cae al id (el mismo fallback que
    la web muestra como solo-ID)."""
    repo_path = _active_project(tmp_path, monkeypatch)
    backlog = repo_path / "02-backlog"
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "user-stories" / "US-AF776-01.md").write_text(
        "---\nid: US-AF776-01\ntype: user_story\nstate: READY\n"
        "dependencies: []\nepic: AF-776\npriority: Media\n---\n\n"
        "## Historia\n\nHistoria.\n\n## Criterios de aceptación\n\n1. Y.\n",
        encoding="utf-8",
    )
    client = TestClient(create_app())

    response = client.get("/backlog/US-AF776-01")

    assert response.status_code == 200
    assert response.json()["title"] == "US-AF776-01"

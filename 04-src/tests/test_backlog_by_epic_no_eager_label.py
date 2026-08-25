"""Tests deterministas de la resolución de `epic_label` del informe raíz
(T-AF048-US03-01/-02/-03, US-AF048-03).

- T-AF048-US03-01: `_epic_label_from_file` no debe invocarse en los
  argumentos de un `setdefault` (evaluación eager) — solo al crear un grupo.
- T-AF048-US03-02: en el caso canónico (Epics en `graph.items` con `title`
  no vacío) el `epic_label` se resuelve DESDE EL GRAFO, sin re-leer ningún
  fichero de Epic; el fallback sigue vivo para Epics referenciadas cuya Epic
  no existe o no tiene `title`.
- T-AF048-US03-03: tests deterministas sobre backlog en `tmp_path` que anclan
  (a) contador de re-lecturas 844→0 en el caso canónico, (b) salida del
  informe IDÉNTICA entre la resolución legada (siempre fichero) y la nueva
  (desde el grafo), y (c) el fallback.

Los tests que citan el backlog REAL de Atlas Forge (raíz del repo) se
conservan como comprobación de integración; los deterministas de la Task
usar ` tmp_path` (sin depender del repo)."""
from pathlib import Path

from atlas_forge.backlog.report import (
    build_backlog_report,
)

_REPO_BACKLOG = Path(__file__).resolve().parents[2] / "02-backlog"


def _seed_backlog(tmp_path: Path, epics: int = 52) -> Path:
    """Backlog de prueba en `tmp_path` con `epics` Epics (cada una con
    `title`) y 2 US + 1 Task por Epic — un caso canónico amplio como el del
    repo real (51 grupos)."""
    backlog = tmp_path / "02-backlog"
    (backlog / "epics").mkdir(parents=True)
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)
    for n in range(1, epics + 1):
        epic_id = f"AF-{n:03d}"
        (backlog / "epics" / f"{epic_id}-epic.md").write_text(
            "---\n"
            f"id: {epic_id}\ntype: epic\ntitle: Epic {n}\nstate: READY\n"
            "dependencies: []\n"
            "---\n\n## Objetivo\n\nO.\n",
            encoding="utf-8",
        )
        us_ranges = (1, 25, 49)  # para repartir el primer índice (n-1)*100
        for k, us_n in enumerate((n, n + epics, n + 2 * epics), start=1):
            us_id = f"US-AF{n:03d}-{us_n:02d}"
            (backlog / "user-stories" / f"{us_id}.md").write_text(
                "---\n"
                f"id: {us_id}\ntype: user_story\ntitle: {us_id}\nstate: READY\n"
                f"updated_at: 2026-08-25T00:00:00+00:00\n"
                f"dependencies: []\nepic: {epic_id}\npriority: Alta\nversion: 0.9\n"
                "---\n\n## Historia\n\nH.\n\n## Criterios de aceptación\n\n- C.\n",
                encoding="utf-8",
            )
    return backlog


def test_epic_label_se_resuelve_menos_de_60_veces_sobre_el_backlog_real(monkeypatch) -> None:
    """Criterio US03-01/2: tras eliminar la eager y resolver desde el grafo,
    la re-lectura de fichero queda en mínimos absolutos."""
    import atlas_forge.backlog.report as report_module

    calls = {"count": 0}
    original = report_module._epic_label_from_file

    def counting(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(report_module, "_epic_label_from_file", counting)

    report = build_backlog_report(_REPO_BACKLOG)

    assert calls["count"] < 60, (
        f"_epic_label_from_file se resolvió {calls['count']} veces; "
        "esperado < 60 (una por grupo nuevo, no por cada US/Task hijo)."
    )
    assert len(report["by_epic"]) > 0
    assert all(entry.get("epic_label") for entry in report["by_epic"] if entry["epic"] != "(sin epic)")


def test_epic_label_canonico_resuelto_desde_el_grafo_cero_lecturas_de_fichero(monkeypatch) -> None:
    """Criterio US03-02/1: en el caso canónico, `_epic_label_from_file` NO se
    invoca en absoluto dentro de `build_backlog_report` del backlog real — el
    `epic_label` sale de `graph.items[label].title`."""
    import atlas_forge.backlog.report as report_module

    calls = {"count": 0}
    original = report_module._epic_label_from_file

    def counting(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(report_module, "_epic_label_from_file", counting)

    report = build_backlog_report(_REPO_BACKLOG)

    assert calls["count"] == 0, (
        f"_epic_label_from_file SE invocó {calls['count']} veces; en el caso "
        "canónico (Epics en graph.items con title) debe ser 0."
    )
    # Los epic_label son títulos reales del grafo (no el id crudo).
    by_epic = sorted(report["by_epic"], key=lambda e: e["epic"])
    assert all(entry["epic_label"] for entry in by_epic if entry["epic"] != "(sin epic)")


def test_fallback_epic_referenciada_sin_fichero_se_resuelve_sin_lanzar(tmp_path: Path, monkeypatch) -> None:
    """Criterio US03-02/2 (fallback): una Epic referenciada por un hijo cuyo
    fichero no existe (o Epic sin fichero) sigue resolviéndose vía
    `_epic_label_from_file` (que devuelve el event_id si el fichero tampoco
    existe), sin lanzar."""
    # Backlog sintético mínimo: una US referenciando una Epic AF-000 que no
    # tiene fichero (pero de la que SÍ habrá un fichero con title en otra
    # parte, para probar ambos vías: label con fichero y sin fichero).
    projects = tmp_path / "02-backlog"
    (projects / "epics").mkdir(parents=True, exist_ok=True)
    (projects / "user-stories").mkdir(parents=True)

    # Epic con fichero y title (legacy: si no está en graph.items, se lee).
    (projects / "epics" / "AF-001-epic.md").write_text(
        "---\nid: AF-001\ntype: epic\ntitle: Legado con fichero\nstate: READY\n"
        "dependencies: []\n---\n\n## Objetivo\n\nO.\n",
        encoding="utf-8",
    )

    def _us(us_id: str, epic: str) -> None:
        (projects / "user-stories" / f"{us_id}.md").write_text(
            "---\n"
            f"id: {us_id}\ntype: user_story\ntitle: {us_id}\nstate: READY\n"
            f"updated_at: 2026-08-25T00:00:00+00:00\ndependencies: []\n"
            f"epic: {epic}\npriority: Alta\nversion: 0.9\n"
            "---\n\n## Historia\n\nH.\n\n## Criterios de aceptación\n\n- C.\n",
            encoding="utf-8",
        )

    # US referenciando AF-001 (con fichero/título) y una Epic inexistente
    # AF-999 completamente (sin fichero).
    _us("US-AF001-01", "AF-001")
    _us("US-AF001-02", "AF-001")
    _us("US-AF999-01", "AF-999")

    # Construir el informe. AF-001 tiene fichero → epic_label leído (fallback
    # _epic_label_from_file) o desde grafo si está; AF-999 no tiene fichero →
    # epic_label = "AF-999". Ninguna de las dos puede lanzar.
    report = build_backlog_report(projects)

    by_epic = {entry["epic"]: entry["epic_label"] for entry in report["by_epic"]}
    # AF-999 (Epic inexistente) cae al fallback del propio epic_id, nunca
    # una excepción.
    assert by_epic.get("AF-999") == "AF-999"
    # AF-001 está en graph.items (se carga del fichero) → title desde el grafo.
    assert by_epic.get("AF-001") == "Legado con fichero"


def test_by_epic_resultado_identico_sin_monkeypatch() -> None:
    # Criterio 3: el informe (by_epic + epic_label) se mantiene íntegro.
    report = build_backlog_report(_REPO_BACKLOG)
    by_epic = sorted(report["by_epic"], key=lambda e: e["epic"])
    assert len(by_epic) > 0
    assert all(entry["epic"] for entry in by_epic)
    for entry in by_epic:
        if entry["epic"] == "(sin epic)":
            continue
        assert entry["epic_label"], entry["epic"]

# ---------------------------------------------------------------------------
# T-AF048-US03-03: anclas deterministas sobre backlog de prueba en `tmp_path`.
# ---------------------------------------------------------------------------


def test_canonico_50_epics_cero_lecturas_de_fichero_tmp_path(tmp_path: Path, monkeypatch) -> None:
    """Criterio 1 (ancla cuantitativa US03-03): sobre un backlog de prueba con
    52 Epics (con title) + US/Tasks, `build_backlog_report` resuelve
    `epic_label` con 0 lecturas de fichero — falla si reaparece la re-lectura
    por hijo (contador > 0 en el caso canónico)."""
    import atlas_forge.backlog.report as report_module

    backlog = _seed_backlog(tmp_path)
    calls = {"count": 0}
    original = report_module._epic_label_from_file

    def counting(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(report_module, "_epic_label_from_file", counting)

    report = build_backlog_report(backlog)

    assert calls["count"] == 0, (
        f"_epic_label_from_file se invocó {calls['count']} veces en el caso "
        "canónico; esperado 0 (ancla 844→0 de la US-AF048-03)."
    )
    assert len(report["by_epic"]) == 52
    assert all(entry["epic_label"] for entry in report["by_epic"])


def test_salida_identica_legacy_fichv_vs_graph_tmp_path(tmp_path: Path, monkeypatch) -> None:
    """Criterio 2 (igualdad estricta): sobre el MISMO backlog de prueba, el
    dict completo de `build_backlog_report` con la resolución LEGADA (siempre
    `_epic_label_from_file`) es IGUAL al de la resolución nueva (desde el
    grafo) — diff estricto, sin campos aditivos extra aquí (los campos
    aditivos del informe —`version`, `fase`, etc.— los produce la misma
    función en ambos casos; solo cambia la procedencia del label y ambos son
    iguales porque `title` del grafo == `title` del fichero)."""
    import atlas_forge.backlog.report as report_module

    backlog = _seed_backlog(tmp_path)
    inherited = report_module._resolve_epic_label

    def legacy_resolver(graph, label, backlog_path):
        # Resolución pre-T-AF048-US03-02: siempre lee el fichero.
        return report_module._epic_label_from_file(backlog_path, label)

    monkeypatch.setattr(report_module, "_resolve_epic_label", legacy_resolver)
    report_legacy = build_backlog_report(backlog)
    monkeypatch.setattr(report_module, "_resolve_epic_label", inherited)
    report_new = build_backlog_report(backlog)

    assert report_legacy == report_new, (
        "El informe con la resolución legada (siempre fichero) debe ser "
        "IDÉNTICO al de la resolución desde el grafo (caso canónico)."
    )
    assert len(report_new["by_epic"]) == 52


def test_fallback_epic_referenciada_sin_titulo_se_resuelve_tmp_path(tmp_path: Path, monkeypatch) -> None:
    """Criterio 3 (fallback): una Epic referenciada por sus US cuyo `title`
    está vacío (o la Epic no existe) sigue resolviéndose vía
    `_epic_label_from_file`, sin lanzar — y el valor es verificable en el
    JSON."""
    import atlas_forge.backlog.report as report_module

    # Epic con fichero pero SIN title.
    projects = tmp_path / "sin-titulo"
    (projects / "epics").mkdir(parents=True)
    (projects / "user-stories").mkdir(parents=True)
    (projects / "epics" / "AF-001-epic.md").write_text(
        "---\nid: AF-001\ntype: epic\nstate: READY\ndependencies: []\n"
        "---\n\n## Objetivo\n\nO.\n",
        encoding="utf-8",
    )
    us_path = projects / "user-stories" / "US-AF001-01.md"
    us_path.write_text(
        "---\nid: US-AF001-01\ntype: user_story\ntitle: U1\nstate: READY\n"
        "updated_at: 2026-08-25T00:00:00+00:00\ndependencies: []\n"
        "epic: AF-001\npriority: Alta\nversion: 0.9\n"
        "---\n\n## Historia\n\nH.\n\n## Criterios de aceptación\n\n- C.\n",
        encoding="utf-8",
    )

    calls = {"count": 0}
    original = report_module._epic_label_from_file

    def counting(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(report_module, "_epic_label_from_file", counting)

    report = build_backlog_report(projects)

    # `title` ausente → cae al fallback (_epic_label_from_file), que devuelve
    # el propio epic_id; se llamó exactamente una vez (al crear el grupo).
    assert calls["count"] == 1
    by_epic = {entry["epic"]: entry["epic_label"] for entry in report["by_epic"]}
    assert by_epic["AF-001"] == "AF-001"

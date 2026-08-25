"""Tests deterministas de la resolución de `epic_label` del informe raíz
(T-AF048-US03-01/-02, US-AF048-03).

- T-AF048-US03-01: `_epic_label_from_file` no debe invocarse en los
  argumentos de un `setdefault` (evaluación eager) — solo al crear un grupo.
- T-AF048-US03-02: en el caso canónico (Epics en `graph.items` con `title`
  no vacío) el `epic_label` se resuelve DESDE EL GRAFO, sin re-leer ningún
  fichero de Epic (`_epic_label_from_file` con contador == 0 dentro de
  `build_backlog_report` sobre el backlog real); el fallback sigue vivo para
  Epics referenciadas por hijo/os cuya Epic no existe o no tiene `title`.

Se recorre el backlog REAL de Atlas Forge (raíz del repo), el mismo que los
criterios citan — no un fixture sintético."""
from pathlib import Path

from atlas_forge.backlog.report import (
    build_backlog_report,
)

_REPO_BACKLOG = Path(__file__).resolve().parents[2] / "02-backlog"


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
    (projects / "epics" / "AF-001.md").write_text(
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
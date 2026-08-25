"""Tests del gate de auditoría del cierre de versión (T-AF018-US03-03,
`scripts/close_version.py --verify`).

Deterministas, SIN tmux ni agentes: simulan los informes de los pasos 1 y 2
(`auditar-backlog` / `verificar-auditoria`) tal como los persiste
`transversal.py` y verifican que `--verify` decide PASA/BLOQUEADO según las
discrepancias críticas confirmadas por el Auditor:

- criterio 1: `--verify` devuelve una decisión de gate (PASA -> exit 0,
  BLOQUEADO -> exit != 0 y referencia el informe del paso 2);
- criterio 2: un item DONE confirmado incompleto bloquea; sin discrepancias
  confirmadas no bloquea;
- criterio 3: `--verify` no altera `--check`/`--apply` (solo añade el modo y
  el gate es independiente del control declarativo de no-DONE);
- criterio 4: no introduce cadencia periódica (simple: no hay watcher en
  `--verify`);
- criterio 5: informe simulado con y sin hallazgos críticos.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "close_version.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("close_version", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def module():
    return _load_module()


def _step1_report(
    hallazgos: str,
) -> str:
    return (
        "# Informe de acción · auditar-backlog\n\n"
        "Fecha: 2026-08-24 00:00:00 UTC\n"
        "Proyecto: test\n"
        "Job ID: j1\n"
        "Estado: completed\n\n"
        "## Resultado\n\n"
        "Panorama general del backlog.\n\n"
        "## Hallazgos\n\n"
        f"{hallazgos}\n"
    )


def _step2_report(paso1_path: str, hallazgos: str) -> str:
    return (
        "# Informe de acción · verificar-auditoria\n\n"
        "Fecha: 2026-08-24 00:00:01 UTC\n"
        "Proyecto: test\n"
        "Job ID: j2\n"
        f"Fichero auditado (paso 1 de la auditoría): {paso1_path}\n\n"
        "## Resultado\n\n"
        "Verificación completada.\n\n"
        "## Hallazgos verificados\n\n"
        f"{hallazgos}\n"
    )


# ---------------------------------------------------------------------------
# Criterio 2: un DONE confirmado incompleto bloquea; sin discrepancias
# confirmadas no bloquea.
# ---------------------------------------------------------------------------


def test_done_confirmado_incompleto_bloquea(tmp_path: Path) -> None:
    module = _load_module()

    paso1 = _step1_report(
        "- id: US-AF900-01\n"
        "- estado_declarado: DONE\n"
        "- evidencia: modulo Ausente\n"
        "- veredicto: incompleto\n"
    )
    paso2 = _step2_report(
        "auditar-backlog-20260824.md",
        "- id: US-AF900-01\n"
        "- accion: corregir_estado\n"
        "- estado_correcto: READY\n"
        "- evidencia: el modulo no existe en 04-src\n",
    )

    decision, bloqueantes, sin_clasificar = module.evaluate_verify_gate(paso2, paso1)
    assert decision == "BLOQUEADO"
    assert "US-AF900-01" in bloqueantes
    assert sin_clasificar == []


def test_sin_discrepancias_confirmadas_pasa(tmp_path: Path) -> None:
    module = _load_module()

    paso1 = _step1_report(
        "- id: US-AF900-01\n"
        "- estado_declarado: DONE\n"
        "- veredicto: confirmado\n"
    )
    # El Auditor verifica el hallazgo y lo descarta (falso positivo).
    paso2 = _step2_report(
        "auditar-backlog-20260824.md",
        "- id: US-AF900-01\n"
        "- accion: descartar\n"
        "- evidencia: la implementacion existe en routes.py\n",
    )

    decision, bloqueantes, _ = module.evaluate_verify_gate(paso2, paso1)
    assert decision == "PASA"
    assert bloqueantes == []


def test_crear_task_correccion_bloquea(tmp_path: Path) -> None:
    module = _load_module()

    paso1 = _step1_report(
        "- id: T-AF900-01\n"
        "- estado_declarado: DONE\n"
        "- veredicto: incompleto\n"
    )
    paso2 = _step2_report(
        "auditar-backlog-20260824.md",
        "- id: T-AF900-01\n"
        "- accion: crear_task_correccion\n"
        "- evidencia: falta el caso de error\n",
    )

    decision, bloqueantes, _ = module.evaluate_verify_gate(paso2, paso1)
    assert decision == "BLOQUEADO"
    assert "T-AF900-01" in bloqueantes


# ---------------------------------------------------------------------------
# Criterio 2: correcciones que no tocan el borde del release no bloquean
# (READY -> IN_PROGRESS), pero un TO_DO/READY implementado (-> DONE) sí.
# ---------------------------------------------------------------------------


def test_corregir_estado_no_critico_pasa(tmp_path: Path) -> None:
    module = _load_module()

    paso1 = _step1_report(
        "- id: US-AF900-02\n"
        "- estado_declarado: READY\n"
        "- veredicto: confirmado\n"
    )
    paso2 = _step2_report(
        "auditar-backlog-20260824.md",
        "- id: US-AF900-02\n"
        "- accion: corregir_estado\n"
        "- estado_correcto: IN_PROGRESS\n"
        "- evidencia: la tarea empezo pero no termino\n",
    )

    decision, bloqueantes, _ = module.evaluate_verify_gate(paso2, paso1)
    assert decision == "PASA"


def test_implementado_pendiente_decision_bloquea(tmp_path: Path) -> None:
    module = _load_module()

    paso1 = _step1_report(
        "- id: US-AF900-03\n"
        "- estado_declarado: READY\n"
        "- veredicto: confirmado\n"
    )
    paso2 = _step2_report(
        "auditar-backlog-20260824.md",
        "- id: US-AF900-03\n"
        "- accion: corregir_estado\n"
        "- estado_correcto: DONE\n"
        "- evidencia: ya esta implementado, falta decidir su cierre\n",
    )

    decision, bloqueantes, _ = module.evaluate_verify_gate(paso2, paso1)
    assert decision == "BLOQUEADO"
    assert "US-AF900-03" in bloqueantes


# ---------------------------------------------------------------------------
# Robustez del parser: cruza el estado declarado con el paso 1 por id cuando
# el bloque del paso 2 no lo repite, y tolera el estado correcto en prosa.
# ---------------------------------------------------------------------------


def test_cruza_estado_declarado_con_el_paso1(tmp_path: Path) -> None:
    module = _load_module()

    paso1 = _step1_report(
        "- id: US-AF900-04\n"
        "- estado_declarado: DONE\n"
        "- veredicto: incompleto\n"
    )
    # El paso 2 no repite estado_declarado: se resuelve desde el paso 1.
    paso2 = _step2_report(
        "auditar-backlog-20260824.md",
        "- id: US-AF900-04\n"
        "- accion: corregir_estado\n"
        "- estado_correcto: TO_DEVELOP\n",
    )

    decision, bloqueantes, _ = module.evaluate_verify_gate(paso2, paso1)
    assert decision == "BLOQUEADO"


def test_estado_correcto_en_prosa_tolerado(tmp_path: Path) -> None:
    module = _load_module()

    paso1 = _step1_report(
        "- id: US-AF900-05\n"
        "- estado_declarado: DONE\n"
        "- veredicto: incompleto\n"
    )
    # Sin `- estado_correcto:` estructurado; el parser lo extrae del texto.
    paso2 = _step2_report(
        "auditar-backlog-20260824.md",
        "- id: US-AF900-05\n"
        "- accion: corregir_estado\n"
        "- evidencia: corregir_estado de DONE a READY, sigue sin cerrar\n",
    )

    decision, bloqueantes, _ = module.evaluate_verify_gate(paso2, paso1)
    assert decision == "BLOQUEADO"


def test_sin_hallazgos_pasa(tmp_path: Path) -> None:
    module = _load_module()

    decision, bloqueantes, _ = module.evaluate_verify_gate("", "")
    assert decision == "PASA"
    assert bloqueantes == []
    # Decision independence: un paso 2 inexistente (None) no bloquea por sí.
    decision2, _, _ = module.evaluate_verify_gate("Sin hallazgos.", "")
    assert decision2 == "PASA"


# ---------------------------------------------------------------------------
# Criterio 1 y 3: `_verify_decision_from_reports` (informes simulados en
# disco) devuelve PASA/BLOQUEADO, y `_run_verify` traduce la decision a exit
# 0 / exit != 0 sin tocar el esqueleto de --check/--apply.
# ---------------------------------------------------------------------------


def test_decision_desde_informes_en_disco(module, tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "auditar-backlog-20260824.md").write_text(
        _step1_report(
            "- id: US-AF900-06\n"
            "- estado_declarado: DONE\n"
            "- veredicto: incompleto\n"
        ),
        encoding="utf-8",
    )
    (reports / "verificar-auditoria-20260824.md").write_text(
        _step2_report(
            "auditar-backlog-20260824.md",
            "- id: US-AF900-06\n"
            "- accion: crear_task_correccion\n",
        ),
        encoding="utf-8",
    )

    decision, bloqueantes, _ = module._verify_decision_from_reports(
        reports / "auditar-backlog-20260824.md",
        reports / "verificar-auditoria-20260824.md",
    )
    assert decision == "BLOQUEADO"
    assert "US-AF900-06" in bloqueantes


def test_run_verify_libera_o_bloquea(
    module, monkeypatch, tmp_path: Path, capsys
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    paso1 = reports / "auditar-backlog-20260824.md"
    paso1.write_text(
        _step1_report(
            "- id: US-AF900-07\n"
            "- estado_declarado: DONE\n"
            "- veredicto: confirmado\n"
        ),
        encoding="utf-8",
    )
    paso2 = reports / "verificar-auditoria-20260824.md"
    paso2.write_text(
        _step2_report(
            "auditar-backlog-20260824.md",
            "- id: US-AF900-07\n- accion: descartar\n",
        ),
        encoding="utf-8",
    )
    # Sin discrepancias críticas -> PASA -> exit 0.
    monkeypatch.setattr(module, "_run_auditoria_paso1", lambda: paso1)
    monkeypatch.setattr(module, "_run_verificacion_paso2", lambda path: paso2)
    assert module._run_verify("0.9") == 0
    capsys.readouterr()

    # Con un DONE incompleto confirmado -> BLOQUEADO -> exit != 0 y la salida
    # referencia el informe del paso 2.
    paso1.write_text(
        _step1_report(
            "- id: US-AF900-08\n"
            "- estado_declarado: DONE\n"
            "- veredicto: incompleto\n"
        ),
        encoding="utf-8",
    )
    paso2.write_text(
        _step2_report(
            "auditar-backlog-20260824.md",
            "- id: US-AF900-08\n"
            "- accion: corregir_estado\n"
            "- estado_correcto: READY\n",
        ),
        encoding="utf-8",
    )
    assert module._run_verify("0.9") == 1
    captured = capsys.readouterr()
    assert "BLOQUEADO" in captured.err
    assert "verificar-auditoria" in captured.err


def _us_versioned(stories_dir: Path, us_id: str, *, version: str, state: str) -> None:
    stories_dir.mkdir(parents=True, exist_ok=True)
    path = stories_dir / f"{us_id}.md"
    path.write_text(
        "---\n"
        f"id: {us_id}\ntype: user_story\ntitle: {us_id}\nstate: {state}\n"
        f"updated_at: 2026-08-24T00:00:00+00:00\n"
        "dependencies: []\nepic: AF-999\npriority: Alta\n"
        f"version: {version}\n"
        "---\n\n## Historia\n\nH.\n\n## Criterios de aceptación\n\n- C.\n",
        encoding="utf-8",
    )


def test_verify_es_modo_adicional_y_no_toca_apply(
    module, monkeypatch, tmp_path: Path
) -> None:
    """Criterio 3: `--verify` solo añade un modo. Se invoca incluso con US
    no-DONE asignadas (su gate es del Auditor, no del control declarativo de
    --check) y devuelve la decision del gate sin escribir el esquema."""
    backlog = tmp_path / "02-backlog"
    version_file = tmp_path / "version.yml"
    version_file.write_text(
        "current_closed: null\nopen: \"0.9\"\nfuture:\n  - \"0.9.1\"\n  - \"0.9.2\"\n",
        encoding="utf-8",
    )
    # Una US no-DONE asignada a la version abierta.
    _us_versioned(backlog / "user-stories", "US-AF900-10", version="0.9", state="READY")

    monkeypatch.setattr(module, "BACKLOG", backlog / "user-stories")
    monkeypatch.setattr(module, "VERSION_FILE", version_file)
    calls: list[str] = []
    monkeypatch.setattr(
        module, "_run_verify", lambda closing: (calls.append(closing), 7)[1]
    )

    assert module.main(["--verify"]) == 7
    assert calls == ["0.9"]
    # El esquema NO se escribió: --verify no es --apply.
    schema = version_file.read_text(encoding="utf-8")
    assert '"0.9.1"' in schema
    assert "current_closed: 0.9" not in schema


def test_check_y_apply_inalterados(module, monkeypatch, tmp_path: Path) -> None:
    """Criterio 3: --check y --apply conservan su contrato original."""
    backlog = tmp_path / "02-backlog"
    version_file = tmp_path / "version.yml"
    version_file.write_text(
        "current_closed: null\nopen: \"0.9\"\nfuture:\n  - \"0.9.1\"\n  - \"0.9.2\"\n",
        encoding="utf-8",
    )
    _us_versioned(backlog / "user-stories", "US-AF900-11", version="0.9", state="DONE")
    _us_versioned(backlog / "user-stories", "US-AF900-12", version="0.9", state="READY")

    monkeypatch.setattr(module, "BACKLOG", backlog / "user-stories")
    monkeypatch.setattr(module, "VERSION_FILE", version_file)

    # --check: exit 1 con US no-DONE.
    assert module.main(["--check"]) == 1
    # --apply: exit 1 con US no-DONE (nada escrito).
    assert module.main(["--apply"]) == 1
    schema = version_file.read_text(encoding="utf-8")
    assert "current_closed: null" in schema

    # Con todas DONE, --apply escribe el esquema (comportamiento heredado).
    _us_versioned(backlog / "user-stories", "US-AF900-12", version="0.9", state="DONE")
    assert module.main(["--apply"]) == 0
    schema = version_file.read_text(encoding="utf-8")
    assert "current_closed:" in schema
    assert "0.9" in schema.splitlines()[0]


def test_latest_report_elige_el_mas_reciente(
    module, monkeypatch, tmp_path: Path
) -> None:
    """Descubrimiento de informes: `_latest_report` elige el fichero del
    mismo `action_id` más reciente (los informes se persisten con fecha)."""
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr(module, "REPORTS_DIR", reports)

    old = reports / "auditar-backlog-20260823.md"
    new = reports / "auditar-backlog-20260824.md"
    old.write_text("a", encoding="utf-8")
    new.write_text("b", encoding="utf-8")
    import os as _os

    _os.utime(old, (1_000_000, 1_000_000))
    _os.utime(new, (1_000_000, 2_000_000))

    assert module._latest_report("auditar-backlog") == new
    assert module._latest_report("verificar-auditoria") is None
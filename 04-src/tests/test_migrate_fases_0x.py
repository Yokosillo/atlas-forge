"""Tests de la migración T-AF036-US14-06: `fase` 0.x de las User Stories
a `Fase 0.9` (`scripts/migrate_af036_us14_06_fases.py`).

Cubre los criterios de aceptación de la Task sobre un fixture de backlog
sintético con fases 0.x mezcladas con las válidas y sin fase:
- migra solo las User Stories con 0.x;
- NO toca Epics (su fase la gestiona US-AF036-18);
- idempotente (segunda ejecución no cambia nada);
- deja el validador determinista sin errores de fase.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from atlas_forge.backlog.validator_v2 import validate_backlog_file_v2

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "migrate_af036_us14_06_fases.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("migrate_fases", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _us(path: Path, us_id: str, fase: str | None) -> None:
    fase_line = f"fase: {fase}\n" if fase is not None else ""
    _write(
        path / "user-stories" / f"{us_id}.md",
        "---\n"
        f"id: {us_id}\ntype: user_story\ntitle: {us_id}\nstate: READY\n"
        f"dependencies: []\nepic: AF-999\npriority: Alta\n{fase_line}"
        "---\n\n## Historia\n\nH.\n\n## Criterios de aceptación\n\n- C.\n",
    )


def _epic(path: Path, epic_id: str, fase: str) -> None:
    _write(
        path / "epics" / f"{epic_id}.md",
        "---\n"
        f"id: {epic_id}\ntype: epic\ntitle: {epic_id}\nstate: TO_DO\n"
        f"dependencies: []\n{fase}\n"
        "---\n\n## Objetivo\n\nO.\n",
    )


def _seed(tmp_path: Path) -> Path:
    backlog = tmp_path / "02-backlog"
    # User Stories: 0.x (a migrar), válidas, SIN_ASIGNAR, null, sin fase.
    _us(backlog, "US-AF900-01", "Fase 0.1")
    _us(backlog, "US-AF900-02", "Fase 0.3")
    _us(backlog, "US-AF900-03", "Fase 0.8")
    _us(backlog, "US-AF900-04", "Fase 0.9")
    _us(backlog, "US-AF900-05", "Fase 0.9.1")
    _us(backlog, "US-AF900-06", "SIN_ASIGNAR")
    _us(backlog, "US-AF900-07", "null")
    _us(backlog, "US-AF900-08", None)  # sin campo fase
    # Epics con 0.x: NO deben tocarse (US-AF036-18).
    _epic(backlog, "AF-910", "fase: Fase 0.1")
    return backlog


def _fase_of(backlog: Path, item_id: str) -> str | None:
    candidate = next(
        (
            p
            for subdir in ("user-stories", "epics")
            for p in (backlog / subdir).glob(f"{item_id}.md")
        ),
        None,
    )
    assert candidate is not None, f"No se encontró {item_id}"
    content = candidate.read_text(encoding="utf-8")
    for line in content.splitlines():
        if line.startswith("fase:"):
            return line.split(":", 1)[1].strip()
    return None


def test_migrates_only_user_stories_with_0x(tmp_path: Path) -> None:
    module = _load_module()
    backlog = _seed(tmp_path)

    changed, skipped = module.migrate_user_stories(backlog)

    # Migradas las 3 US con 0.x (0.1, 0.3, 0.8); el resto sin cambio.
    assert changed == 3
    assert skipped == 5
    assert _fase_of(backlog, "US-AF900-01") == "Fase 0.9"
    assert _fase_of(backlog, "US-AF900-02") == "Fase 0.9"
    assert _fase_of(backlog, "US-AF900-03") == "Fase 0.9"
    # No se tocan las ya válidas / sin fase.
    assert _fase_of(backlog, "US-AF900-04") == "Fase 0.9"
    assert _fase_of(backlog, "US-AF900-05") == "Fase 0.9.1"
    assert _fase_of(backlog, "US-AF900-06") == "SIN_ASIGNAR"
    assert _fase_of(backlog, "US-AF900-07") == "null"
    assert _fase_of(backlog, "US-AF900-08") is None
    # Las Epics con 0.x NO se tocan.
    assert _fase_of(backlog, "AF-910") == "Fase 0.1"


def test_is_idempotent(tmp_path: Path) -> None:
    module = _load_module()
    backlog = _seed(tmp_path)

    module.migrate_user_stories(backlog)
    changed, _ = module.migrate_user_stories(backlog)

    assert changed == 0  # segunda ejecución no cambia nada


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    module = _load_module()
    backlog = _seed(tmp_path)

    changed, _ = module.migrate_user_stories(backlog, dry=True)

    assert changed == 3
    assert _fase_of(backlog, "US-AF900-01") == "Fase 0.1"  # no se escribió


def test_validator_passes_after_migration(tmp_path: Path) -> None:
    module = _load_module()
    backlog = _seed(tmp_path)

    module.migrate_user_stories(backlog)

    # Todas las User Stories pasan el validador sin errores de fase.
    for p in (backlog / "user-stories").glob("*.md"):
        result = validate_backlog_file_v2(p)
        assert result.valid, f"{p.name}: {result.errors}"

def _field_of(backlog: Path, item_id: str, field: str) -> str | None:
    candidate = next(
        (
            p
            for subdir in ("user-stories", "epics")
            for p in (backlog / subdir).glob(f"{item_id}.md")
        ),
        None,
    )
    assert candidate is not None, f"No se encontró {item_id}"
    content = candidate.read_text(encoding="utf-8")
    for line in content.splitlines():
        if line.startswith(field + ":"):
            return line.split(":", 1)[1].strip()
    return None


def test_migrate_epics_replaces_fase_with_version_0_9(tmp_path: Path) -> None:
    """T-AF036-US18-03: una Epic con `fase` pasa a `version: 0.9` (sin fase)."""
    module = _load_module()
    backlog = _seed(tmp_path)

    changed, _ = module.migrate_epics(backlog)

    assert changed == 1  # solo AF-910 (la única Epic del fixture con fase)
    assert _field_of(backlog, "AF-910", "version") == "0.9"
    assert _field_of(backlog, "AF-910", "fase") is None
    # Las User Stories conservan su fase (no las toca este modo).
    assert _field_of(backlog, "US-AF900-01", "fase") == "Fase 0.1"


def test_migrate_epics_is_idempotent(tmp_path: Path) -> None:
    module = _load_module()
    backlog = _seed(tmp_path)

    module.migrate_epics(backlog)
    changed, _ = module.migrate_epics(backlog)

    assert changed == 0


def test_migrate_epics_keeps_existing_version(tmp_path: Path) -> None:
    """T-AF036-US18-03: si la Epic ya declara `version`, no se pisa — solo
    se retira la `fase` residual."""
    module = _load_module()
    backlog = tmp_path / "02-backlog"
    _write(
        backlog / "epics" / "AF-920.md",
        "---\nid: AF-920\ntype: epic\ntitle: AF-920\nstate: TO_DO\n"
        "dependencies: []\nversion: 1.2\nfase: Fase 0.1\n"
        "---\n\n## Objetivo\n\nO.\n",
    )

    changed, _ = module.migrate_epics(backlog)

    assert changed == 1
    assert _field_of(backlog, "AF-920", "version") == "1.2"  # no se pisa
    assert _field_of(backlog, "AF-920", "fase") is None


def test_migrate_epics_dry_run_writes_nothing(tmp_path: Path) -> None:
    module = _load_module()
    backlog = _seed(tmp_path)

    changed, _ = module.migrate_epics(backlog, dry=True)

    assert changed == 1
    assert _field_of(backlog, "AF-910", "fase") == "Fase 0.1"  # no se escribió

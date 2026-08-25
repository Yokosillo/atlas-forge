"""Tests de la migración T-AF036-US24-01 (US-AF036-24): `fase` → `version`
en las User Stories, con default `0.9.2` para lo no asignado
(`scripts/migrate_af036_us24_01_fase_a_version.py`).

Cubre los criterios de aceptación de la Task sobre un fixture de backlog
sintético con las tres fuentes (`Fase 0.9` / `Fase 0.9.1` / `SIN_ASIGNAR`
/ `null`) y un caso con `version` preexistente:
- migra las User Stories con `fase` a `version` (mapeo correcto);
- NO toca Epics (US-AF036-18) ni US sin campo `fase`;
- idempotente (segunda ejecución no cambia nada);
- `--dry` no escribe en disco;
- actualiza `updated_at` de cada US migrada;
- deja el validador determinista sin errores por `fase`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from atlas_forge.backlog.validator_v2 import validate_backlog_file_v2

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "migrate_af036_us24_01_fase_a_version.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("migrate_fase_a_version", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _us(
    path: Path,
    us_id: str,
    fase: str | None,
    version: str | None = None,
    updated_at: str | None = None,
) -> None:
    fase_line = f"fase: {fase}\n" if fase is not None else ""
    version_line = f"version: {version}\n" if version is not None else ""
    updated_line = f"updated_at: {updated_at}\n" if updated_at is not None else ""
    _write(
        path / "user-stories" / f"{us_id}.md",
        "---\n"
        f"id: {us_id}\ntype: user_story\ntitle: {us_id}\nstate: READY\n"
        f"{updated_line}"
        f"dependencies: []\nepic: AF-999\npriority: Alta\n"
        f"{version_line}{fase_line}"
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
    # User Stories: las tres fuentes de migración + null + sin fase.
    _us(backlog, "US-AF900-01", "Fase 0.9")       # -> 0.9
    _us(backlog, "US-AF900-02", "Fase 0.9.1")     # -> 0.9.1
    _us(backlog, "US-AF900-03", "SIN_ASIGNAR")    # -> 0.9.2
    _us(backlog, "US-AF900-04", "null")           # -> 0.9.2
    # Con `version` preexistente que debe reemplazarse por la derivada.
    _us(backlog, "US-AF900-05", "Fase 0.9", version="0.9.1")  # -> 0.9
    # Sin campo `fase` (ya migrada): no se toca.
    _us(backlog, "US-AF900-06", None, version="0.9.2")
    # Epic con `fase`: NO se toca (US-AF036-18).
    _epic(backlog, "AF-910", "fase: Fase 0.1")
    return backlog


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
    found = None
    for line in content.splitlines():
        if line.startswith(field + ":"):
            found = line.split(":", 1)[1].strip()
    return found


def test_migrates_user_stories_fase_to_version(tmp_path: Path) -> None:
    module = _load_module()
    backlog = _seed(tmp_path)

    changed, skipped = module.migrate_user_stories(backlog)

    assert changed == 5
    assert skipped == 1  # solo la US sin fase (US-AF900-06)
    # Mapeo correcto.
    assert _field_of(backlog, "US-AF900-01", "version") == "0.9"
    assert _field_of(backlog, "US-AF900-02", "version") == "0.9.1"
    assert _field_of(backlog, "US-AF900-03", "version") == "0.9.2"
    assert _field_of(backlog, "US-AF900-04", "version") == "0.9.2"
    # La `version` preexistente se reemplaza por la derivada de la `fase`.
    assert _field_of(backlog, "US-AF900-05", "version") == "0.9"
    # Ninguna US conserva `fase`.
    for sub in ("01", "02", "03", "04", "05"):
        assert _field_of(backlog, "US-AF900-" + sub, "fase") is None
    # La US sin fase se conserva intacta.
    assert _field_of(backlog, "US-AF900-06", "version") == "0.9.2"
    assert _field_of(backlog, "US-AF900-06", "fase") is None
    # La Epic con `fase` NO se toca.
    assert _field_of(backlog, "AF-910", "fase") == "Fase 0.1"


def test_does_not_touch_epics(tmp_path: Path) -> None:
    module = _load_module()
    backlog = _seed(tmp_path)

    module.migrate_user_stories(backlog)

    assert _field_of(backlog, "AF-910", "fase") == "Fase 0.1"


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

    assert changed == 5
    # No se escribió: la US-AF900-01 sigue con `fase` y sin `version`.
    assert _field_of(backlog, "US-AF900-01", "fase") == "Fase 0.9"
    assert _field_of(backlog, "US-AF900-01", "version") is None


def test_validator_passes_after_migration(tmp_path: Path) -> None:
    module = _load_module()
    backlog = _seed(tmp_path)

    module.migrate_user_stories(backlog)

    for p in (backlog / "user-stories").glob("*.md"):
        result = validate_backlog_file_v2(p)
        assert result.valid, f"{p.name}: {result.errors}"


def test_updates_updated_at(tmp_path: Path) -> None:
    """Criterio 4 de T-AF036-US24-02: cada US migrada actualiza su
    `updated_at` a un valor nuevo (no queda con el timestamp anterior)."""
    module = _load_module()
    backlog = tmp_path / "02-backlog"
    # Una US con `fase` y un `updated_at` antiguo conocido.
    _us(backlog, "US-AF900-01", "Fase 0.9", updated_at="2020-01-01T00:00:00+00:00")
    _us(backlog, "US-AF900-02", "SIN_ASIGNAR", updated_at="2020-01-01T00:00:00+00:00")
    # Una US sin `fase` (no se migra): su `updated_at` NO debe tocarse.
    _us(backlog, "US-AF900-03", None, version="0.9.2", updated_at="2020-01-01T00:00:00+00:00")

    module.migrate_user_stories(backlog)

    old = "2020-01-01T00:00:00+00:00"
    assert _field_of(backlog, "US-AF900-01", "updated_at") is not None
    assert _field_of(backlog, "US-AF900-01", "updated_at") != old
    assert _field_of(backlog, "US-AF900-02", "updated_at") is not None
    assert _field_of(backlog, "US-AF900-02", "updated_at") != old
    # La US no migrada conserva su timestamp intacto.
    assert _field_of(backlog, "US-AF900-03", "updated_at") == old


# ---------------------------------------------------------------------------
# T-AF036-US24-06 (veredicto RECHAZADO de US-AF036-24): la migración debe
# dejar EXACTAMENTE una línea `version:` y NINGUNA `fase:` — el shape real
# del corpus tiene `version:` + `fase:` a la vez, con el `version` delante
# (ej. US-AF001-01) y casos con `fase: null`/`SIN_ASIGNAR`.
# ---------------------------------------------------------------------------


def _count_field(backlog: Path, item_id: str, field: str) -> int:
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
    return sum(
        1
        for line in content.splitlines()
        if line.strip().startswith(field + ":")
    )


def test_removes_residual_fase_in_real_corpus_shape(tmp_path: Path) -> None:
    """T-AF036-US24-06, criterio 1/2: una US con `version:` + `fase:` a la
    vez (el shape real del corpus, `version` delante y detrás) queda tras
    migrar con EXACTAMENTE una `version:` y NINGUNA `fase:` — sin importar
    el orden de los campos ni las comillas de la `version` preexistente."""
    module = _load_module()
    backlog = tmp_path / "02-backlog"
    for us_id, version_line, fase_line, expected in [
        # Orden real del corpus: `version:` delante de `fase:`.
        ("US-AF900-10", "version: 0.9\n", "fase: Fase 0.9\n", "0.9"),
        # Orden inverso: `fase:` delante de `version:`.
        ("US-AF900-11", "fase: Fase 0.9\n", "version: 0.9\n", "0.9"),
        # `version` preexistente con comillas que el regex antiguo podía
        # no retirar + `fase: null` (default 0.9.2).
        ("US-AF900-12", "version: '0.9'\n", "fase: null\n", "0.9.2"),
        # `fase: SIN_ASIGNAR` con `version` preexistente.
        ("US-AF900-13", "fase: SIN_ASIGNAR\n", "version: 0.9\n", "0.9.2"),
    ]:
        _write(
            backlog / "user-stories" / f"{us_id}.md",
            "---\n"
            f"id: {us_id}\ntype: user_story\ntitle: {us_id}\nstate: READY\n"
            "dependencies: []\nepic: AF-999\npriority: Alta\n"
            f"{version_line}{fase_line}"
            "---\n\n## Historia\n\nH.\n\n## Criterios de aceptación\n\n- C.\n",
        )

    changed, _ = module.migrate_user_stories(backlog)

    assert changed == 4
    for us_id in ("US-AF900-10", "US-AF900-11", "US-AF900-12", "US-AF900-13"):
        assert _count_field(backlog, us_id, "version") == 1, (
            f"{us_id} debe quedar con EXACTAMENTE una línea version (no "
            f"{_count_field(backlog, us_id, 'version')})"
        )
        assert _count_field(backlog, us_id, "fase") == 0, (
            f"{us_id} no debe conservar `fase:` residual"
        )
    # La versión derivada de la `fase` es la autoritativa.
    assert _field_of(backlog, "US-AF900-10", "version") == "0.9"
    assert _field_of(backlog, "US-AF900-11", "version") == "0.9"
    assert _field_of(backlog, "US-AF900-12", "version") == "0.9.2"
    assert _field_of(backlog, "US-AF900-13", "version") == "0.9.2"


def test_real_corpus_subset_migrated_has_no_residual_fase(tmp_path: Path) -> None:
    """T-AF036-US24-06, criterio 2/3/5: un subconjunto real de
    `02-backlog/user-stories/` (las US que hoy conservan `fase:`, el
    hallazgo del veredicto) migra sin dejar NINGÚN `fase:` residual y con
    exactamente una `version:` por fichero."""
    import shutil

    real_us = _SCRIPT_PATH.parents[2] / "02-backlog" / "user-stories"
    if not real_us.is_dir():
        pytest.skip("sin corpus real disponible")

    candidates = [
        p
        for p in sorted(real_us.glob("*.md"))
        if "fase:" in p.read_text(encoding="utf-8").split("\n---", 1)[0]
    ]

    dest = tmp_path / "02-backlog" / "user-stories"
    dest.mkdir(parents=True)
    for path in candidates:
        shutil.copy2(path, dest / path.name)

    module = _load_module()
    module.migrate_user_stories(tmp_path / "02-backlog")

    residual = []
    malformed = []
    for path in sorted(dest.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        frontmatter = text.split("\n---", 1)[0]
        version_count = sum(
            1 for line in frontmatter.splitlines() if line.strip().startswith("version:")
        )
        fase_count = sum(
            1 for line in frontmatter.splitlines() if line.strip().startswith("fase:")
        )
        if fase_count != 0:
            residual.append(path.name)
        if version_count != 1:
            malformed.append(f"{path.name} (version_lines={version_count})")

    # El corpus real contenía US con `fase:` (el genuino hallazgo del
    # veredicto) y tras migrar no queda ninguno.
    if candidates:
        assert residual == [], f"fase residual tras migrar: {residual}"
    assert malformed == []
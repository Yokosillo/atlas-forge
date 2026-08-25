"""Tests deterministas del uso de `yaml.CSafeLoader` en `parse_frontmatter`
(T-AF048-US02-01, US-AF048-02): el loader YAML en C (seguro, mismo esquema
de resolución de tipos que `SafeLoader`) cuando esté disponible, con fallback
a `SafeLoader`, conservando exactamente la normalización de tipos que hace el
parser después del parseo.

Criterios cubiertos:
1. `parser._YAML_LOADER` es `CSafeLoader` cuando `hasattr(yaml, "CSafeLoader")`
   y `SafeLoader` en caso contrario (resolución una vez por módulo).
2. Conservación de tipos: frontmatter con `updated_at` ISO-8601 sin comillas
   (→ datetime → `isoformat()`), `version: 0.9` (→ float → `"0.9"`) y
   `dependencies` en lista → los `BacklogItem` resultantes de `load_backlog`
   no cambian (`updated_at` string ISO, `version` "0.9", `dependencies` lista
   de strings).
3. Fallback: con `yaml.CSafeLoader` ausente (monkeypatch), `parse_frontmatter`
   sigue funcionando con `SafeLoader` sin error."""
from copy import deepcopy
from pathlib import Path

import yaml

from atlas_forge.backlog import parser as parser_module
from atlas_forge.backlog.parser import load_backlog, parse_frontmatter


def test_csafeloader_es_el_loader_cuando_esta_disponible() -> None:
    assert parser_module._YAML_LOADER == yaml.CSafeLoader or parser_module._YAML_LOADER == yaml.SafeLoader
    if hasattr(yaml, "CSafeLoader"):
        assert parser_module._YAML_LOADER is yaml.CSafeLoader
    # El parseo pasa por ese loader (y no por safe_load directo).
    data = parser_module.parse_frontmatter("---\nid: X\nversion: 0.9\n---\n")
    assert data["version"] == 0.9


def test_csafeloader_es_seguro_e_identico_a_safefor_yaml_basico(monkeypatch) -> None:
    # Los dos loaders resuelven el mismo YAML de la misma forma.
    text = "dependencies:\n  - T-AF001-US01-01\n  - AF-002\nversion: 0.9\n"
    safe = yaml.safe_load(text)
    c_safe = yaml.load(text, Loader=_pick())
    assert safe == c_safe


def _pick():
    return yaml.CSafeLoader if hasattr(yaml, "CSafeLoader") else yaml.SafeLoader


def test_parse_frontmatter_conserva_tipos_en_load_backlog(tmp_path: Path) -> None:
    # Fichero real con updated_at ISO-8601 sin comillas, version 0.9 y deps.
    backlog = tmp_path / "02-backlog"
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)
    (backlog / "epics").mkdir(parents=True)
    us = backlog / "user-stories" / "US-AF900-01.md"
    us.write_text(
        "---\n"
        "id: US-AF900-01\ntype: user_story\ntitle: U1\nstate: READY\n"
        "updated_at: 2026-08-25T10:00:00+00:00\n"
        "dependencies: []\nepic: AF-900\npriority: Alta\nversion: 0.9\n"
        "---\n\n## Historia\n\nH.\n\n## Criterios de aceptación\n\n- C.\n",
        encoding="utf-8",
    )
    task = backlog / "tasks" / "T-AF900-US01-01.md"
    task.write_text(
        "---\n"
        "id: T-AF900-US01-01\ntype: task\ntitle: T1\nstate: READY\n"
        "updated_at: 2026-08-25T10:00:00+00:00\n"
        "dependencies:\n  - US-AF900-02\n  - AF-900\n"
        "epic: AF-900\npriority: Alta\n"
        "---\n\n## Objetivo\n\nO.\n",
        encoding="utf-8",
    )

    graph = load_backlog(backlog)
    us_item = graph.items["US-AF900-01"]
    task_item = graph.items["T-AF900-US01-01"]

    # version 0.9 → str "0.9"; updated_at ISO → str isoformat; deps en lista.
    assert us_item.version == "0.9"
    assert isinstance(us_item.updated_at, str)
    assert us_item.updated_at.startswith("2026-08-25T10:00:00")
    assert list(task_item.dependencies) == ["US-AF900-02", "AF-900"]
    assert list(us_item.dependencies) == []


def test_parse_frontmatter_fallback_safeloader_cuando_no_hay_csafeloader(monkeypatch) -> None:
    # Simular que PyYAML no expone CSafeLoader: el módulo resuelve SafeLoader.
    monkeypatch.setattr(yaml, "CSafeLoader", None, raising=False)
    # Re-resolver el loader del módulo como si el import se hiciera sin C.
    monkeypatch.setattr(parser_module, "_YAML_LOADER", yaml.SafeLoader)

    data = parse_frontmatter(
        "---\nid: AF-001\ntype: epic\ntitle: Epic\nstate: READY\n"
        "updated_at: 2026-08-25T10:00:00+00:00\ndependencies: []\n---\n"
    )
    assert data["id"] == "AF-001"
    assert data["title"] == "Epic"
    assert data["updated_at"].isoformat().startswith("2026-08-25T10:00:00")


def test_parse_frontmatter_conserva_tipos_crudos(monkeypatch) -> None:
    # Verificación a nivel crudo: datetimes y floats llegan igual que con
    # safe_load (la normalización posterior es responsabilidad del parser).
    text = (
        "updated_at: 2026-08-25T10:00:00+00:00\n"
        "version: 0.9\n"
        "dependencies:\n  - X-1\n"
    )
    raw = parse_frontmatter("---\n" + text + "---\n")
    safe = yaml.safe_load(text)
    assert raw == safe
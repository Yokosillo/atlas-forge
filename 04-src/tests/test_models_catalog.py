"""Tests de T-AF022-US09-01: esquema y lectura del catalogo de modelos."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from atlas_forge.models_catalog import (
    CATALOG_RELATIVE_PATH,
    MalformedModelCatalogError,
    ModelEntry,
    invalidate_model_catalog_cache,
    load_model_catalog,
    _load_model_catalog_uncached,
)


_SAMPLE_CATALOG = {
    "models": [
        {"id": "opencode-go/deepseek-v4-pro", "name": "DeepSeek V4 Pro", "runtime": "opencode"},
        {"id": "opencode-go/deepseek-v4-flash", "name": "DeepSeek V4 Flash", "runtime": "opencode"},
        {"id": "claude-sonnet-4", "name": "Claude Sonnet 4", "runtime": "claude_code"},
    ],
}


def _write_catalog(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data), encoding="utf-8")


class TestLoadModelCatalog:
    def test_loads_valid_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "models.yml"
            _write_catalog(catalog_path, _SAMPLE_CATALOG)
            invalidate_model_catalog_cache()
            entries = load_model_catalog(catalog_path=catalog_path)
            assert len(entries) == 3
            assert entries[0] == ModelEntry(
                id="opencode-go/deepseek-v4-pro",
                name="DeepSeek V4 Pro",
                runtime="opencode",
            )
            assert entries[1] == ModelEntry(
                id="opencode-go/deepseek-v4-flash",
                name="DeepSeek V4 Flash",
                runtime="opencode",
            )
            assert entries[2] == ModelEntry(
                id="claude-sonnet-4",
                name="Claude Sonnet 4",
                runtime="claude_code",
            )

    def test_file_not_found_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "nonexistent.yml"
            invalidate_model_catalog_cache()
            with pytest.raises(MalformedModelCatalogError, match="no existe"):
                load_model_catalog(catalog_path=catalog_path)

    def test_invalid_yaml_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "models.yml"
            catalog_path.write_text("not: valid: yaml: [", encoding="utf-8")
            invalidate_model_catalog_cache()
            with pytest.raises(MalformedModelCatalogError, match="no es YAML"):
                load_model_catalog(catalog_path=catalog_path)

    def test_empty_catalog_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "models.yml"
            catalog_path.write_text("", encoding="utf-8")
            invalidate_model_catalog_cache()
            with pytest.raises(MalformedModelCatalogError, match="vacio o solo contiene comentarios"):
                load_model_catalog(catalog_path=catalog_path)

    def test_missing_models_key_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "models.yml"
            catalog_path.write_text("other_key: []", encoding="utf-8")
            invalidate_model_catalog_cache()
            with pytest.raises(MalformedModelCatalogError, match="clave raiz 'models'"):
                load_model_catalog(catalog_path=catalog_path)

    def test_models_not_a_list_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "models.yml"
            catalog_path.write_text("models: not_a_list", encoding="utf-8")
            invalidate_model_catalog_cache()
            with pytest.raises(MalformedModelCatalogError, match="debe ser una lista"):
                load_model_catalog(catalog_path=catalog_path)

    def test_empty_models_list_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "models.yml"
            _write_catalog(catalog_path, {"models": []})
            invalidate_model_catalog_cache()
            with pytest.raises(MalformedModelCatalogError, match="no declara ningun modelo"):
                load_model_catalog(catalog_path=catalog_path)

    def test_missing_required_fields_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "models.yml"
            _write_catalog(catalog_path, {
                "models": [{"id": "some-model", "name": "Some Model"}]
            })
            invalidate_model_catalog_cache()
            with pytest.raises(MalformedModelCatalogError, match="runtime"):
                load_model_catalog(catalog_path=catalog_path)

    def test_unsupported_runtime_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "models.yml"
            _write_catalog(catalog_path, {
                "models": [
                    {"id": "gpt-4", "name": "GPT-4", "runtime": "openai"}
                ]
            })
            invalidate_model_catalog_cache()
            with pytest.raises(MalformedModelCatalogError, match="runtime no soportado"):
                load_model_catalog(catalog_path=catalog_path)

    def test_duplicate_id_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "models.yml"
            _write_catalog(catalog_path, {
                "models": [
                    {"id": "dup", "name": "First", "runtime": "opencode"},
                    {"id": "dup", "name": "Second", "runtime": "opencode"},
                ]
            })
            invalidate_model_catalog_cache()
            with pytest.raises(MalformedModelCatalogError, match="duplicado"):
                load_model_catalog(catalog_path=catalog_path)

    def test_entry_not_a_dict_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "models.yml"
            catalog_path.write_text("models:\n  - just_a_string\n", encoding="utf-8")
            invalidate_model_catalog_cache()
            with pytest.raises(MalformedModelCatalogError, match="no es un objeto"):
                load_model_catalog(catalog_path=catalog_path)

    def test_codex_runtime_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "models.yml"
            _write_catalog(catalog_path, {
                "models": [
                    {"id": "gpt-5-codex", "name": "GPT-5 Codex", "runtime": "codex"}
                ]
            })
            invalidate_model_catalog_cache()
            entries = load_model_catalog(catalog_path=catalog_path)
            assert len(entries) == 1
            assert entries[0].runtime == "codex"

    def test_cache_returns_same_entries_without_rereading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "models.yml"
            _write_catalog(catalog_path, _SAMPLE_CATALOG)
            invalidate_model_catalog_cache()
            first = load_model_catalog(catalog_path=catalog_path)
            # Second call should hit cache.
            second = load_model_catalog(catalog_path=catalog_path)
            assert first == second

    def test_cache_invalidates_when_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "models.yml"
            _write_catalog(catalog_path, _SAMPLE_CATALOG)
            invalidate_model_catalog_cache()
            first = load_model_catalog(catalog_path=catalog_path)
            _write_catalog(catalog_path, {
                "models": [
                    {"id": "changed", "name": "Changed", "runtime": "opencode"}
                ]
            })
            second = load_model_catalog(catalog_path=catalog_path)
            assert first != second
            assert len(second) == 1
            assert second[0].id == "changed"

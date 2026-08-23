"""Tests para cache-busting automático (T-AF021-US01-03)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from atlas_forge.api.cache_bust import compute_static_file_hash, get_cache_bust_version


def test_compute_static_file_hash_returns_hash_of_existing_file(tmp_path):
    """compute_static_file_hash devuelve los primeros 8 chars del SHA256."""
    test_file = tmp_path / "test.js"
    test_file.write_text("console.log('test');")

    result = compute_static_file_hash(test_file)

    assert len(result) == 8
    assert all(c in "0123456789abcdef" for c in result)


def test_compute_static_file_hash_returns_missing_for_nonexistent_file(tmp_path):
    """Si el archivo no existe, devuelve 'missing'."""
    nonexistent = tmp_path / "nonexistent.js"

    result = compute_static_file_hash(nonexistent)

    assert result == "missing"


def test_compute_static_file_hash_changes_when_content_changes(tmp_path):
    """El hash cambia cuando el contenido del archivo cambia."""
    test_file = tmp_path / "test.js"
    test_file.write_text("version1")
    hash1 = compute_static_file_hash(test_file)

    test_file.write_text("version2")
    hash2 = compute_static_file_hash(test_file)

    assert hash1 != hash2


def test_get_cache_bust_version_combines_multiple_files(tmp_path):
    """get_cache_bust_version combina hashes de todos los archivos estáticos."""
    # Crear archivos de prueba
    (tmp_path / "app.js").write_text("app content")
    (tmp_path / "style.css").write_text("style content")
    (tmp_path / "backend-client.js").write_text("backend content")
    (tmp_path / "reconnecting-websocket.js").write_text("ws content")

    version = get_cache_bust_version(tmp_path)

    # Debe tener formato YYYYMMDD + 6 chars hex
    assert len(version) == 14  # 8 chars date + 6 chars hash
    assert version[:8].isdigit()
    assert all(c in "0123456789abcdef" for c in version[8:])


def test_get_cache_bust_version_changes_when_any_file_changes(tmp_path):
    """El version cambia si cualquiera de los archivos estáticos cambia."""
    # Crear archivos iniciales
    (tmp_path / "app.js").write_text("app v1")
    (tmp_path / "style.css").write_text("style")
    (tmp_path / "backend-client.js").write_text("backend")
    (tmp_path / "reconnecting-websocket.js").write_text("ws")

    version1 = get_cache_bust_version(tmp_path)

    # Cambiar uno de los archivos
    (tmp_path / "app.js").write_text("app v2")
    version2 = get_cache_bust_version(tmp_path)

    assert version1 != version2


def test_get_cache_bust_version_same_when_files_unchanged(tmp_path):
    """El version es el mismo si los archivos no cambian (entre reinicios)."""
    # Crear archivos
    (tmp_path / "app.js").write_text("app")
    (tmp_path / "style.css").write_text("style")
    (tmp_path / "backend-client.js").write_text("backend")
    (tmp_path / "reconnecting-websocket.js").write_text("ws")

    version1 = get_cache_bust_version(tmp_path)
    version2 = get_cache_bust_version(tmp_path)

    assert version1 == version2

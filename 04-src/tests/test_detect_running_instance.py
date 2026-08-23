"""Tests para la detección de instancias de atlas-forge-api ya sirviendo
(T-AF037-US01-01)."""

import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from atlas_forge.api.main import _detect_running_instance


@pytest.fixture
def caplog_fixture(caplog):
    """Fixture para capturar logs a nivel INFO."""
    caplog.set_level(logging.INFO)
    return caplog


def test_detect_running_instance_returns_true_when_200(caplog_fixture):
    """T-AF037-US01-01, criterio 1: si GET /projects devuelve 200,
    detecta instancia y logguea."""
    with patch("atlas_forge.api.main.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = _detect_running_instance("127.0.0.1", 8000)

        assert result is True
        mock_get.assert_called_once_with(
            "http://127.0.0.1:8000/projects", timeout=1.0
        )
        assert "Detectada otra instancia" in caplog_fixture.text


def test_detect_running_instance_returns_false_when_no_connection(caplog_fixture):
    """T-AF037-US01-01, criterio 2: sin ninguna otra instancia viva,
    retorna False y no logguea nada."""
    with patch("atlas_forge.api.main.requests.get") as mock_get:
        mock_get.side_effect = requests.ConnectionError("Connection refused")

        result = _detect_running_instance("127.0.0.1", 8000)

        assert result is False
        assert "Detectada otra instancia" not in caplog_fixture.text


def test_detect_running_instance_returns_false_when_timeout(caplog_fixture):
    """Sin respuesta en el timeout, no hay instancia viva."""
    with patch("atlas_forge.api.main.requests.get") as mock_get:
        mock_get.side_effect = requests.Timeout("Timed out")

        result = _detect_running_instance("127.0.0.1", 8000)

        assert result is False


def test_detect_running_instance_returns_false_when_non_200_response(caplog_fixture):
    """Si la respuesta no es 200, no se considera instancia Atlas Forge viva."""
    with patch("atlas_forge.api.main.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        result = _detect_running_instance("127.0.0.1", 8000)

        assert result is False
        assert "Detectada otra instancia" not in caplog_fixture.text


def test_detect_running_instance_handles_unexpected_exception(caplog_fixture):
    """Excepciones inesperadas se silencian; no bloquean el arranque."""
    with patch("atlas_forge.api.main.requests.get") as mock_get:
        mock_get.side_effect = ValueError("Unexpected error")

        result = _detect_running_instance("127.0.0.1", 8000)

        assert result is False

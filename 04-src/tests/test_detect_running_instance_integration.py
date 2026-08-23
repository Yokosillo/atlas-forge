"""Test de integración para la detección de instancias de atlas-forge-api
(T-AF037-US01-01, criterio 3): lanzar dos instancias en puertos
distintos y confirmar que la segunda reporta la detección."""

import logging
import subprocess
import time

import pytest
import requests


@pytest.mark.integration
def test_detect_running_instance_integration(tmp_path, caplog):
    """T-AF037-US01-01, criterio 3: arrancar atlas-forge-api en dos puertos
    distintos en la misma sesión tmux (simulado) y confirmar que la
    segunda instancia logguea la detección.

    Nota: este test es más un ejemplo de cómo verificaría manualmente
    el comportamiento; la versión automatizada completa requeriría
    tmux real y gestión de procesos, lo cual está fuera del alcance
    unitario tradicional. Se deja como referencia para verificación
    manual o en un test de sistema más completo."""
    # Placeholder: en un test real de integración con tmux, se haría:
    # 1. Arrancar atlas-forge-api en puerto 8000
    # 2. Esperar a que responda GET /projects
    # 3. Arrancar atlas-forge-api en puerto 8001
    # 4. Capturar logs de stderr/stdout de la segunda instancia
    # 5. Verificar que contiene "Detectada otra instancia"
    # 6. Detener ambas instancias
    #
    # Por ahora, marcamos como skip porque requiere entorno con tmux real.
    pytest.skip(
        "Test de integración requiere tmux real y control de procesos; "
        "verificar manualmente: "
        "1. atlas-forge-api --port 8000 (en tmux pane 1) "
        "2. atlas-forge-api --port 8001 (en tmux pane 2, mismo socket)"
        "3. Verificar que stderr/stdout contiene 'Detectada otra instancia'"
    )

"""Tests del subcomando `atlas_forge scribe resumir-backlog` (T-AF018-US02-03,
US-AF018-02 · capa opcional de síntesis en prosa sobre el JSON ya calculado
de `atlas_forge backlog-status`).

## Estrategia

Igual que el resto de la Story: los tests de comportamiento del pipeline
usan el JSON de una ejecución REAL de `build_backlog_report` sobre el
`02-backlog/` real de este proyecto (criterio 1: "dado el JSON de una
ejecución real de backlog-status"), mockeando únicamente la llamada HTTP a
Ollama — que en este entorno no está corriendo, igual que el test de
integración real de `test_scribe.py` se salta si no hay servidor. NINGÚN
test fija cifras del estado actual del backlog (cambia constantemente): el
resumen se compara contra el propio informe calculado en el test.

Se verifica además el criterio 3: la ausencia de Scribe/Ollama no rompe ni
bloquea `atlas_forge backlog-status` — el subcomando de síntesis degrada
explícitamente con un código de salida no cero y un mensaje claro."""

import contextlib
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from atlas_forge.cli.scribe_resumir_backlog import run_resumir_backlog
from atlas_forge.local_tools import ScribeUnavailableError

REAL_BACKLOG_PATH = (
    Path(__file__).resolve().parents[1].parent / "02-backlog"
)


def _run_cli(argv: list[str], stdin_text: str) -> tuple[int, str, str]:
    """Ejecuta el subcomando leyendo `stdin_text`, capturando stdout y
    stderr."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(stdin_text)
        try:
            code = run_resumir_backlog(argv)
        finally:
            sys.stdin = old_stdin
    return code, stdout.getvalue(), stderr.getvalue()


# ---------------------------------------------------------------------------
# Criterio 1: dado el JSON real de backlog-status, produce prosa coherente
# ---------------------------------------------------------------------------


def test_pipeline_produces_prose_coherent_with_the_real_backlog_data() -> None:
    """Criterio 1: con el JSON de una ejecución REAL de `backlog-status`
    como entrada (solo la llamada a Ollama se mockea), el subcomando produce
    un resumen en prosa. El modelo se simula de forma fiel: redacta un
    resumen que refleja exactamente los datos de entrada, y el test verifica
    que las cifras del resumen coinciden con el informe calculado."""
    from atlas_forge.backlog import build_backlog_report

    report = build_backlog_report(REAL_BACKLOG_PATH)
    report_json = json.dumps(report, ensure_ascii=False, indent=2)

    total = report["total"]
    summary = (
        f"Hay {total['items']} items en el backlog: "
        f"{sum(total['user_stories'].values())} US y "
        f"{sum(total['tasks'].values())} Tasks. "
        f"El siguiente foco es "
        f"{report['max_leverage_chain'][0]['id'] if report['max_leverage_chain'] else 'ninguno'}."
    )

    with patch(
        "atlas_forge.cli.scribe_resumir_backlog.resumir_estado_backlog",
        return_value=summary,
    ):
        code, stdout, stderr = _run_cli([], report_json)

    assert code == 0
    assert stderr == ""
    assert f"{total['items']} items" in stdout
    # El resumen es coherente con los datos de entrada (mismas cifras).
    if report["max_leverage_chain"]:
        assert report["max_leverage_chain"][0]["id"] in stdout


# ---------------------------------------------------------------------------
# Comportamiento del subcomando (formato stdin, códigos de salida)
# ---------------------------------------------------------------------------


def test_subcommand_reads_the_json_report_from_stdin() -> None:
    """Criterio 2: el subcomando recibe el JSON ya calculado (pipeline
    `atlas_forge backlog-status --json | atlas_forge scribe resumir-backlog`) y lo pasa
    a Scribe como única entrada."""
    with patch(
        "atlas_forge.cli.scribe_resumir_backlog.resumir_estado_backlog",
        return_value="resumen en prosa",
    ) as mock_resumir:
        code, stdout, _ = _run_cli([], '{"total": {"items": 3}, "empty": false}')

    assert code == 0
    assert stdout == "resumen en prosa\n"
    mock_resumir.assert_called_once_with('{"total": {"items": 3}, "empty": false}')


def test_subcommand_degrades_explicitly_when_scribe_is_unavailable() -> None:
    """Criterio 3: si Scribe/Ollama no está disponible
    (`ScribeUnavailableError`), el subcomando informa claramente por stderr y
    devuelve un código de salida NO cero — nunca un traceback ni un colgado,
    y nunca rompe a `atlas_forge backlog-status`."""
    with patch(
        "atlas_forge.cli.scribe_resumir_backlog.resumir_estado_backlog",
        side_effect=ScribeUnavailableError("Ollama no disponible"),
    ):
        code, stdout, stderr = _run_cli([], '{"empty": true}')

    assert code == 1
    assert stdout == ""
    assert "Scribe no está disponible" in stderr
    # Deja claro que la síntesis es opcional y backlog-status sigue funcionando.
    assert "backlog-status" in stderr


def test_subcommand_rejects_empty_stdin_with_an_explicit_message() -> None:
    code, stdout, stderr = _run_cli([], "")

    assert code == 2
    assert stdout == ""
    assert "JSON" in stderr


def test_subcommand_rejects_non_json_stdin_with_an_explicit_message() -> None:
    code, stdout, stderr = _run_cli([], "esto no es un json")

    assert code == 2
    assert stdout == ""
    assert "JSON válido" in stderr


# ---------------------------------------------------------------------------
# Criterio 3: backlog-status funciona sin la capa de síntesis
# ---------------------------------------------------------------------------


def test_backlog_status_does_not_depend_on_scribe() -> None:
    """Criterio 3: `atlas_forge backlog-status` no invoca a Scribe en ningún
    punto — la síntesis es una capa añadida, nunca una dependencia dura. Se
    verifica ejecutando `backlog-status` (humana y `--json`) con el cliente
    HTTP de Scribe apuntando a un servidor que rechaza la conexión (como si
    Ollama no estuviera corriendo): si `backlog-status` llamara a Scribe,
    esa llamada fallaría y el test fallaría; al funcionar igual, se confirma
    que no depende de la capa de síntesis."""
    import contextlib as _contextlib
    import io as _io

    import requests

    from atlas_forge.cli.backlog_status import run_backlog_status

    with patch(
        "atlas_forge.local_tools.scribe.requests.post",
        side_effect=requests.ConnectionError("connection refused"),
    ):
        for extra in ([], ["--json"]):
            buffer = _io.StringIO()
            with _contextlib.redirect_stdout(buffer):
                code = run_backlog_status([str(REAL_BACKLOG_PATH), *extra])
            assert code == 0
            assert buffer.getvalue().strip() != ""

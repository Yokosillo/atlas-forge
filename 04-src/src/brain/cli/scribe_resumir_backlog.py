"""Subcomando `brain scribe resumir-backlog` (T-FB018-US02-03, US-FB018-02 ·
"Estado del backlog: conteo, dependencias y siguiente foco, sin gastar tokens
de agente cognitivo").

Capa opcional de síntesis en prosa sobre el cálculo ya determinista de
T-FB018-US02-02: lee por stdin el JSON que produce
`brain backlog-status --json`, lo pasa a `resumir_estado_backlog` (Scribe,
catálogo cerrado de operaciones — plantilla de prompt fija, no prompt libre)
y escribe el resumen en prosa por stdout.

Scribe NO vuelve a leer ni a parsear los ficheros de `02-backlog/`: recibe
el JSON ya calculado como única entrada (criterio 2 de la Task).

Degradación explícita (criterio 3 de la Task): si Scribe/Ollama no está
disponible (`ScribeUnavailableError`), el comando lo informa claramente por
stderr y devuelve un código de salida no cero, pero NUNCA rompe ni bloquea a
`brain backlog-status` — la síntesis es una capa añadida, no una dependencia
dura del resto de la Story. El contrato de quien invoca Scribe (capturar
`ScribeUnavailableError` y continuar sin el resultado) se cumple aquí."""

from __future__ import annotations

import argparse
import json
import sys

from brain.local_tools import ScribeUnavailableError, resumir_estado_backlog


def run_resumir_backlog(argv: list[str] | None = None) -> int:
    """Lee el JSON del informe del backlog por stdin, lo sintetiza en prosa
    vía Scribe y lo imprime por stdout.

    Devuelve 0 en éxito; 1 si Scribe/Ollama no está disponible (degradación
    explícita, mensaje claro por stderr); 2 si stdin no trae un JSON válido
    del informe."""
    parser = argparse.ArgumentParser(
        prog="brain scribe resumir-backlog",
        description="Redacta un resumen en prosa del estado del backlog "
        "a partir del JSON de `brain backlog-status --json`.",
    )
    args = parser.parse_args(argv)

    raw = sys.stdin.read().strip()
    if not raw:
        print(
            "No se recibió ningún JSON por stdin. Úsalo en un pipeline: "
            "'brain backlog-status --json <02-backlog/> | "
            "brain scribe resumir-backlog'.",
            file=sys.stderr,
        )
        return 2
    try:
        json.loads(raw)
    except json.JSONDecodeError as error:
        print(f"El stdin no es un JSON válido: {error}", file=sys.stderr)
        return 2

    try:
        resumen = resumir_estado_backlog(raw)
    except ScribeUnavailableError as error:
        print(
            f"Scribe no está disponible — la síntesis en prosa es opcional, "
            f"el estado del backlog sigue disponible con 'brain "
            f"backlog-status' sin la capa de síntesis. Motivo: {error}",
            file=sys.stderr,
        )
        return 1

    print(resumen)
    return 0

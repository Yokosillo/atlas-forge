"""Lógica PURA de detección de inactividad (cuelgue) de un agente
(T-AF023-US01-01) — sin dependencias de HTTP, persistencia ni tmux, para
que sea testeable de forma determinista.

Un agente se considera "colgado" cuando su timestamp de última actividad
lleva varias lecturas seguidas SIN cambiar superando un umbral configurable.
Se distingue de "procesando": un agente con actividad espaciada pero REAL
(la última actividad avanza entre lecturas, aunque sea lenta) nunca se
marca colgado — evita falsos positivos.

## Umbral configurable

El umbral no está hardcodeado: se pasa como parámetro. Valor por defecto
`DEFAULT_INACTIVITY_THRESHOLD_SECONDS = 120.0`, documentado (sesión de
origen: ~120s con varias lecturas consecutivas sin cambio).
"""

from __future__ import annotations

import time

# Valor por defecto del umbral de inactividad (segundos), documentado en el
# código (T-AF023-US01-01): generaliza la sesión de origen (CRITICO.md) que
# usaba ~120s con varias lecturas consecutivas sin cambio para declarar un
# cuelgue. Configurable en cada llamada vía `threshold_seconds`.
DEFAULT_INACTIVITY_THRESHOLD_SECONDS = 120.0

# Veredictos posibles (vocabulario canónico de la Task).
VERDICT_ALIVE = "vivo"
VERDICT_HUNG = "colgado"
VERDICT_PROCESSING = "procesando"


def detect_agent_activity(
    last_activity: list[float],
    threshold_seconds: float = DEFAULT_INACTIVITY_THRESHOLD_SECONDS,
    consecutive_reads: int = 3,
    now: float | None = None,
) -> str:
    """Decide el estado de actividad de un agente a partir de la secuencia
    `last_activity` de timestamps (epoch segundos) de su última actividad,
    observados en lecturas consecutivas (cronológicos; el último elemento es
    la lectura más reciente).

    Regla (determinista, sin infraestructura externa):

    - `vivo`: la última actividad es reciente — `now - last_activity[-1]
      <= threshold_seconds`. El agente hizo algo recientemente.
    - `colgado`: la última actividad es antigua (`> threshold_seconds`) y NO
      ha cambiado en `consecutive_reads` lecturas seguidas — el agente lleva
      un cuelgue real sin producir actividad.
    - `procesando`: la última actividad es antigua pero no se dan aún las
      condiciones de `colgado` (p. ej. la actividad SÍ avanzó en la última
      lectura — trabajo espaciado pero real; o aún no hay suficientes
      lecturas consecutivas sin cambio) — nunca se marca `colgado` con
      actividad real.

    Devuelve una de las constantes `VERDICT_*`. `now` es inyectable para
    tests deterministas (por defecto `time.time()`)."""
    if now is None:
        now = time.time()

    if not last_activity:
        # Sin datos todavía no se puede declarar un cuelgue.
        return VERDICT_PROCESSING

    latest = last_activity[-1]
    if now - latest <= threshold_seconds:
        return VERDICT_ALIVE

    # Última actividad antigua: distinguir cuelgue de trabajo espaciado.
    # Se exige `consecutive_reads` lecturas seguidas con el MISMO timestamp
    # para declarar colgado — con menos lecturas, o si el timestamp avanzó
    # en la última lectura, se reporta `procesando` (evita falsos positivos).
    if (
        len(last_activity) >= consecutive_reads
        and all(ts == latest for ts in last_activity[-consecutive_reads:])
    ):
        return VERDICT_HUNG

    return VERDICT_PROCESSING

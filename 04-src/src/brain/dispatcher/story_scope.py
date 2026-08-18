"""Detección de si una User Story "toca `10-web/`" (T-FB022-US15-04,
US-FB022-15).

## Mecanismo elegido: heurística sobre los informes de cierre ya
## existentes, no un campo nuevo de frontmatter

La Task propone tres opciones (ver `T-FB022-US15-04-disparo-automatico-tester-al-cerrar-us.md`,
"Descripción" punto 2) y recomienda como punto de partida un campo nuevo
explícito en el frontmatter (`touches_web: true`) declarado por el
Arquitecto al aterrizar el backlog, salvo que las otras dos resulten
viables sin complejidad añadida significativa — y ese es exactamente el
caso aquí:

- **`git diff` de los commits asociados a los Jobs de la US**: descartada.
  No existe ningún mecanismo que asocie de forma fiable un commit de git
  con un Job/Task concretos (los commits de esta sesión los hacen
  sesiones de Developer en paralelo sobre el mismo árbol compartido, sin
  ninguna marca que los ligue a un `job_id`) — construir esa asociación
  sería la complejidad añadida significativa que la propia Task pide
  evitar.
- **Campo nuevo en frontmatter (`touches_web`)**: descartada para esta
  Task. Requeriría ampliar el parser del backlog
  (`brain.backlog.parser`), el validador (`validate_backlog_content_v2`)
  y el flujo de creación/aterrizaje de User Stories del Arquitecto — y
  además exige que alguien lo declare por adelantado, con riesgo de
  quedar desactualizado si el alcance real cambia durante el desarrollo
  (un Developer puede acabar tocando `10-web/` aunque la Story, leída de
  antemano, pareciera puramente de backend).
- **Heurística sobre el informe de cierre** (elegida): cada informe de
  cierre en `07-informes/<US-id>/*.md` ya documenta, en prosa
  estructurada, qué ficheros se tocaron (sección "Cambios", patrón
  `**\`10-web/...\`**` — ver cualquier informe de esta misma sesión,
  p. ej. `07-informes/US-FB036-01/US-FB036-01.md`). Es información que
  YA EXISTE, generada como efecto colateral del propio protocolo de
  cierre (`00-gobierno/DEVELOPER.md`), no una obligación nueva que
  imponer a nadie — y es la fuente más fiel al trabajo REAL hecho
  (registrado después de implementar, no antes), no una declaración de
  intención por adelantado. Coste de implementación: una búsqueda de
  substring sobre texto que `_collect_story_reports`
  (`job_plan_dispatch.py`) ya lee para el propio veredicto del
  Arquitecto — ningún I/O adicional más allá de reutilizar esa lectura.

Limitación aceptada: si ningún informe de cierre de la US menciona
`10-web/` en absoluto (p. ej. porque el Developer olvidó listar los
ficheros afectados, contra el protocolo), esta heurística no detecta el
alcance web — mismo tipo de limitación que cualquier heurística basada en
texto libre. Se acepta porque el mecanismo determinista alternativo
(campo de frontmatter) tiene el mismo problema de fondo (depende de que
alguien lo declare correctamente) con mayor coste de implementación."""

from __future__ import annotations

import re
from pathlib import Path

_WEB_PATH_PATTERN = re.compile(r"10-web/")


def story_touches_web(reports: list[str]) -> bool:
    """`True` si algún informe de cierre en `reports` menciona una ruta
    bajo `10-web/` — heurística determinista, ver docstring del módulo.

    `reports` es la lista de contenidos ya leídos (mismo formato que
    devuelve `_collect_story_reports`, `job_plan_dispatch.py`) — esta
    función no hace I/O propio, para poder reutilizar exactamente la
    misma lectura ya hecha para el veredicto del Arquitecto sin leer los
    ficheros dos veces."""
    return any(_WEB_PATH_PATTERN.search(report) for report in reports)


def default_reports_root() -> Path:
    return Path(__file__).resolve().parents[4] / "07-informes"

"""Modelos del parser determinista de `02-backlog/` (T-AF018-US02-01,
US-AF018-02 · "Estado del backlog: conteo, dependencias y siguiente foco,
sin gastar tokens de agente cognitivo").

`BacklogItem` es un US/Task ya parseado de su fichero `.md` (identificador,
tipo, epic, estado y lista de identificadores de dependencia). `BacklogGraph`
es el resultado de cargar un `02-backlog/` completo: nodo por item, arista
por dependencia declarada, más la lista de errores de parseo por fichero
(un fichero mal formado no aborta el cálculo del resto — se reporta aparte,
ver T-AF018-US02-01). `BacklogParseError` describe exactamente qué fichero
falló y por qué."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

ITEM_KIND_TASK = "T"
ITEM_KIND_USER_STORY = "US"
ITEM_KIND_EPIC = "E"

# Estado canónico (AF-040): el vocabulario completo y las transiciones
# viven en `atlas_forge/core/state_machines.py`; estas constantes solo evitan
# magic strings en los consumidores más básicos.
STATE_DONE = "DONE"
STATE_READY = "READY"


@dataclass(frozen=True)
class BacklogItem:
    """Un US/Task del backlog ya parseado de su fichero `.md`.

    `id` es el identificador estable (p. ej. `T-AF018-US02-01` o
    `US-AF018-02`); `kind` es `"T"` (Task) o `"US"` (User Story); `epic` es
    el nombre de la Epic declarado en la línea `**Epic:**` (o `None` si el
    fichero no lo declara, que ocurre en algunos ficheros del propio
    backlog); `state` es el valor literal de la sección `## Estado`;
    `dependencies` son los identificadores extraídos de la sección
    `## Dependencias` (patrones `**T-FBxxx-...**`/`**US-FBxxx-...**` en
    negrita, convención ya usada en todo `02-backlog/`); `priority` es el
    valor literal de la sección `## Prioridad` (p. ej. `Alta.`, `Media.`,
    `Baja — ...`) o `None` si el fichero no la declara — es un campo
    OPcional, no un error de parseo (un backlog recién creado puede tener
    items sin prioridad aún asignada); `user_story` es el valor del campo
    `user_story:` del frontmatter YAML de una Task (la US a la que
    pertenece, p. ej. `US-AF020-01`) o `None` para Epics/User Stories, que
    no lo declaran — es la relación real Task→US (T-AF008-US04-05:
    `dependencies` NUNCA se usó para esto, pese a que `build_item_detail`
    lo asumía); `path` es la ruta del fichero del que se leyó (para
    reportar errores de parseo de ese fichero concreto)."""

    id: str
    kind: str
    epic: str | None
    state: str
    dependencies: tuple[str, ...]
    priority: str | None
    difficulty: str | None
    fase: str | None
    path: Path
    user_story: str | None = None
    updated_at: str | None = None
    # T-AF036-US19-01: la Epic se versiona (campo `version:` del frontmatter)
    # en lugar de tener `fase` (que es de la User Story). Solo se puebla para
    # Epics; para US/Task es `None`.
    version: str | None = None
    # T-AF036-US19-01: título del item, leído del campo `title:` del
    # frontmatter — `None` si el fichero no lo declara.
    title: str | None = None


@dataclass(frozen=True)
class BacklogParseError(Exception):
    """Un fichero que no sigue la convención del backlog (`## Estado` o
    `## Dependencias` ausente o mal formado). Se reporta por fichero
    concreto (identificador + motivo) sin abortar el cálculo del resto
    (criterio de aceptación 6 de US-AF018-02)."""

    path: Path
    item_id: str | None
    reason: str

    def __str__(self) -> str:
        file_label = self.path.name
        if self.item_id is not None:
            file_label = f"{self.item_id} ({file_label})"
        return f"{file_label}: {self.reason}"


@dataclass(frozen=True)
class BacklogGraph:
    """Resultado de `load_backlog`: el grafo de dependencias de todo el
    `02-backlog/`.

    `items` es un dict `id -> BacklogItem` (nodo por US/Task real del
    backlog); `dependencies_of` es la lista de dependencias declaradas por
    cada item (arista del grafo); `errors` es la lista de ficheros que no
    siguieron la convención y fueron reportados sin interrumpir el resto.
    El dict `items` es de solo lectura (se construye una vez y nunca se
    muta) — se expone como `Mapping` para no filtrar un estado mutable."""

    items: Mapping[str, BacklogItem]
    errors: tuple[BacklogParseError, ...] = field(default_factory=tuple)

    @property
    def dependencies_of(self) -> Mapping[str, tuple[str, ...]]:
        return {item_id: item.dependencies for item_id, item in self.items.items()}

"""Modelos del parser determinista de `02-backlog/` (T-FB018-US02-01,
US-FB018-02 · "Estado del backlog: conteo, dependencias y siguiente foco,
sin gastar tokens de agente cognitivo").

`BacklogItem` es un US/Task ya parseado de su fichero `.md` (identificador,
tipo, epic, estado y lista de identificadores de dependencia). `BacklogGraph`
es el resultado de cargar un `02-backlog/` completo: nodo por item, arista
por dependencia declarada, más la lista de errores de parseo por fichero
(un fichero mal formado no aborta el cálculo del resto — se reporta aparte,
ver T-FB018-US02-01). `BacklogParseError` describe exactamente qué fichero
falló y por qué."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

ITEM_KIND_TASK = "T"
ITEM_KIND_USER_STORY = "US"

STATE_DONE = "DONE"
STATE_TODO = "TODO"


@dataclass(frozen=True)
class BacklogItem:
    """Un US/Task del backlog ya parseado de su fichero `.md`.

    `id` es el identificador estable (p. ej. `T-FB018-US02-01` o
    `US-FB018-02`); `kind` es `"T"` (Task) o `"US"` (User Story); `epic` es
    el nombre de la Epic declarado en la línea `**Epic:**` (o `None` si el
    fichero no lo declara, que ocurre en algunos ficheros del propio
    backlog); `state` es el valor literal de la sección `## Estado`;
    `dependencies` son los identificadores extraídos de la sección
    `## Dependencias` (patrones `**T-FBxxx-...**`/`**US-FBxxx-...**` en
    negrita, convención ya usada en todo `02-backlog/`); `priority` es el
    valor literal de la sección `## Prioridad` (p. ej. `Alta.`, `Media.`,
    `Baja — ...`) o `None` si el fichero no la declara — es un campo
    OPcional, no un error de parseo (un backlog recién creado puede tener
    items sin prioridad aún asignada); `path` es la ruta del fichero del que
    se leyó (para reportar errores de parseo de ese fichero concreto)."""

    id: str
    kind: str
    epic: str | None
    state: str
    dependencies: tuple[str, ...]
    priority: str | None
    path: Path


@dataclass(frozen=True)
class BacklogParseError(Exception):
    """Un fichero que no sigue la convención del backlog (`## Estado` o
    `## Dependencias` ausente o mal formado). Se reporta por fichero
    concreto (identificador + motivo) sin abortar el cálculo del resto
    (criterio de aceptación 6 de US-FB018-02)."""

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

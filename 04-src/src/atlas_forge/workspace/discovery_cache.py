"""Caché TTL en memoria para descubrimientos de filesystem
(T-AF001-US01-06).

`discover_projects` (`workspace/discovery.py`) y `discover_project_scripts`
(`workspace/project_scripts.py`) recorren el filesystem completo (`os.walk`
/ lectura del manifiesto) en cada llamada, y la API los invoca de nuevo en
cada request (`api/routes.py`) — hallazgo de auditoría externa
(2026-08-01). Ambas hacen I/O sin memoización.

Este módulo aporta una caché genérica en memoria con TTL corto (por defecto
5s, verificado que `os.walk` en un workspace real grande tarda ~90ms — un
TTL de 5s absorbe ráfagas de requests sin servir datos obsoletos por más de
unos segundos si el desarrollador añade un script nuevo), suficiente para:

- no repetir el recorrido del filesystem en llamadas seguidas dentro del TTL
  (varias pantallas de la app consultando en poco tiempo), y
- no servir datos obsoletos por más del TTL.

## Decisiones

- **No se cachean errores**: si la función de cómputo lanza (p. ej. un
  manifiesto mal formado o un fallo de `os.walk`), la excepción se propaga y
  NADA se guarda — el siguiente intento reintenta de verdad, no sirve el
  fallo cacheado (criterio de aceptación explícito).
- **Validación por mtime del recurso**: además del TTL, cada acceso a una
  entrada cacheada re-valida un `stat` barato (O(1), nunca un recorrido) del
  recurso observado (el directorio raíz en `discover_projects`; el fichero
  de manifiesto en `discover_project_scripts`). Si el mtime cambió, la
  entrada se descarta y se recomputa al instante — así, un repo creado o
  borrado, o un script añadido al manifiesto, se refleja sin esperar al TTL,
  y aun así no se repite el `os.walk` completo para lecturas sin cambios.
- **Invalidación explícita al cambiar de proyecto activo**: `routes.py`
  llama a `invalidate_discovery_cache()`/`invalidate_project_scripts_cache()`
  en `POST /project`, para que el catálogo del nuevo proyecto se refleje sin
  esperar al TTL anterior (y para un ida-y-vuelta A→B→A dentro del TTL no
  sirva la caché vieja de A).
- **Clave por recurso**: `discover_projects` cachea por `root`;
  `discover_project_scripts` por `project_path` — cada proyecto mantiene su
  propia entrada.
- **Thread-safety**: `threading.Lock` para leer/escribir la tabla; el cómputo
  se hace FUERA del lock (el I/O de `os.walk` es lento y no debe bloquear
  lecturas de otros hilos de la API).
"""

import threading
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")

DEFAULT_DISCOVERY_TTL_SECONDS = 5.0


class TTLCache:
    def __init__(self, ttl_seconds: float = DEFAULT_DISCOVERY_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, Any, Callable[[], bool]]] = {}

    def get_or_compute(
        self,
        key: str,
        compute: Callable[[], T],
        *,
        cache_if: Callable[[T], bool] | None = None,
        validate: Callable[[], bool] | None = None,
    ) -> T:
        """Devuelve la entrada cacheada para `key` si no ha expirado y
        `validate()` (si se da) sigue siendo verdadero; si no, llama a
        `compute()`, guarda el resultado con la marca de tiempo actual y lo
        devuelve.

        Si `compute()` lanza, la excepción se propaga sin guardar nada (no se
        cachean errores). Si `cache_if` se da, el resultado solo se guarda
        cuando `cache_if(value)` es verdadero (p. ej. `discover_projects` no
        cachea un escaneo vacío: es barato recomputarlo y representa un
        estado transitorio — un repo puede aparecer en cualquier momento, y
        cachearlo ocultaría el cambio hasta el TTL)."""
        now = time.monotonic()
        with self._lock:
            cached = self._entries.get(key)
            if (
                cached is not None
                and now - cached[0] < self._ttl_seconds
                and cached[2]()
            ):
                return cached[1]

        value = compute()

        if cache_if is not None and not cache_if(value):
            return value

        def _default_validate() -> bool:
            return True

        with self._lock:
            self._entries[key] = (now, value, validate or _default_validate)
        return value

    def invalidate(self) -> None:
        with self._lock:
            self._entries.clear()

    def _debug_size(self) -> int:
        return len(self._entries)

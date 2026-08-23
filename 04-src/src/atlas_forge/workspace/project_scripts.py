"""Catalogación de scripts particulares del proyecto activo (T-AF001-US03-01):
un proyecto declara sus propios scripts en un manifiesto YAML en su raíz, y
Atlas Forge los descubre sin necesitar que el desarrollador teclee el
comando cada vez.

## Formato del manifiesto: `.atlas-forge/scripts.yml`, YAML

Se descarta JSON (ya usado en `atlas_forge.storage.local_store` para persistencia
INTERNA de Atlas Forge, p. ej. `active_project.json`) porque ese caso es
distinto al de aquí: este manifiesto lo escribe y mantiene el desarrollador
a mano, en su propio repositorio, no lo genera Atlas Forge — YAML admite
comentarios y no exige comillas en cada valor, ambos relevantes para un
fichero de configuración editado por humanos (mismo formato ya estándar en
la industria para manifiestos declarativos similares: `docker-compose.yml`,
`.github/workflows/*.yml`).

Se descarta `tomllib` (built-in desde Python 3.11, sin dependencia externa)
para no romper la compatibilidad ya declarada del proyecto
(`requires-python = ">=3.10"`, `pyproject.toml`) — introducir `PyYAML` como
dependencia nueva es preferible a bajar la compatibilidad mínima solo para
evitar una dependencia.

Ubicación (`.atlas-forge/scripts.yml`, no en la raíz directamente): mismo
directorio oculto que usarán futuros ficheros de configuración específicos
de Atlas Forge por proyecto (p. ej. AF-013 Configuration Management,
todavía en `BACKLOG HOLD`), evitando ensuciar la raíz del repositorio con
un fichero de nombre genérico (`scripts.yml` a secas podría colisionar con
convenciones propias de otras herramientas del proyecto).

## Forma del manifiesto

```yaml
scripts:
  - id: lint
    name: "Lint del proyecto"
    command: "ruff check ."
    description: "Ejecuta el linter sobre todo el código."
  - id: tests
    name: "Suite de tests"
    command: "pytest"
```

`id` y `command` son obligatorios por script; `name` es obligatorio (nombre
visible en la interfaz); `description` es opcional (por defecto cadena
vacía, mismo criterio que la Task pide: "opcionalmente descripción").

## Ejecución (T-AF001-US03-02)

`run_project_script` localiza un `ScriptEntry` catalogado por `id` y lo
ejecuta como subproceso — no requiere tmux (a diferencia de un `Runtime`
interactivo de AF-004): es una ejecución puntual que termina sola, mismo
criterio ya aplicado a Scribe frente a Developer/Critic (`ver
atlas_forge.local_tools.scribe`, aunque Scribe usa HTTP en vez de subprocess —
el paralelismo es "puntual y sin estado retenido", no el mecanismo de
transporte). `subprocess.run(..., shell=True)`: `ScriptEntry.command` es
un string de shell completo (puede incluir pipes, redirecciones,
variables — lo que el desarrollador haya declarado, tal cual lo
ejecutaría él mismo en su terminal), no una lista de argumentos fija como
`resolve_tailscale_host` (`atlas_forge/api/host.py`, que sí controla cada
argumento por separado porque el comando es interno y fijo, no declarado
por un tercero)."""

import subprocess
from pathlib import Path
from typing import Any

import yaml

from atlas_forge.models import ScriptEntry, ScriptRunResult
from atlas_forge.workspace.discovery_cache import TTLCache

MANIFEST_RELATIVE_PATH = Path(".atlas-forge") / "scripts.yml"

# PARCHE PROVISIONAL (bug: suite de tests excede el timeout, 2026-08-19): subido de 30.0 a 600.0
# para que el script genérico 'run_tests' (que ejecuta la suite completa de
# Atlas Forge, 1237 tests de integración que tardan varios minutos) no
# agote el timeout y haga fallar al Tester. NO es la solución de fondo: la
# suite además adolece de contaminación de estado entre tests que la hace
# colgarse; la task de reestructuración está pendiente de crear (ver
# resumen para el Arquitecto). Este valor solo da margen mientras tanto.
DEFAULT_SCRIPT_TIMEOUT_SECONDS = 600.0

# Caché TTL (T-AF001-US01-06): `discover_project_scripts` lee el manifiesto
# del disco en cada llamada, y la API lo invoca de nuevo en cada `GET
# /scripts`. La caché por `project_path` absorbe ráfagas de requests. Un TTL
# corto (5s) garantiza que un script añadido por el desarrollador aparezca
# en el catálogo al expirar el TTL sin reiniciar el backend. Los errores
# (`MalformedScriptManifestError`, YAML roto) NO se cachean — la excepción se
# propaga y el siguiente intento vuelve a leer el fichero.
_SCRIPTS_CACHE = TTLCache()


def invalidate_project_scripts_cache() -> None:
    """Vacía la caché de scripts particulares — se llama al cambiar de
    proyecto activo (`POST /project`, T-AF001-US01-06) para que el catálogo
    del nuevo proyecto se refleje sin esperar al TTL anterior."""
    _SCRIPTS_CACHE.invalidate()


class MalformedScriptManifestError(ValueError):
    """El manifiesto de scripts existe pero no se puede interpretar: YAML
    inválido, estructura inesperada (no es una lista bajo `scripts`), o
    falta algún campo obligatorio (`id`, `name`, `command`) en alguna
    entrada — nunca una excepción no controlada, siempre este error
    explícito con un mensaje legible sobre qué está mal."""


def _validate_script_entry(raw_entry: Any, index: int) -> ScriptEntry:
    if not isinstance(raw_entry, dict):
        raise MalformedScriptManifestError(
            f"El script en la posición {index} del manifiesto no es un "
            f"objeto con campos (id/name/command) — se encontró: "
            f"{raw_entry!r}."
        )

    missing_fields = [
        field for field in ("id", "name", "command") if not raw_entry.get(field)
    ]
    if missing_fields:
        raise MalformedScriptManifestError(
            f"El script en la posición {index} del manifiesto no tiene "
            f"los campos obligatorios: {', '.join(missing_fields)}."
        )

    return ScriptEntry(
        id=str(raw_entry["id"]),
        name=str(raw_entry["name"]),
        command=str(raw_entry["command"]),
        description=str(raw_entry.get("description", "")),
    )


def discover_project_scripts(project_path: str) -> list[ScriptEntry]:
    """Lee el manifiesto de scripts particulares de `project_path` y
    devuelve la lista de scripts declarados.

    - Manifiesto ausente: lista vacía, sin ningún error (criterio de
      aceptación explícito) — no todos los proyectos declaran scripts
      propios, y eso es un estado válido, no una carencia.
    - Manifiesto presente pero mal formado (YAML inválido, no es una
      lista bajo `scripts`, o falta algún campo obligatorio en alguna
      entrada): `MalformedScriptManifestError` explícita — nunca una
      excepción de parseo no controlada (`yaml.YAMLError`) propagada tal
      cual, que rompería cualquier interfaz que llame a esta función sin
      capturar ese tipo concreto.

    Cacheada por TTL (T-AF001-US01-06) y validada contra el mtime del
    manifiesto: aunque la entrada siga dentro del TTL, si el fichero cambió
    (script añadido/quitado por el desarrollador), se recomputa al instante
    sin esperar al TTL — un `stat` es O(1), nunca una relectura del YAML
    para lecturas sin cambios. Los errores de parseo NO se cachean (la
    excepción se propaga).
    """
    manifest_path = Path(project_path) / MANIFEST_RELATIVE_PATH
    baseline: list[tuple[int, int] | None] = [None]

    def compute() -> list[ScriptEntry]:
        baseline[0] = _manifest_fingerprint(manifest_path)
        return _discover_project_scripts_uncached(project_path)

    def validate() -> bool:
        return _manifest_fingerprint(manifest_path) == baseline[0]

    return _SCRIPTS_CACHE.get_or_compute(
        project_path, compute, validate=validate
    )


def _manifest_fingerprint(path: Path) -> tuple[int, int] | None:
    """Marca del manifiesto para validar la caché: `(mtime_ns, size)` o
    `None` si el fichero no existe. Incluir el tamaño hace el validador
    fiable incluso si una escritura cae en la misma marca temporal."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _discover_project_scripts_uncached(project_path: str) -> list[ScriptEntry]:
    """Lógica original de `discover_project_scripts` — extraída a esta
    función privada para que la pública la envuelva con la caché TTL sin
    tocar ningún comportamiento (lectura real del manifiesto YAML del disco,
    propagación de `MalformedScriptManifestError` para manifiestos rotos)."""
    manifest_path = Path(project_path) / MANIFEST_RELATIVE_PATH
    if not manifest_path.exists():
        return []

    try:
        raw_content = manifest_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw_content)
    except yaml.YAMLError as error:
        raise MalformedScriptManifestError(
            f"El manifiesto de scripts '{manifest_path}' no es YAML "
            f"válido: {error}."
        ) from error

    if parsed is None:
        # Fichero vacío o solo comentarios: manifiesto presente pero sin
        # contenido real — se trata igual que "sin scripts declarados",
        # no como un error (no hay ningún dato mal formado, simplemente no
        # hay ninguno).
        return []

    if not isinstance(parsed, dict) or "scripts" not in parsed:
        raise MalformedScriptManifestError(
            f"El manifiesto de scripts '{manifest_path}' debe tener una "
            f"clave raíz 'scripts' con la lista de scripts declarados."
        )

    raw_scripts = parsed["scripts"]
    if not isinstance(raw_scripts, list):
        raise MalformedScriptManifestError(
            f"'scripts' en '{manifest_path}' debe ser una lista de "
            f"scripts, no {type(raw_scripts).__name__}."
        )

    return [
        _validate_script_entry(raw_entry, index)
        for index, raw_entry in enumerate(raw_scripts)
    ]


def run_subprocess(
    command: str | list[str],
    cwd: str,
    timeout_seconds: float,
    *,
    shell: bool = False,
    action_description: str,
) -> ScriptRunResult:
    """Ejecuta `command` como subproceso real con `cwd` como directorio de
    trabajo y traduce el resultado a un [ScriptRunResult] — el mecanismo de
    ejecución de T-AF001-US03-02, extraído para que lo compartan
    `run_project_script` (scripts particulares, comando de shell declarado
    en un manifiesto, `shell=True`) y `run_generic_script` (T-AF018-US01-01,
    comandos git como lista de argumentos sin shell, `shell=False`).

    Nunca lanza una excepción no controlada: un timeout agotado o un fallo
    al arrancar el subproceso (p. ej. el shell no disponible) se traduce a
    un `ScriptRunResult` con `success=False`, `exit_code=None` y
    `error_message` explicando el motivo. Un comando que sí se ejecuta pero
    termina con código de salida distinto de cero es `success=False` con su
    `exit_code` real y su `stdout`/`stderr` disponibles para diagnóstico
    (distinto del caso anterior: aquí el comando SÍ corrió, solo que falló).
    """
    try:
        completed = subprocess.run(
            command,
            shell=shell,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        return ScriptRunResult(
            success=False,
            exit_code=None,
            stdout=error.stdout or "",
            stderr=error.stderr or "",
            error_message=(
                f"{action_description.capitalize()} no terminó en "
                f"{timeout_seconds}s (timeout agotado)."
            ),
        )
    except OSError as error:
        # El propio subproceso no pudo arrancar (p. ej. el shell del
        # sistema no está disponible) — distinto de "el comando arrancó y
        # falló" (ese caso ya tiene su propio exit_code real, más abajo).
        return ScriptRunResult(
            success=False,
            exit_code=None,
            stdout="",
            stderr="",
            error_message=f"No se pudo ejecutar {action_description}: {error}",
        )

    return ScriptRunResult(
        success=completed.returncode == 0,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def run_project_script(
    script_id: str,
    project_path: str,
    timeout_seconds: float = DEFAULT_SCRIPT_TIMEOUT_SECONDS,
) -> ScriptRunResult:
    """Localiza el script `script_id` entre los catalogados de
    `project_path` (`discover_project_scripts`) y lo ejecuta como
    subproceso, en `project_path` como directorio de trabajo.

    Nunca lanza una excepción no controlada (criterio de aceptación
    explícito) — cualquier fallo (manifiesto mal formado, `script_id`
    desconocido, comando inexistente, timeout agotado) se traduce a un
    `ScriptRunResult` con `success=False`, `exit_code=None` y
    `error_message` explicando el motivo. Un script que sí llega a
    ejecutarse pero termina con código de salida distinto de cero también
    es `success=False`, pero con `exit_code` real y su `stdout`/`stderr`
    disponibles para diagnóstico (distinto del caso anterior: aquí el
    script SÍ corrió, solo que falló)."""
    try:
        catalogued_scripts = discover_project_scripts(project_path)
    except MalformedScriptManifestError as error:
        return ScriptRunResult(
            success=False,
            exit_code=None,
            stdout="",
            stderr="",
            error_message=str(error),
        )

    script = next((entry for entry in catalogued_scripts if entry.id == script_id), None)
    if script is None:
        return ScriptRunResult(
            success=False,
            exit_code=None,
            stdout="",
            stderr="",
            error_message=(
                f"No existe ningún script catalogado con id '{script_id}' "
                f"en '{project_path}'."
            ),
        )

    return run_subprocess(
        script.command,
        project_path,
        timeout_seconds,
        shell=True,
        action_description=f"el script '{script_id}'",
    )

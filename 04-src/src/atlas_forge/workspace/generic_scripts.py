"""Catálogo fijo de scripts genéricos (T-AF018-US01-01/02): a diferencia de
los scripts particulares de un proyecto (`discover_project_scripts`,
T-AF001-US03-01, que cada repo declara en su propio manifiesto), estos
viven en el propio Atlas Forge y son iguales para cualquier proyecto del
workspace — no tiene sentido pedirle a cada repositorio que declare `git
commit` o `git push` por su cuenta.

Los seis scripts del catálogo:
- `commit`, `push`, `changed_files`, `diff_stat` (T-AF018-US01-01): basados
  únicamente en `git`, ya presente en cualquier entorno con un repo.
- `language_stats` (T-AF018-US01-02): desglose de lenguajes y líneas de
  código — requiere una herramienta externa (ver decisión y mecanismo de
  instalación más abajo).
- `backlog_status` (T-AF018-US02-02): estado del backlog (conteo US/Task por
  estado agrupado por Epic, items TO_DO LISTA por prioridad, items TO_DO
  BLOQUEADA con su dependencia pendiente y cadena de mayor apalancamiento).
  Es la ÚNICA entrada pura de Python del catálogo: no ejecuta un subproceso
  sobre el proyecto, sino que reusa `build_backlog_report` de
  `atlas_forge.backlog.report` (la misma función de cálculo que el comando
  `atlas_forge backlog-status`) y devuelve su dict JSON en stdout — decisión
  documentada, ver sección "[`backlog_status`: entrada de cálculo, no de
  subproceso]" abajo.

Dos de los basados en git (`changed_files`, `diff_stat`) están motivados
directamente por ahorro de tokens de agentes cognitivos: un `git diff`
completo puede tener miles de líneas irrelevantes (lockfiles regenerados,
ficheros generados) que Developer/Critic no necesitan cargar en su contexto
— el resumen (`--stat`/`--name-only`) da la misma información útil por una
fracción del coste. `language_stats` cubre el mismo problema para entender
"qué tipo de proyecto es este" sin recorrer el árbol de ficheros contando
extensiones a mano.

## Reutilización, no duplicación

La ejecución como subproceso no se reimplementa aquí: se reutiliza
`run_subprocess` de `atlas_forge.workspace.project_scripts` (el mecanismo de
T-AF001-US03-02, extraído como función compartida) y el mismo tipo
`ScriptRunResult`. Los comandos se pasan como lista de argumentos sin shell
(`shell=False`): el mensaje de commit y la ruta del proyecto son
parámetros del usuario y no deben interpretarse como código de shell (mismo
criterio de seguridad ya aplicado en `resolve_tailscale_host`,
`atlas_forge/api/host.py`), a diferencia del comando de shell declarado por un
tercero en el manifiesto de scripts particulares.

## `language_stats`: herramienta elegida y mecanismo de instalación

### Decisión real tomada (T-AF018-US01-02)

El candidato investigado era `tokei` (Rust, ~20x más rápido que `cloc`,
gitignore-aware, 150+ lenguajes, JSON nativo). Se verificó en esta VM que
`tokei` NO está instalado (`which tokei` → ausente). Para instalarlo se
evaluaron las dos vías del enunciado:
1. `cargo install tokei` — inviable aquí: `cargo`/Rust NO están instalados
   (`which cargo` → ausente), e instalarlo exigiría montar toda la cadena
   Rust (rustup/rustc/cargo) solo para este script. Fricción
   desproporcionada para una utilidad de visibilidad.
2. Paquete del sistema — `apt` (Debian bookworm) NO tiene ningún paquete
   para `tokei`; sí tiene `cloc` (`apt-cache policy cloc` → candidato
   1.96-1).

Por tanto se eligió **`cloc` como alternativa**, la opción de menor
fricción real en esta VM (un solo paquete del sistema, ya instalado).
`cloc` está más establecido que `tokei` (aunque es más lento), soporta
también salida JSON nativa y no exige instalar nada más que él mismo.

### Mecanismo de instalación (repetible en otra VM)

```sh
# Debian/Ubuntu
sudo apt-get install -y cloc
# macOS (Homebrew)
brew install cloc
# Verificación
cloc --version
```

La instalación quedó hecha en esta VM (cloc 1.96). Si el entorno donde
corre `atlas-forge-api` no tiene la herramienta, `run_generic_script` devuelve un
error explícito que menciona qué instalar (nunca un `FileNotFoundError`
genérico sin contexto — ver [run_generic_script] y [LANGUAGE_STATS_INSTALL_HINT]).

## [`backlog_status`: entrada de cálculo, no de subproceso]

### Decisión real tomada (T-AF018-US02-02)

El criterio 3 de la Task pide revisar si aplica exponer `backlog-status`
como entrada del catálogo `run_generic_script` "sin duplicar la lógica de
invocación". Decisión: **SÍ aplica, y se implementa como la única entrada
pura de Python del catálogo.**

A diferencia de los cinco scripts basados en subprocesos (git/cloc), el
informe de backlog es un cálculo ya resuelto en `atlas_forge.backlog.report` con
parser determinista de texto — NO necesita ni un subproceso ni una
herramienta externa. Exponerlo en el catálogo da a los agentes cognitivos
(Developer/Critic/Planificador) el mismo ahorro de tokens que los scripts
git (US-AF018-02), vía la interfaz ya conocida `run_generic_script`.

Para NO duplicar lógica de invocación, `run_generic_script` llama
directamente a `build_backlog_report`/`render_json_report` (la misma fuente
de cálculo que el comando `atlas_forge backlog-status`); la entrada no ejecuta un
subproceso propio ni reimplementa el renderizado. Igual que el resto del
catálogo, rechaza un `project_path` que no sea un repositorio git válido y
nunca lanza excepción no controlada. El directorio del backlog se deriva
como `<project_path>/02-backlog/` (convención de todo proyecto del
workspace); un proyecto recién creado sin US/Tasks devuelve
`success=True` con el informe `empty=True` ("sin datos"), igual que el
comando.
"""

import shutil
from pathlib import Path

from atlas_forge.backlog.report import build_backlog_report, render_json_report
from atlas_forge.models import GenericScriptEntry, ScriptRunResult
from atlas_forge.workspace.discovery import is_git_repository
from atlas_forge.workspace.project_scripts import DEFAULT_SCRIPT_TIMEOUT_SECONDS, run_subprocess

# Herramienta externa usada por `language_stats` (decisión documentada en
# el docstring del módulo: `cloc` elegido sobre `tokei` porque en esta VM
# `tokei`/`cargo` no están instalados y no hay paquete de sistema para
# tokei, mientras `cloc` es un único paquete del sistema ya instalado).
LANGUAGE_STATS_TOOL = "cloc"

# Cómo instalar la herramienta en otra VM — parte del mecanismo de
# instalación documentado (criterio de aceptación explícito): el error de
# "herramienta ausente" incluye este hint, para que quien lo reciba sepa
# exactamente qué hacer, sin tener que buscar en el código.
LANGUAGE_STATS_INSTALL_HINT = (
    "instala 'cloc' con el gestor de paquetes de tu sistema "
    "(Debian/Ubuntu: 'sudo apt-get install -y cloc'; macOS/Homebrew: "
    "'brew install cloc') y vuelve a intentarlo."
)

# Registro fijo en código (no leído de ningún fichero, criterio de
# aceptación explícito de T-AF018-US01-01): mismos scripts para cualquier
# proyecto, sin parámetro de proyecto en la consulta.
GENERIC_SCRIPTS: tuple[GenericScriptEntry, ...] = (
    GenericScriptEntry(id="commit", name="Commit de cambios", description="Guarda los cambios del área de staging en el historial de git con un mensaje descriptivo."),
    GenericScriptEntry(id="push", name="Push al remoto", description="Envía los commits locales al repositorio remoto configurado."),
    GenericScriptEntry(id="changed_files", name="Ficheros modificados", description="Lista los nombres de los ficheros con cambios respecto al último commit."),
    GenericScriptEntry(id="diff_stat", name="Resumen de cambios por fichero", description="Muestra un resumen de líneas añadidas y eliminadas por cada fichero modificado."),
    GenericScriptEntry(id="language_stats", name="Desglose de lenguajes y líneas de código", description="Analiza el proyecto con cloc y muestra el desglose de líneas de código por lenguaje."),
    GenericScriptEntry(id="backlog_status", name="Estado del backlog (conteo, dependencias y siguiente foco)", description="Calcula el estado actual del backlog: conteo por estado, dependencias bloqueantes y cadena de mayor apalancamiento."),
    GenericScriptEntry(id="run_tests", name="Ejecutar tests del proyecto", description="Ejecuta la suite de tests del proyecto con pytest y muestra el resultado."),
)


def list_generic_scripts() -> list[GenericScriptEntry]:
    """Catálogo fijo de scripts genéricos — el mismo para cualquier
    proyecto, sin parámetro de proyecto (criterio de aceptación
    explícito). Devuelve una copia nueva para que el llamador no pueda
    mutar el registro interno."""
    return list(GENERIC_SCRIPTS)


def _git_command(script_id: str, params: dict) -> tuple[list[str], str] | None:
    """Resuelve el comando git real (lista de argumentos sin shell) para
    `script_id` con sus `params`. Devuelve `None` si `script_id` no
    pertenece al catálogo — el llamador traduce eso a un resultado de error
    explícito, nunca una excepción no controlada."""
    if script_id == "commit":
        message = params.get("message")
        if not isinstance(message, str) or not message.strip():
            return None
        return ["git", "commit", "-m", message], "commit"
    if script_id == "push":
        return ["git", "push"], "push"
    if script_id == "changed_files":
        return ["git", "diff", "--name-only"], "changed_files"
    if script_id == "diff_stat":
        return ["git", "diff", "--stat"], "diff_stat"
    return None


def _require_external_tool(script_id: str) -> ScriptRunResult | None:
    """Verifica que la herramienta externa de `language_stats` esté
    disponible en el sistema (criterio de aceptación explícito de
    T-AF018-US01-02). Devuelve `None` si lo está; si no, un
    [ScriptRunResult] de error explícito que menciona qué instalar — nunca
    un `FileNotFoundError` genérico sin contexto."""
    if shutil.which(LANGUAGE_STATS_TOOL) is None:
        return ScriptRunResult(
            success=False,
            exit_code=None,
            stdout="",
            stderr="",
            error_message=(
                f"El script genérico '{script_id}' necesita la herramienta "
                f"'{LANGUAGE_STATS_TOOL}', que no está instalada en este "
                f"sistema: {LANGUAGE_STATS_INSTALL_HINT}"
            ),
        )
    return None


def _locate_tests_dir(project_path: str) -> Path | None:
    """Localiza el directorio de tests del proyecto (bug: monorepo con tests en subproyecto 04-src/).

    Busca primero `tests/` en la raíz de `project_path` (caso simple de
    proyecto plano). Si no existe, busca en los subdirectorios de primer
    nivel que sean el subproyecto Python de un monorepo: el que contenga
    un `tests/` Y un `pyproject.toml` (p. ej. `04-src/` en Atlas Forge)
    — el `pyproject.toml` distingue el subproyecto real de carpetas
    genéricas (`docs/`, `10-web/`, etc.) que también podrían tener un
    `tests/` suelto. Devuelve `None` si no hay ningún directorio de tests
    localizable."""
    root = Path(project_path)
    direct = root / "tests"
    if direct.is_dir():
        return direct
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        candidate = child / "tests"
        if candidate.is_dir() and (child / "pyproject.toml").is_file():
            return candidate
    return None


def _find_test_runner(project_path: str) -> list[str] | None:
    """Busca un test runner disponible para `project_path`. Prueba en orden:
    `pytest` (el del venv del subproyecto si existe, sino el global),
    `python3 -m pytest`. Devuelve la lista de argumentos sin shell o `None`
    si ninguno está disponible. El comando se resuelve para ejecutarse con
    `cwd` en el directorio que contiene `tests/` (raíz o subproyecto del
    monorepo) — ver `_locate_tests_dir`."""
    import shutil as _shutil

    tests_dir = _locate_tests_dir(project_path)
    if tests_dir is None:
        return None

    project_dir = tests_dir.parent
    # Ruta del tests/ relativa al cwd de ejecución (raíz o subproyecto) —
    # los argumentos de pytest deben ser relativos a ese cwd.
    try:
        rel_tests = str(tests_dir.relative_to(project_dir))
    except ValueError:
        rel_tests = str(tests_dir)

    venv_pytest = project_dir / ".venv" / "bin" / "pytest"
    if venv_pytest.is_file():
        return [str(venv_pytest), rel_tests, "-v"]
    if _shutil.which("pytest"):
        return ["pytest", rel_tests, "-v"]
    if _shutil.which("python3"):
        return ["python3", "-m", "pytest", rel_tests, "-v"]
    return None


# T-AF025-US04-02: timeout DEFINITIVO de `run_tests`, acorde a la suite que
# realmente ejecuta el Tester (el subconjunto determinista `unit` por defecto,
# rápido; la integración completa, si el operador la pide con `scope=all`,
# tarda varios minutos con tmux real). Por-call: no infla el default global de
# los scripts regulares (`DEFAULT_SCRIPT_TIMEOUT_SECONDS`).
RUN_PROJECT_TESTS_TIMEOUT_SECONDS = 1800.0

# Guard anti-recursión (T-AF025-US04-02, hallazgo del Tester): si un test
# del subconjunto `unit` lanza la acción `testear` (que a su vez ejecuta
# `pytest -m unit`), se produciría una recursión infinita (el pytest anidado
# re-colecta el mismo test, que vuelve a lanzar otro pytest...) hasta el
# timeout de 1800s. Este marcador de entorno lo setea el subproceso que
# `run_tests` lanza; si `run_tests` vuelve a invocarse DENTRO de esa
# ejecución (padre en cadena), no re-anida y devuelve un resultado explícito.
_ATLAS_FORGE_RUNNING_TESTS = "ATLAS_FORGE_RUNNING_TESTS"


def _run_project_tests(project_path: str, scope: str = "unit") -> ScriptRunResult:
    """Ejecuta los tests del proyecto (`pytest` o equivalente) como paso
    determinista (T-AF022-US12-03). No es parte del razonamiento del
    Tester — es un script genérico del catálogo AF-018.

    T-AF025-US04-02 — política de subconjunto de suite (decisión tomada y
    documentada): el ciclo Tester ejecuta por defecto el subconjunto
    DETERMINISTA y rápido (los tests etiquetados con el marcador `unit`),
    no la suite completa de integración con tmux real (que además se
    colgaba por contaminación de estado). `scope`:
      - `"unit"` (default): `pytest <tests> -m unit` — solo lo determinista
        y rápido; nunca arranca tmux/agentes reales ni un backend en vivo.
      - `"all"`: `pytest <tests>` — la suite completa (integración incluida);
        la pide el operador explícitamente y usa
        `RUN_PROJECT_TESTS_TIMEOUT_SECONDS`.
    Como ancla genérica: si el proyecto NO etiqueta nada como `unit` (no hay
    marcadores), `-m unit` no seleccionaría ningún test; en ese caso se
    ejecuta el directorio `tests/` completo (fallback determinista para
    proyectos sin la división).

    Devuelve `ScriptRunResult` con `success=True` si todos los tests pasan
    (exit_code 0), o `success=False` con el detalle de fallos en
    `stdout`/`stderr`. Si no se encuentra un test runner disponible,
    devuelve un resultado de error explícito, nunca una excepción no
    controlada."""
    tests_dir = _locate_tests_dir(project_path)
    if tests_dir is None:
        return ScriptRunResult(
            success=False,
            exit_code=None,
            stdout="",
            stderr="",
            error_message=(
                "No se encontró un test runner disponible en este "
                "proyecto. Se necesita 'pytest' instalado y un "
                "directorio 'tests/' con tests."
            ),
        )
    command = _find_test_runner(project_path)
    if command is None:
        return ScriptRunResult(
            success=False,
            exit_code=None,
            stdout="",
            stderr="",
            error_message=(
                "No se encontró un test runner disponible en este "
                "proyecto. Se necesita 'pytest' instalado y un "
                "directorio 'tests/' con tests."
            ),
        )
    if scope == "unit" and _any_unit_marker(tests_dir):
        # Selección por marcador: solo lo etiquetado `unit` (determinista).
        command = list(command[0:2]) + ["-m", "unit", "-v"]
    # Guard anti-recursión (T-AF025-US04-02): si ESTA invocación de
    # `run_tests` ocurre dentro de una ejecución de pytest ya lanzada por
    # `run_tests` (p. ej. un test del subconjunto `unit` disparando la
    # acción `testear`), NO se anida otro `pytest` — devolvemos un resultado
    # explícito que deja claro que el trabajo ya lo está haciendo el pytest
    # padre (evita la recursión infinita hasta el timeout de 1800s).
    import os as _os

    if _os.environ.get(_ATLAS_FORGE_RUNNING_TESTS):
        return ScriptRunResult(
            success=False,
            exit_code=None,
            stdout="",
            stderr="",
            error_message=(
                "run_tests ignorado: ya hay una ejecución de tests del "
                "proyecto en vuelo (la lanzó este mismo script) — no se "
                "anidian ejecuciones de pytest para evitar recursión."
            ),
        )
    _previous = _os.environ.get(_ATLAS_FORGE_RUNNING_TESTS)
    try:
        _os.environ[_ATLAS_FORGE_RUNNING_TESTS] = "1"
        return run_subprocess(
            command,
            str(tests_dir.parent),
            RUN_PROJECT_TESTS_TIMEOUT_SECONDS,
            action_description="el script genérico 'run_tests'",
        )
    finally:
        if _previous is None:
            _os.environ.pop(_ATLAS_FORGE_RUNNING_TESTS, None)
        else:
            _os.environ[_ATLAS_FORGE_RUNNING_TESTS] = _previous


def _any_unit_marker(tests_dir: Path) -> bool:
    """`True` si algún `test_*.py` de `tests_dir` (recursivo) declara el
    marcador `unit` (`pytestmark = pytest.mark.unit`) — el subconjunto
    determinista que `run_tests` ejecuta por defecto. Si no hay ninguno, el
    proyecto no usa la división y el fallback corre el directorio completo."""
    if not tests_dir.is_dir():
        return False
    for path in tests_dir.rglob("test_*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "pytestmark = pytest.mark.unit" in text:
            return True
    return False


def run_generic_script(
    script_id: str,
    project_path: str,
    **params: object,
) -> ScriptRunResult:
    """Resuelve el comando real de `script_id` y lo ejecuta como subproceso
    sobre `project_path` (directorio de trabajo), reutilizando el mecanismo
    de ejecución de T-AF001-US03-02 (`run_subprocess`) y el mismo tipo
    `ScriptRunResult` (no uno nuevo).

    Nunca lanza una excepción no controlada (mismo criterio que
    `run_project_script`): cualquier fallo se traduce a un `ScriptRunResult`
    con `success=False` — `script_id` desconocido, `project_path` que no es
    un repositorio git válido (rechazo explícito), un fallo real de git
    (nada que comitear, remoto no configurado, conflicto) que se refleja
    con la salida real en `stdout`/`stderr` y su `exit_code`, o la
    herramienta externa de `language_stats` ausente (error explícito con la
    instrucción de instalación, ver [LANGUAGE_STATS_INSTALL_HINT]).
    `params["message"]` (string no vacío) es obligatorio para `commit` y su
    ausencia se rechaza con un mensaje explícito."""
    if script_id == "commit":
        message = params.get("message")
        if not isinstance(message, str) or not message.strip():
            return ScriptRunResult(
                success=False,
                exit_code=None,
                stdout="",
                stderr="",
                error_message=(
                    "El script genérico 'commit' requiere un parámetro "
                    "'message' no vacío."
                ),
            )

    resolved = _git_command(script_id, params)
    if resolved is None and script_id not in ("language_stats", "backlog_status", "run_tests"):
        return ScriptRunResult(
            success=False,
            exit_code=None,
            stdout="",
            stderr="",
            error_message=f"No existe ningún script genérico con id '{script_id}'.",
        )

    if not is_git_repository(Path(project_path)):
        return ScriptRunResult(
            success=False,
            exit_code=None,
            stdout="",
            stderr="",
            error_message=(
                f"'{project_path}' no es un repositorio git válido — no se "
                f"puede ejecutar el script genérico '{script_id}'."
            ),
        )

    if script_id == "language_stats":
        tool_error = _require_external_tool(script_id)
        if tool_error is not None:
            return tool_error
        command: list[str] = [
            LANGUAGE_STATS_TOOL,
            "--json",
            "--quiet",
            project_path,
        ]
    elif script_id == "backlog_status":
        backlog_path = Path(project_path) / "02-backlog"
        report = build_backlog_report(backlog_path)
        return ScriptRunResult(
            success=True,
            exit_code=0,
            stdout=render_json_report(report),
            stderr="",
        )
    elif script_id == "run_tests":
        # T-AF025-US04-02: `scope` (default "unit") decide el subconjunto
        # de suite que ejecuta run_tests — ver `_run_project_tests`.
        scope = str(params.get("scope") or "unit")
        return _run_project_tests(project_path, scope=scope)
    else:
        command, _label = resolved  # type: ignore[misc]

    return run_subprocess(
        command,
        project_path,
        DEFAULT_SCRIPT_TIMEOUT_SECONDS,
        action_description=f"el script genérico '{script_id}'",
    )

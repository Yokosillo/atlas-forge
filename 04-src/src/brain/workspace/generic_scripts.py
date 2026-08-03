"""Catálogo fijo de scripts genéricos (T-FB018-US01-01/02): a diferencia de
los scripts particulares de un proyecto (`discover_project_scripts`,
T-FB001-US03-01, que cada repo declara en su propio manifiesto), estos
viven en el propio Factory Brain y son iguales para cualquier proyecto del
workspace — no tiene sentido pedirle a cada repositorio que declare `git
commit` o `git push` por su cuenta.

Los seis scripts del catálogo:
- `commit`, `push`, `changed_files`, `diff_stat` (T-FB018-US01-01): basados
  únicamente en `git`, ya presente en cualquier entorno con un repo.
- `language_stats` (T-FB018-US01-02): desglose de lenguajes y líneas de
  código — requiere una herramienta externa (ver decisión y mecanismo de
  instalación más abajo).
- `backlog_status` (T-FB018-US02-02): estado del backlog (conteo US/Task por
  estado agrupado por Epic, items TODO LISTA por prioridad, items TODO
  BLOQUEADA con su dependencia pendiente y cadena de mayor apalancamiento).
  Es la ÚNICA entrada pura de Python del catálogo: no ejecuta un subproceso
  sobre el proyecto, sino que reusa `build_backlog_report` de
  `brain.backlog.report` (la misma función de cálculo que el comando
  `brain backlog-status`) y devuelve su dict JSON en stdout — decisión
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
`run_subprocess` de `brain.workspace.project_scripts` (el mecanismo de
T-FB001-US03-02, extraído como función compartida) y el mismo tipo
`ScriptRunResult`. Los comandos se pasan como lista de argumentos sin shell
(`shell=False`): el mensaje de commit y la ruta del proyecto son
parámetros del usuario y no deben interpretarse como código de shell (mismo
criterio de seguridad ya aplicado en `resolve_tailscale_host`,
`brain/api/host.py`), a diferencia del comando de shell declarado por un
tercero en el manifiesto de scripts particulares.

## `language_stats`: herramienta elegida y mecanismo de instalación

### Decisión real tomada (T-FB018-US01-02)

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
corre `brain-api` no tiene la herramienta, `run_generic_script` devuelve un
error explícito que menciona qué instalar (nunca un `FileNotFoundError`
genérico sin contexto — ver [run_generic_script] y [LANGUAGE_STATS_INSTALL_HINT]).

## [`backlog_status`: entrada de cálculo, no de subproceso]

### Decisión real tomada (T-FB018-US02-02)

El criterio 3 de la Task pide revisar si aplica exponer `backlog-status`
como entrada del catálogo `run_generic_script` "sin duplicar la lógica de
invocación". Decisión: **SÍ aplica, y se implementa como la única entrada
pura de Python del catálogo.**

A diferencia de los cinco scripts basados en subprocesos (git/cloc), el
informe de backlog es un cálculo ya resuelto en `brain.backlog.report` con
parser determinista de texto — NO necesita ni un subproceso ni una
herramienta externa. Exponerlo en el catálogo da a los agentes cognitivos
(Developer/Critic/Planificador) el mismo ahorro de tokens que los scripts
git (US-FB018-02), vía la interfaz ya conocida `run_generic_script`.

Para NO duplicar lógica de invocación, `run_generic_script` llama
directamente a `build_backlog_report`/`render_json_report` (la misma fuente
de cálculo que el comando `brain backlog-status`); la entrada no ejecuta un
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

from brain.backlog.report import build_backlog_report, render_json_report
from brain.models import GenericScriptEntry, ScriptRunResult
from brain.workspace.discovery import is_git_repository
from brain.workspace.project_scripts import DEFAULT_SCRIPT_TIMEOUT_SECONDS, run_subprocess

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
# aceptación explícito de T-FB018-US01-01): mismos scripts para cualquier
# proyecto, sin parámetro de proyecto en la consulta.
GENERIC_SCRIPTS: tuple[GenericScriptEntry, ...] = (
    GenericScriptEntry(id="commit", name="Commit de cambios"),
    GenericScriptEntry(id="push", name="Push al remoto"),
    GenericScriptEntry(id="changed_files", name="Ficheros modificados"),
    GenericScriptEntry(id="diff_stat", name="Resumen de cambios por fichero"),
    GenericScriptEntry(id="language_stats", name="Desglose de lenguajes y líneas de código"),
    GenericScriptEntry(id="backlog_status", name="Estado del backlog (conteo, dependencias y siguiente foco)"),
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
    T-FB018-US01-02). Devuelve `None` si lo está; si no, un
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


def run_generic_script(
    script_id: str,
    project_path: str,
    **params: object,
) -> ScriptRunResult:
    """Resuelve el comando real de `script_id` y lo ejecuta como subproceso
    sobre `project_path` (directorio de trabajo), reutilizando el mecanismo
    de ejecución de T-FB001-US03-02 (`run_subprocess`) y el mismo tipo
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
    if resolved is None and script_id not in ("language_stats", "backlog_status"):
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
        # Única entrada pura de Python del catálogo: reusa el cálculo del
        # comando `brain backlog-status` (misma fuente de verdad), no ejecuta
        # un subproceso propio — decisión documentada en el docstring del
        # módulo. Un proyecto recién creado sin US/Tasks es un resultado
        # válido (`success=True`, informe `empty=True`), igual que el comando.
        backlog_path = Path(project_path) / "02-backlog"
        report = build_backlog_report(backlog_path)
        return ScriptRunResult(
            success=True,
            exit_code=0,
            stdout=render_json_report(report),
            stderr="",
        )
    else:
        command, _label = resolved  # type: ignore[misc]

    return run_subprocess(
        command,
        project_path,
        DEFAULT_SCRIPT_TIMEOUT_SECONDS,
        action_description=f"el script genérico '{script_id}'",
    )

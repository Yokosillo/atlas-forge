"""Lectura y cambio del modelo activo de un agente OpenCode en ejecucion
(T-FB004-US05-01).

`get_active_model` lee el modelo actual desde la barra de estado de
OpenCode via `capture_pane_lines`. `set_active_model` lo cambia mediante
atajos de teclado (Ctrl+P, Ctrl+X, navegacion con flechas, Enter) con
verificacion del estado de la interfaz entre cada paso.

Ninguna funcion lanza una excepcion no controlada ante un runtime no
soportado o un parseo fallido — devuelven None/False respectivamente.

## Patron de texto de la barra de estado de OpenCode (documentado por
## fragilidad)

El parseo busca la linea `"Build · <nombre del modelo> <proveedor>"` en
el pane, p. ej. `"Build · DeepSeek V4 Flash DeepSeek"` o
`"Build · DeepSeek V4 Flash Free (New) OpenCode Zen"`.

Este patron es fragil: depende del texto literal que OpenCode decida
mostrar en su barra de estado, que puede cambiar entre versiones del
binario sin previo aviso. Si el patron deja de coincidir, el sistema
devuelve `None` sin fallar — no hay heuristica de respaldo.
"""

from __future__ import annotations

import time
from pathlib import Path

from brain.runtime.agent_runtime_registry import (
    get_runtime_instance_for_agent,
)
from brain.tmux import (
    DEFAULT_SOCKET_NAME,
    capture_pane_lines,
    is_alive,
    send_keys_literal,
)

_MODEL_STATUS_PATTERN = "Build · "

_STEP_SLEEP_S = 0.3
_VERIFY_SLEEP_S = 2.0

def get_available_models(catalog_path: Path | None = None) -> list[str]:
    """Identificadores de modelos disponibles (solo IDs), leidos del fichero
    de catalogo (`models.yml`, T-FB022-US09). Consultable sin necesidad de
    un agente en ejecucion.

    `catalog_path` opcional permite tests aislados sin tocar el fichero real
    del proyecto Factory Brain."""
    from brain.models_catalog import load_model_catalog

    return [entry.id for entry in load_model_catalog(catalog_path=catalog_path)]


def get_available_model_entries(catalog_path: Path | None = None) -> list[dict]:
    """Catalogo completo de modelos (id + name + runtime), leido del fichero
    de configuracion (`models.yml`, T-FB022-US09). Consultable sin necesidad
    de un agente en ejecucion.

    Devuelve una lista de dicts `{id, name, runtime}` — la capa HTTP puede
    serializar esto directamente."""
    from brain.models_catalog import load_model_catalog

    return [
        {"id": entry.id, "name": entry.name, "runtime": entry.runtime}
        for entry in load_model_catalog(catalog_path=catalog_path)
    ]


_CATALOG_RUNTIME_TO_REAL_TYPE = {
    # El catalogo (models.yml) usa snake_case para los 3 runtimes
    # soportados (`opencode`, `claude_code`, `codex`), pero el runtime
    # real registrado por `register_claude_code_runtime` usa `claude-code`
    # (kebab-case, T-FB002-US01-01) — unica discrepancia entre ambos
    # vocabularios, `opencode` coincide en los dos.
    "claude_code": "claude-code",
}


def resolve_runtime_for_model(
    model_id: str, *, catalog_path: Path | None = None
) -> str | None:
    """Resuelve el runtime asociado al modelo `model_id` desde el catalogo.
    Devuelve el tipo de runtime real tal como lo espera `launch_agent`
    (`opencode`, `claude-code`, `codex`) o `None` si el modelo no esta en
    el catalogo."""
    from brain.models_catalog import load_model_catalog

    entries = load_model_catalog(catalog_path=catalog_path)
    for entry in entries:
        if entry.id == model_id:
            return _CATALOG_RUNTIME_TO_REAL_TYPE.get(entry.runtime, entry.runtime)
    return None


def get_active_model(
    agent_id: str, *, socket_name: str | None = None
) -> str | None:
    """Lee el modelo activo desde la barra de estado de OpenCode.

    Devuelve el texto extraido tras `"Build · "` (nombre del modelo +
    proveedor), o `None` si:
    - El runtime no es OpenCode.
    - El agente no tiene runtime registrado.
    - La sesion tmux no esta viva.
    - El patron `"Build · "` no aparece en el pane.
    - Cualquier excepcion inesperada (atrapada, nunca se propaga).

    No modifica el estado del agente ni su sesion tmux."""
    rt = get_runtime_instance_for_agent(agent_id)
    if rt is None:
        return None
    if rt.runtime.type != "opencode":
        return None

    session_name = rt.session_name
    sock = socket_name or DEFAULT_SOCKET_NAME

    if not is_alive(session_name, socket_name=sock):
        return None

    try:
        lines = capture_pane_lines(session_name, socket_name=sock)
    except Exception:
        return None

    return _parse_model_from_pane(lines)


def _parse_model_from_pane(lines: list[str]) -> str | None:
    """Extrae el modelo de la barra de estado de OpenCode.

    Busca la ultima linea que contenga `"Build · "` (barra de estado al
    fondo del pane) y devuelve el texto tras el patron. `None` si no se
    encuentra."""
    for line in reversed(lines):
        if _MODEL_STATUS_PATTERN in line:
            rest = line.split(_MODEL_STATUS_PATTERN, 1)[1].strip()
            if rest:
                return rest
    return None


def set_active_model(
    agent_id: str,
    model_name: str,
    *,
    socket_name: str | None = None,
) -> bool:
    """Cambia el modelo activo de un agente OpenCode en ejecucion.

    Flujo real confirmado por el usuario:
    1. Ctrl+P → abre el selector de comandos de OpenCode.
    2. Ctrl+X → atajo de cambio de modelo dentro del selector.
    3. Navegacion con flechas hasta encontrar el modelo deseado.
    4. Enter para seleccionar.
    5. Verificacion: leer el modelo tras el cambio.

    Cada paso se verifica (captura del pane antes y despues). Si algun
    paso falla, se devuelve `False` sin lanzar excepcion.

    El agente debe estar en ejecucion (sesion tmux viva) y ser OpenCode.
    No modifica el estado del agente (sigue `idle`/`working`)."""
    rt = get_runtime_instance_for_agent(agent_id)
    if rt is None or rt.runtime.type != "opencode":
        return False

    session_name = rt.session_name
    sock = socket_name or DEFAULT_SOCKET_NAME

    if not is_alive(session_name, socket_name=sock):
        return False

    # Guardar el modelo previo para comparar al final.
    previous = get_active_model(agent_id, socket_name=sock)

    try:
        # Paso 1: Ctrl+P (abrir selector de comandos)
        _send_and_verify_change(session_name, "C-p", sock, "Ctrl+P")

        # Paso 2: Ctrl+X (cambio de modelo dentro del selector)
        _send_and_verify_change(session_name, "C-x", sock, "Ctrl+X")
        time.sleep(2.0)  # esperar que se cargue la lista de modelos en el selector

        # Paso 3: Leer el selector para encontrar el indice del modelo.
        selector_lines = _capture_safe(session_name, sock)
        if selector_lines is None:
            return False
        index = _find_model_index(selector_lines, model_name)
        if index is None:
            return False

        # Paso 4: Navegar con flecha abajo hasta el modelo deseado.
        for _ in range(index):
            send_keys_literal(session_name, "Down", socket_name=sock)
            time.sleep(0.1)

        # Paso 5: Enter para seleccionar.
        send_keys_literal(session_name, "Enter", socket_name=sock)
        time.sleep(2.0)  # esperar que OpenCode procese el cambio

        # Paso 6: Verificacion final.
        current = get_active_model(agent_id, socket_name=sock)
        if current is None:
            return False
        if current == model_name:
            return True
        if previous is not None and current == previous:
            return False  # no cambio
        # Devuelve True si el modelo leido tiene interseccion suficiente
        # con el nombre pedido (el proveedor puede variar en el texto de
        # estado de OpenCode respecto al nombre pasado por parametro).
        if _model_names_match(current, model_name):
            return True
        return False

    except Exception:
        return False


def _send_and_verify_change(
    session_name: str, keys: str, socket_name: str, label: str
) -> bool:
    """Envia `keys` y verifica que el contenido del pane cambio."""
    before = _capture_safe(session_name, socket_name)
    send_keys_literal(session_name, keys, socket_name=socket_name)
    time.sleep(_STEP_SLEEP_S)
    after = _capture_safe(session_name, socket_name)
    if before is None or after is None:
        return False
    return before != after


def _capture_safe(session_name: str, socket_name: str) -> list[str] | None:
    try:
        return capture_pane_lines(session_name, socket_name=socket_name)
    except Exception:
        return None


def _find_model_index(lines: list[str], model_name: str) -> int | None:
    """Busca `model_name` (o un fragmento significativo) entre las lineas
    del selector de modelos y devuelve su indice (0-based). `None` si no se
    encuentra.

    La heuristica: busca lineas que contengan el nombre completo o el
    nombre del modelo sin proveedor, en las lineas tras la apertura del
    selector. Si hay multiples coincidencias, se queda con la primera."""
    if not lines:
        return None

    model_lower = model_name.lower().strip()

    # Intenta coincidencia exacta del nombre completo (case-insensitive).
    for idx, line in enumerate(lines):
        if model_lower in line.lower():
            return idx

    # Si el nombre incluye "/" (formato provider/model), intenta solo
    # con la parte del modelo (despues de la barra).
    if "/" in model_name:
        model_part = model_name.rsplit("/", 1)[1].strip().lower()
        for idx, line in enumerate(lines):
            if model_part in line.lower():
                return idx

    return None


def _model_names_match(current: str, requested: str) -> bool:
    """Comparacion laxa de nombres de modelo — True si `requested` aparece
    como subcadena dentro de `current` (el nombre en la barra de estado de
    OpenCode puede tener texto adicional del proveedor, versiones, etc.).

    Ambos se normalizan a minusculas y sin espacios extra."""
    cur = current.lower().strip()
    req = requested.lower().strip()
    if cur == req:
        return True
    if "/" in req:
        model_part = req.rsplit("/", 1)[1]
        if model_part in cur:
            return True
    if req in cur:
        return True
    return False

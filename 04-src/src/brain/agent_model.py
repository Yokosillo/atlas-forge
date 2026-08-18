"""Lectura y cambio del modelo activo de un agente OpenCode en ejecucion
(T-FB004-US05-01), y lectura bajo demanda del modelo activo de un agente
Claude Code (T-FB024-US11-05).

`get_active_model` lee el modelo actual desde la barra de estado de
OpenCode via `capture_pane_lines` — lectura PASIVA, sin interactuar con
el pane, segura de invocar en cada `GET /agents`/polling.
`set_active_model` lo cambia mediante atajos de teclado (Ctrl+P, Ctrl+X,
navegacion con flechas, Enter) con verificacion del estado de la interfaz
entre cada paso.

`get_active_model_claude_code` lee el modelo activo de un agente Claude
Code enviando `/status` al pane (T-FB024-US11-05) — a diferencia de
OpenCode, Claude Code no tiene lectura pasiva posible (su barra de estado
no imprime el modelo, verificado en vivo). Por eso esta función NUNCA se
invoca automáticamente (ni desde `extract_model_from_runtime`, ni desde
`GET /agents`, ni desde ningún polling) — solo bajo demanda explícita del
humano (`GET /agents/{id}/status-model`), y solo si el agente está
`idle` (nunca interactúa con el pane de un agente `working`, mismo
criterio ya fijado para `set_active_model`/criterio 9 de `US-FB024-11`).

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

## Patron de texto del panel `/status` de Claude Code (documentado por
## fragilidad, mismo criterio que la barra de estado de OpenCode)

Verificado en vivo (`00-gobierno`, T-FB024-US11-05, captura real contra
el pane del Arquitecto) que `/status` + Enter abre un panel modal con una
línea `"Model:            Default (Sonnet 5 · Efficient for routine
tasks)"` — el parseo busca la línea que empieza por `"Model:"` (tras
strip) y devuelve el resto tras los dos puntos, con espacios colapsados.
Este patrón depende del texto/formato literal que Claude Code decida
mostrar en ese panel, que puede cambiar entre versiones de la CLI sin
previo aviso — igual de frágil que el patrón `"Build · "` de OpenCode, y
con el mismo criterio: si el patrón deja de coincidir, se devuelve `None`
sin fallar, sin heurística de respaldo.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from brain.runtime.agent_runtime_registry import (
    get_runtime_instance_for_agent,
)
from brain.runtime_model_contract import (
    RuntimeType,
    runtime_model_change_idle_only,
    runtime_supports_model_change,
    runtime_supports_model_read,
)
from brain.tmux import (
    DEFAULT_SOCKET_NAME,
    capture_pane_lines,
    is_alive,
    run_command,
    send_keys_literal,
)

_MODEL_STATUS_PATTERN = "Build · "
_CLAUDE_CODE_STATUS_MODEL_PATTERN = "Model:"

_STEP_SLEEP_S = 0.3
_VERIFY_SLEEP_S = 2.0
_STATUS_PANEL_OPEN_WAIT_S = 2.0
_STATUS_PANEL_CLOSE_WAIT_S = 0.3

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
    """Lee el modelo activo desde la barra de estado de OpenCode (lectura pasiva).

    Usa contrato de capacidades (T-FB005-US07-01) para verificar que el
    runtime soporta lectura pasiva de modelo. Devuelve el texto extraido
    tras `"Build · "` (nombre del modelo + proveedor), o `None` si:
    - El runtime no soporta lectura pasiva de modelo (contrato).
    - El agente no tiene runtime registrado.
    - La sesion tmux no esta viva.
    - El patron `"Build · "` no aparece en el pane.
    - Cualquier excepcion inesperada (atrapada, nunca se propaga).

    No modifica el estado del agente ni su sesion tmux."""
    rt = get_runtime_instance_for_agent(agent_id)
    if rt is None:
        return None

    # Usar contrato de capacidades en lugar de comprobación ad-hoc de "opencode"
    runtime_type = RuntimeType(rt.runtime.type)
    if not runtime_supports_model_read(runtime_type):
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


def get_active_model_claude_code(
    agent_id: str, *, socket_name: str | None = None
) -> str | None:
    """Lee el modelo activo de un agente Claude Code enviando `/status` al
    pane (T-FB024-US11-05) — INTERACCIÓN ACTIVA, a diferencia de
    `get_active_model` (OpenCode, lectura pasiva). Por eso esta función
    NUNCA debe invocarse automáticamente: quien la llame (la ruta HTTP
    bajo demanda) es responsable de comprobar que el agente está `idle`
    ANTES de invocarla — esta función no conoce `Agent.status` (vive en
    `brain.models`, una capa por encima de este módulo, que solo conoce
    `RuntimeInstance`/tmux), así que no puede hacer esa comprobación por
    su cuenta.

    Devuelve el texto tras `"Model:"` en el panel de `/status` (nombre +
    detalle entre paréntesis, tal cual lo muestra Claude Code), o `None`
    si:
    - El runtime no es Claude Code.
    - El agente no tiene runtime registrado.
    - La sesión tmux no está viva.
    - El patrón `"Model:"` no aparece en el panel tras esperar a que abra.
    - Cualquier excepción inesperada (atrapada, nunca se propaga).

    Flujo (verificado en vivo, ver docstring del módulo): envía `/status`
    + Enter (`run_command`, mismo mecanismo ya usado para lanzar el
    prompt inicial de un agente — `send_keys` con `enter=True` por
    defecto), espera a que el panel abra, captura el pane, cierra el
    panel con `Escape` (`send_keys_literal`) SIEMPRE — incluso si el
    parseo falla — para no dejar el pane del agente en un estado distinto
    al que tenía antes de consultar (criterio de aceptación 4 de la
    Task)."""
    rt = get_runtime_instance_for_agent(agent_id)
    if rt is None:
        return None
    if rt.runtime.type != "claude-code":
        return None

    session_name = rt.session_name
    sock = socket_name or DEFAULT_SOCKET_NAME

    if not is_alive(session_name, socket_name=sock):
        return None

    try:
        run_command(session_name, "/status", socket_name=sock)
        time.sleep(_STATUS_PANEL_OPEN_WAIT_S)
        lines = capture_pane_lines(session_name, socket_name=sock)
        model = _parse_model_from_claude_code_status(lines)
    except Exception:
        model = None
    finally:
        # Cerrar el panel pase lo que pase (parseo ok, fallido, o
        # excepción) — el pane nunca debe quedar en un estado distinto al
        # que tenía antes de consultar.
        try:
            send_keys_literal(session_name, "Escape", socket_name=sock)
            time.sleep(_STATUS_PANEL_CLOSE_WAIT_S)
        except Exception:
            pass

    return model


def _parse_model_from_claude_code_status(lines: list[str]) -> str | None:
    """Extrae el modelo del panel `/status` de Claude Code.

    Busca la última línea que, tras `strip()`, empiece por `"Model:"` y
    devuelve el resto tras los dos puntos, con espacios exteriores e
    interiores colapsados. `None` si no se encuentra o el resto está
    vacío."""
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith(_CLAUDE_CODE_STATUS_MODEL_PATTERN):
            rest = stripped[len(_CLAUDE_CODE_STATUS_MODEL_PATTERN):].strip()
            if rest:
                return rest
    return None


_MODEL_SWITCH_CONFIRM_WAIT_S = 1.0
_MODEL_SWITCH_CONFIRM_PATTERN = "Switch model?"


def set_active_model_claude_code(
    session_name: str,
    model_id: str,
    *,
    socket_name: str | None = None,
) -> None:
    """Cambia el modelo activo de un agente Claude Code EN CALIENTE
    (T-FB024-US11-13, decisión de producto 2026-08-17) enviando el
    comando interno `/model <id>` al pane de la sesión tmux
    `session_name` (NO el agent_id — resuelto por el llamador vía
    `runtime_instance.session_name`, mismo patrón que
    `POST /agents/{id}/send-keys`).

    ## Por qué hace falta una segunda confirmación (verificado en vivo)

    Cuando hay contexto de conversación cacheado sustancial que se
    perdería al cambiar de modelo, Claude Code no aplica el cambio de
    inmediato: abre un diálogo interno ("Switch model? ... 1. Yes, switch
    to <modelo> / 2. No, go back") que requiere una segunda pulsación —
    un solo `/model <id>` + Enter deja el diálogo abierto sin confirmar,
    y el modelo NUNCA cambia (bug real reportado por el usuario en vivo,
    confirmado conectándose directamente a la sesión tmux: el primer
    Enter por sí solo no basta). Cuando no hay contexto cacheado
    relevante, el diálogo no aparece y el cambio se aplica directo — así
    que esta función comprueba el pane tras el primer envío y solo manda
    el Enter de confirmación si el diálogo realmente apareció, para no
    enviar un Enter de más (línea en blanco) en el caso sin diálogo.

    No lanza excepción ante fallo de runtime/sesión — no hace nada
    (mismo criterio que el resto de funciones de este módulo); el
    llamador (`POST /agents/{id}/send-keys`) ya valida sesión/runtime
    antes de invocar esta función, así que aquí solo se asume una sesión
    tmux viva."""
    sock = socket_name or DEFAULT_SOCKET_NAME
    run_command(session_name, f"/model {model_id}", socket_name=sock)
    time.sleep(_MODEL_SWITCH_CONFIRM_WAIT_S)
    lines = capture_pane_lines(session_name, socket_name=sock)
    dialog_open = any(_MODEL_SWITCH_CONFIRM_PATTERN in line for line in lines)
    if dialog_open:
        send_keys_literal(session_name, "Enter", socket_name=sock)


def set_active_model(
    agent_id: str,
    model_name: str,
    *,
    socket_name: str | None = None,
) -> bool:
    """Cambia el modelo activo de un agente en ejecucion.

    Usa contrato de capacidades (T-FB005-US07-01) para verificar que el
    runtime soporta cambio de modelo. Por ahora solo OpenCode lo soporta.

    ## Flujo corregido (T-FB024-US11-13, 2026-08-17) — DOS bugs reales
    ## distintos, ambos reproducidos y verificados contra OpenCode 1.18.18
    ## real antes de corregir (sesiones tmux de prueba aisladas, nunca
    ## contra agentes de producción).

    **Bug 1 — atajo de teclado obsoleto**: el flujo documentado
    originalmente ("Ctrl+P abre el selector de comandos, luego Ctrl+X
    dentro de él") dejó de funcionar: el panel de comandos que abre
    Ctrl+P lista hoy "Switch model — ctrl+x m" como su PROPIO atajo
    global, no anidado dentro de ese panel. Enviar Ctrl+P → Ctrl+X → 'm'
    con Ctrl+P de por medio escribía la 'm' como texto de búsqueda DENTRO
    del panel de comandos general (filtrando la lista, sin ejecutar
    nada). Corregido: Ctrl+X directo (sin Ctrl+P) → 'm'.

    **Bug 2 — cálculo de navegación mezclaba índice de línea de texto con
    número de opciones reales**: tras abrir "Select model" sin filtrar,
    el pane mezcla cabeceras ("Select model", "Search", "Recent"),
    encabezados de sección por PROVEEDOR (p. ej. "OpenCode Zen" aparece
    como su propia línea, indistinguible de un nombre de modelo por
    texto) y las opciones reales — el índice de línea del texto
    capturado NO corresponde al número de pulsaciones de `Down` reales
    desde la posición actual, así que la navegación aterrizaba en un
    modelo distinto al pedido. Corregido: en vez de navegar sobre el
    listado completo sin filtrar, se escribe el nombre del modelo en el
    campo "Search" propio del selector — filtra a solo las opciones
    relevantes (sin cabeceras de proveedor mezcladas) y preselecciona
    automáticamente la primera con '●'. El offset de `Down` se calcula
    SOLO sobre ese listado ya filtrado, buscando la coincidencia EXACTA
    (no solo "contiene") para no quedarse con una variante equivocada
    (p. ej. "DeepSeek V4 Flash **Free**" en vez de "DeepSeek V4 Flash").

    Flujo real confirmado:
    1. Ctrl+X (SIN pasar por Ctrl+P) → atajo global directo.
    2. 'm' (segunda pulsación de la combinación Ctrl+X m) → abre "Select
       model" con el catálogo real, marcando el modelo activo con '●'.
    3. Escribir el nombre del modelo → filtra el listado a las opciones
       relevantes, la primera queda preseleccionada con '●'.
    4. Leer el listado FILTRADO y calcular el offset de `Down` hasta la
       coincidencia exacta (0 si ya es la primera).
    5. Enter para seleccionar.
    6. Verificacion: leer el modelo tras el cambio.

    Cada paso se verifica (captura del pane antes y despues). Si algun
    paso falla, se devuelve `False` sin lanzar excepcion.

    El agente debe estar en ejecucion (sesion tmux viva) y su runtime
    debe soportar cambio de modelo. No modifica el estado del agente
    (sigue `idle`/`working` — aunque T-FB024-US11-11 restringe esto a
    estado idle por seguridad)."""
    rt = get_runtime_instance_for_agent(agent_id)
    if rt is None:
        return False

    # Usar contrato de capacidades en lugar de comprobación ad-hoc
    runtime_type = RuntimeType(rt.runtime.type)
    if not runtime_supports_model_change(runtime_type):
        return False

    session_name = rt.session_name
    sock = socket_name or DEFAULT_SOCKET_NAME

    if not is_alive(session_name, socket_name=sock):
        return False

    # Guardar el modelo previo para comparar al final.
    previous = get_active_model(agent_id, socket_name=sock)

    # Bug real corregido (T-FB024-US11-13, 2026-08-17): un fallo a mitad
    # de camino (offset no encontrado, verificación fallida) dejaba el
    # selector "Select model" abierto con el texto de búsqueda tecleado
    # sin limpiar — el SIGUIENTE intento de cambio de modelo se
    # encontraba ese residuo y fallaba en cascada (reproducido en vivo:
    # el segundo intento abrió "Select variant" con el texto de la
    # búsqueda anterior pegado). Por eso el selector se cierra SIEMPRE
    # con Escape en un `finally`, sea cual sea el resultado — mismo
    # patrón ya usado en `get_active_model_claude_code` para su panel de
    # `/status`.
    selector_opened = False
    try:
        # Paso 1+2: Ctrl+X luego 'm' — combinación directa "Switch model"
        # (NO se pasa por Ctrl+P: ver docstring de la función, el flujo
        # antiguo dejó de funcionar con la CLI actual de OpenCode).
        send_keys_literal(session_name, "C-x", socket_name=sock)
        time.sleep(_STEP_SLEEP_S)
        _send_and_verify_change(session_name, "m", sock, "m (Switch model)")
        selector_opened = True
        time.sleep(2.0)  # esperar que se cargue la lista de modelos en el selector

        # Paso 3: escribir el nombre en el campo Search del propio
        # selector — filtra a solo las opciones relevantes (sin
        # cabeceras de proveedor mezcladas) y preselecciona la primera
        # con '●'. `run_command` no vale aquí (añade Enter, que
        # confirmaría antes de tiempo) — se teclea letra a letra con
        # `send_keys_literal` en modo texto libre.
        send_keys_literal(session_name, model_name, socket_name=sock)
        time.sleep(1.0)  # esperar a que el filtro se aplique

        # Paso 4: leer el listado YA FILTRADO y calcular cuántos `Down`
        # hacen falta desde la primera opción (ya preseleccionada) hasta
        # la coincidencia EXACTA (no basta con "contiene": evita quedarse
        # con una variante como "... Free" en vez del modelo pedido).
        selector_lines = _capture_safe(session_name, sock)
        if selector_lines is None:
            return False
        offset = _find_model_offset_in_filtered_list(selector_lines, model_name)
        if offset is None:
            return False

        for _ in range(offset):
            send_keys_literal(session_name, "Down", socket_name=sock)
            time.sleep(0.1)

        # Paso 5: Enter para seleccionar.
        send_keys_literal(session_name, "Enter", socket_name=sock)
        selector_opened = False  # Enter ya cierra el selector por si mismo
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
        return _model_names_match(current, model_name)

    except Exception:
        return False

    finally:
        if selector_opened:
            try:
                send_keys_literal(session_name, "Escape", socket_name=sock)
            except Exception:
                pass


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


def _find_model_offset_in_filtered_list(lines: list[str], model_name: str) -> int | None:
    """Calcula cuántos `Down` hacen falta desde la primera opción
    (ya preseleccionada tras filtrar por Search) hasta la coincidencia
    EXACTA de `model_name`, sobre el listado YA FILTRADO por el propio
    selector de OpenCode (T-FB024-US11-13, decisión de diseño 2026-08-17:
    contar sobre líneas sin filtrar mezclaba cabeceras de proveedor con
    opciones reales — ver docstring de `set_active_model`).

    Las líneas de opción real, tras escribir en Search, tienen SIEMPRE el
    nombre del modelo seguido del proveedor en la misma línea (con
    espaciado variable) — se identifican por exclusión de las cabeceras
    conocidas ("Select model", "Search", el propio texto tecleado) y de
    líneas vacías/decorativas.

    Devuelve `0` si la primera opción ya es la buscada (caso más común:
    el nombre del catálogo es específico y el filtro deja una sola
    coincidencia). `None` si no se encuentra ninguna coincidencia exacta
    entre las opciones filtradas."""
    if not lines:
        return None

    model_lower = model_name.lower().strip()
    known_headers = {"select model", "search", model_lower}

    option_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower() in known_headers:
            continue
        if stripped.startswith("Connect provider") or stripped.startswith("esc"):
            continue
        option_lines.append(stripped)

    for offset, option in enumerate(option_lines):
        # Coincidencia EXACTA del nombre (no "contiene" — evita quedarse
        # con "DeepSeek V4 Flash Free" en vez de "DeepSeek V4 Flash"
        # cuando ambos empiezan igual). El proveedor va tras varios
        # espacios en la misma línea, así que se hace split por
        # espacios múltiples y se compara solo la primera columna.
        first_column = re.split(r"\s{2,}", option, maxsplit=1)[0].strip()
        if first_column.lower() == model_lower:
            return offset

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


def _normalize_model_text(text: str) -> str:
    """Colapsa guiones/espacios/puntos a un único espacio y baja a
    minúsculas — bug real corregido (T-FB024-US11-13, 2026-08-17): la
    barra de estado de OpenCode puede mostrar el mismo modelo con
    separadores distintos a los del nombre pedido (p. ej. "GLM-5.2" vs
    "GLM 5.2"), y una comparación de subcadena literal sin normalizar
    fallaba aunque el cambio real hubiera funcionado."""
    return re.sub(r"[-_.\s]+", " ", text.lower().strip())


def _model_names_match(current: str, requested: str) -> bool:
    """Comparacion laxa de nombres de modelo — True si `requested` aparece
    como subcadena dentro de `current` (el nombre en la barra de estado de
    OpenCode puede tener texto adicional del proveedor, versiones, etc.),
    tolerando separadores distintos (guion/espacio/punto)."""
    cur = _normalize_model_text(current)
    req = _normalize_model_text(requested)
    if cur == req:
        return True
    if "/" in requested:
        model_part = _normalize_model_text(requested.rsplit("/", 1)[1])
        if model_part in cur:
            return True
    if req in cur:
        return True
    return False

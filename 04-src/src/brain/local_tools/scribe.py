"""Scribe (T-FB014-US01-01, FB-014 Local Tools): catálogo cerrado de
operaciones deterministas ejecutadas por un modelo local (Ollama), sin
tmux ni sesión interactiva — no es un `Agent` en el sentido de FB-005 (ver
`US-FB014-01`). Cada operación es una llamada HTTP síncrona e
independiente, sin estado retenido entre invocaciones.

Cliente HTTP: se usa `requests` (añadida a `04-src/pyproject.toml`, no
estaba declarada — decisión explícita de esta Task, ver T-FB000-01). Se
eligió sobre `httpx` porque Scribe no necesita soporte async ni HTTP/2 —
cada operación es una única llamada síncrona bloqueante, y `requests` es
la opción más simple y con menor superficie para ese caso de uso.

## Degradación explícita (T-FB014-US01-02, criterio de aceptación 5 de
US-FB014-01)

Si Ollama no está corriendo, el modelo configurado no está descargado, o
la respuesta llega con una estructura inesperada, toda operación de
Scribe (`summarize_document`/`index_documents`/`resumir_estado_backlog`)
lanza `ScribeUnavailableError` — nunca una excepción genérica de
`requests` (`ConnectionError`/`Timeout`/`HTTPError`) ni un colgado
indefinido (`timeout_seconds` acota cada llamada HTTP).

**Contrato para quien invoque Scribe** (Developer/Critic hoy de forma
manual; el Dispatcher en US-FB008-03 de forma automática): Scribe es una
ayuda opcional para ahorrar tokens del agente principal (criterio 4 de
US-FB014-01), nunca una dependencia dura. Quien la invoque **debe**
capturar `ScribeUnavailableError` con un `try/except` alrededor de la
llamada y continuar su propio flujo sin el resultado de Scribe (p. ej.
leyendo el documento completo en vez de su resumen) — nunca dejar que
`ScribeUnavailableError` se propague sin capturar y bloquee o tumbe el
resto de Factory Brain. Ver `test_scribe.py`,
`test_caller_can_catch_scribe_unavailable_error_and_continue_without_it`
para el patrón de consumo verificado.
"""

import requests

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5-coder:14b"

# Plantillas de prompt fijas por operación (T-FB014-US01-01, criterio de
# aceptación 3 de US-FB014-01: catálogo cerrado, no prompt libre).
_SUMMARIZE_PROMPT_TEMPLATE = (
    "Resume el siguiente documento de forma breve y fiel, sin añadir "
    "información que no esté en el texto:\n\n{text}"
)
_INDEX_PROMPT_TEMPLATE = (
    "Construye un índice temático a partir de los siguientes documentos, "
    "listando los temas principales de cada uno:\n\n{documents}"
)
_BACKLOG_STATUS_PROMPT_TEMPLATE = (
    "Redacta un resumen breve en prosa del estado de un backlog de "
    "desarrollo, en 3-6 frases, fiel a los datos. Los datos ya están "
    "calculados: no inventes cifras ni identificadores que no aparezcan. "
    "Menciona el total de items, cuántas US y cuántas Tasks hay en cada "
    "estado, cuántas Tasks están LISTAS (listas para empezar) y cuántas "
    "BLOQUEADAS (y por qué dependencia pendiente), y el próximo foco "
    "(la cadena de mayor apalancamiento, raíz y qué desbloquea). "
    "Datos del backlog:\n\n{json_report}"
)


class ScribeUnavailableError(RuntimeError):
    """El modelo local (Ollama) no está disponible — degradación
    explícita: el componente que invocó a Scribe puede continuar sin
    ella, en vez de bloquearse."""


def _unavailable_message(error: requests.RequestException, base_url: str, model: str) -> str:
    """Traduce una `requests.RequestException` a un mensaje con el motivo
    específico (T-FB014-US01-02, criterio de aceptación: "modelo no
    descargado... lanza ScribeUnavailableError con el motivo
    específico"), distinguiendo:
    - sin respuesta HTTP en absoluto (conexión rechazada, timeout): solo
      hay el error de `requests`, no hay cuerpo que inspeccionar;
    - con respuesta HTTP de error (`HTTPError`, p. ej. Ollama devolviendo
      404/500 para un modelo no descargado): se incluye el cuerpo de esa
      respuesta, que suele traer el motivo exacto reportado por Ollama.
    """
    response = getattr(error, "response", None)
    if response is None:
        return (
            f"El modelo local de Scribe no está disponible en '{base_url}' "
            f"(modelo '{model}'): {error}"
        )

    try:
        body = response.json()
    except ValueError:
        body = response.text

    return (
        f"El modelo local de Scribe en '{base_url}' respondió con un error "
        f"(modelo '{model}', HTTP {response.status_code}): {body!r}"
    )


def _chat_completion(
    prompt: str,
    model: str,
    base_url: str,
    timeout_seconds: float,
) -> str:
    """Llamada HTTP directa al endpoint OpenAI-compatible de Ollama
    (`/v1/chat/completions`). Sin sesión persistente: cada llamada abre
    y cierra su propia petición HTTP."""
    url = f"{base_url}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        response = requests.post(url, json=payload, timeout=timeout_seconds)
        response.raise_for_status()
    except requests.RequestException as error:
        raise ScribeUnavailableError(
            _unavailable_message(error, base_url, model)
        ) from error

    data = response.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ScribeUnavailableError(
            f"El modelo local de Scribe en '{base_url}' (modelo '{model}') "
            f"devolvió una respuesta con estructura inesperada (sin "
            f"'choices' o con un formato distinto al esperado): {data!r}"
        ) from error


def summarize_document(
    text: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    timeout_seconds: float = 30.0,
) -> str:
    """Resume `text` usando el modelo local configurado. No acepta un
    prompt arbitrario — la plantilla es fija e interna."""
    prompt = _SUMMARIZE_PROMPT_TEMPLATE.format(text=text)
    return _chat_completion(prompt, model, base_url, timeout_seconds)


def index_documents(
    texts: list[str],
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    timeout_seconds: float = 30.0,
) -> str:
    """Construye un índice temático a partir de `texts` usando el modelo
    local configurado. No acepta un prompt arbitrario — la plantilla es
    fija e interna."""
    documents = "\n\n---\n\n".join(texts)
    prompt = _INDEX_PROMPT_TEMPLATE.format(documents=documents)
    return _chat_completion(prompt, model, base_url, timeout_seconds)


def resumir_estado_backlog(
    resultado_json: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    timeout_seconds: float = 30.0,
) -> str:
    """Redacta un resumen breve en prosa del estado del backlog a partir del
    JSON ya calculado por `build_backlog_report`/`brain backlog-status`
    (T-FB018-US02-02). Scribe NO vuelve a leer ni a parsear los ficheros de
    `02-backlog/`: recibe el JSON como única entrada y solo redacta sobre
    esos datos ya resueltos (criterios de aceptación 1 y 2 de T-FB018-US02-03).
    Capa opcional sobre el cálculo determinista — si el modelo local no está
    disponible, `brain backlog-status` sigue funcionando igual. Plantilla
    fija e interna, como el resto del catálogo."""
    prompt = _BACKLOG_STATUS_PROMPT_TEMPLATE.format(json_report=resultado_json)
    return _chat_completion(prompt, model, base_url, timeout_seconds)

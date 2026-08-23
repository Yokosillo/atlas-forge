"""Mecanismo de disparo automático de Scribe (T-AF008-US03-01, AF-008
Dispatcher v2): decide CUÁNDO invocar a Scribe (AF-014) antes de
despachar un Job, y cómo delimitar su resultado dentro de la instrucción
final del agente. No conecta esto al flujo real de `dispatch_job` — esa
conexión es T-AF008-US03-02 (ver también las notas de diseño de esa Task
sobre de dónde se obtiene el historial de Jobs por agente, todavía sin
decidir). Este módulo deja las tres piezas implementadas y testeadas de
forma aislada.

## Investigación previa que motiva DOS mecanismos, no uno (ver
US-AF008-03, "Contexto")

La evidencia de la industria muestra dos patrones complementarios, no
alternativos: Claude Code real dispara compactación de contexto por
umbral de capacidad de ventana (reactivo, ~83-95% de la ventana), y la
compresión programada periódica (cada 10-15 turnos) logra mejor ahorro
sin degradar precisión (22.7%) que la compresión puramente reactiva
(6%, con degradación). Aplicado a Scribe: un disparo reactivo por
tamaño de un Job individual, y un disparo proactivo por conteo
periódico de Jobs consecutivos con el mismo agente — combinados con OR,
porque resuelven problemas distintos ("este Job trae demasiado
contenido crudo" vs. "la sesión lleva mucho acumulado aunque cada Job
sea pequeño") y ninguno de los dos por separado cubre al otro caso.

## Operación de Scribe elegida para este incremento (criterio de
aceptación de la Task)

Se invoca `summarize_document` (no `index_documents`): ambos mecanismos
de disparo actúan sobre el contenido de UN Job (su `description`) o
sobre el contexto acumulado de una sesión con un agente, que es
justamente "un documento largo que conviene resumir antes de
despachar" — el caso de uso directo de `summarize_document`.
`index_documents` construye un índice temático a partir de VARIOS
documentos distintos, que no es la forma en la que un Job o una sesión
acumulan contenido aquí. Queda `index_documents` disponible en el
catálogo de Scribe para un uso futuro distinto (p. ej. Knowledge Engine,
AF-007), no para este mecanismo de disparo del Dispatcher.
"""

# Umbral de tamaño (criterio de aceptación 1: caso positivo/negativo/
# límite). 4000 caracteres ≈ 800-1000 tokens en inglés/español (ratio
# aproximado de 4-5 caracteres por token) — un Job por debajo de eso cabe
# cómodamente en el contexto de Developer/Critic sin pre-procesar; por
# encima, ya es del orden de una página de documentación técnica o un
# fichero de tamaño medio, el caso concreto que motivó esta Story
# ("contenido largo referenciado en un Job").
DEFAULT_SIZE_THRESHOLD_CHARACTERS = 4000

# Umbral de conteo periódico (criterio de aceptación 2: antes/en/después
# del umbral). 10 Jobs consecutivos con el mismo agente — el extremo
# inferior del rango (10-15 turnos) que la investigación de la industria
# reporta como punto de mejor compromiso ahorro/precisión para
# compresión programada de contexto (ver docstring de módulo); se elige
# el extremo inferior por precaución (disparar antes en vez de después,
# dado que el coste de invocar a Scribe de más es bajo — una llamada
# HTTP local — frente al coste de un agente arrastrando demasiado
# contexto acumulado sin comprimir).
DEFAULT_JOB_COUNT_THRESHOLD = 10

_SCRIBE_SECTION_HEADER = "--- Contexto pre-procesado por Scribe ---"
_SCRIBE_SECTION_FOOTER = "--- Fin del contexto pre-procesado por Scribe ---"


def should_invoke_scribe_by_size(
    content: str, threshold_characters: int = DEFAULT_SIZE_THRESHOLD_CHARACTERS
) -> bool:
    """Disparo reactivo: `True` si `content` (el contenido referenciado
    en `job.description`, o la propia descripción) supera
    `threshold_characters`. Estrictamente mayor que el umbral — un Job
    justo en el límite no dispara todavía (ver test del caso límite)."""
    return len(content) > threshold_characters


def should_invoke_scribe_by_job_count(
    consecutive_job_count: int, threshold: int = DEFAULT_JOB_COUNT_THRESHOLD
) -> bool:
    """Disparo proactivo: `True` si `consecutive_job_count` (número de
    Jobs ya despachados consecutivamente al mismo agente dentro de la
    misma sesión, antes de contar el Job actual) alcanza `threshold`.

    Recibe el conteo ya calculado como `int`, no `(session, agent)` como
    sugería el enunciado de la Task: de dónde se obtiene ese conteo
    (¿un campo nuevo en `DevelopmentSession`? ¿un registro aparte?) es
    una decisión explícitamente diferida a T-AF008-US03-02 ("confirmar
    de dónde se obtiene ese dato... evaluar antes de implementar", ver
    esa Task). Fijar aquí ya una firma que dependa de `DevelopmentSession`
    forzaría esa decisión de fondo antes de tiempo y acoplaría esta
    función (que esta Task pide dejar "testeada de forma aislada") a una
    fuente de datos concreta que todavía no existe. Recibir el conteo ya
    resuelto mantiene esta función pura y trivialmente testeable, y dado
    que un `int` es toda la información que necesita, ninguna decisión de
    -02 sobre dónde se guarda ese conteo cambiará su contrato.
    """
    return consecutive_job_count >= threshold


def should_invoke_scribe(
    content: str,
    consecutive_job_count: int,
    size_threshold_characters: int = DEFAULT_SIZE_THRESHOLD_CHARACTERS,
    job_count_threshold: int = DEFAULT_JOB_COUNT_THRESHOLD,
) -> bool:
    """Combina ambos mecanismos con OR (criterio de aceptación de la
    Task: "si cualquiera de los dos aplica, se dispara Scribe") — ninguno
    de los dos mecanismos sustituye al otro, resuelven problemas
    distintos (ver docstring de módulo)."""
    return should_invoke_scribe_by_size(
        content, size_threshold_characters
    ) or should_invoke_scribe_by_job_count(consecutive_job_count, job_count_threshold)


def compose_job_instruction_with_scribe_context(
    job_description: str, scribe_result: str
) -> str:
    """Compone la instrucción final del Job con el resultado de Scribe en
    una sección delimitada de forma explícita (criterio de aceptación:
    "el agente distingue sin ambigüedad ese contexto pre-procesado de la
    petición original", verificable programáticamente, no solo
    visualmente). La petición original va primero (sin alterar), seguida
    de la sección de Scribe delimitada por cabecera y cierre explícitos —
    mismo principio ya aplicado en `job_creation.create_job` para
    encadenar el resultado de un Job anterior (T-AF008-US02-01), con un
    delimitador distinto y más específico para distinguir ambas fuentes
    de contexto añadido si algún día coexisten en el mismo Job."""
    return (
        f"{job_description}\n\n"
        f"{_SCRIBE_SECTION_HEADER}\n"
        f"{scribe_result}\n"
        f"{_SCRIBE_SECTION_FOOTER}"
    )


def extract_scribe_context(instruction: str) -> str | None:
    """Extrae programáticamente la sección de Scribe de `instruction`
    (compuesta por `compose_job_instruction_with_scribe_context`), o
    `None` si no contiene ninguna. Es lo que hace verificable "el agente
    distingue sin ambigüedad" de forma programática (criterio de
    aceptación), no solo por inspección visual de cabeceras."""
    if _SCRIBE_SECTION_HEADER not in instruction or _SCRIBE_SECTION_FOOTER not in instruction:
        return None

    start = instruction.index(_SCRIBE_SECTION_HEADER) + len(_SCRIBE_SECTION_HEADER)
    end = instruction.index(_SCRIBE_SECTION_FOOTER)
    return instruction[start:end].strip("\n")

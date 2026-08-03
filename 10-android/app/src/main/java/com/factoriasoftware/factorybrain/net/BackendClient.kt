package com.factoriasoftware.factorybrain.net

import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Agente lanzado en la sesión activa (T-FB017-US01-02), reflejo directo
 * del JSON ya devuelto por `GET /agents`/`POST /agents`
 * (`brain.api.routes`) — mismos campos, ninguna interpretación adicional
 * aquí (envoltura fina, sin lógica de dominio en la app).
 */
data class AgentDto(
    val id: String,
    val name: String,
    val role: String,
    val status: String,
    /**
     * Modelo usado por el agente (T-FB017-US01-08), reflejo directo de
     * `model` en `_serialize_agent` (`brain/api/routes.py`): presente solo
     * para agentes sobre OpenCode con modelo indicado en el lanzamiento —
     * `null` para Claude Code (que no admite modelo) o OpenCode sin
     * modelo. Se omite limpiamente en la UI cuando no aplica.
     */
    val model: String? = null,
)

internal data class LaunchAgentRequestDto(
    val role: String,
    val runtime_type: String,
    val model: String?,
    /**
     * Tarea inicial (Job) opcional a despachar justo tras lanzar el agente
     * (T-FB017-US06-01, consume T-FB016-US01-16). `null` si el usuario no
     * escribió nada — Moshi omite los nulos por defecto, así que el campo
     * ni siquiera viaja en el payload (compatibilidad total con el backend
     * actual, que todavía no lo acepta; el despacho real queda bloqueado a
     * T-FB016-US01-16).
     */
    val initial_job_description: String? = null,
)

/**
 * Una combinación disponible de agente + runtime para elegir antes de
 * lanzar (T-FB017-US01-10), reflejo directo del JSON de
 * `GET /agents/options` (`get_agents_options`, `brain/api/routes.py`,
 * envoltura de `list_available_agent_options`, FB-005). Sustituye al
 * catálogo Kotlin hardcodeado que existía antes de `T-FB016-US01-18` — la
 * app y la TUI comparten ahora la misma fuente de verdad en vez de
 * duplicar estos 4 valores en dos lenguajes.
 */
data class AgentLaunchOptionDto(
    val agent_role: String,
    val runtime_type: String,
    val runtime_name: String,
    val supports_model: Boolean,
)

/**
 * Contenido actual del pane de tmux de un agente (T-FB017-US01-08),
 * reflejo directo del JSON de `GET /agents/{agent_id}/pane`
 * (`get_agent_pane`, `brain/api/routes.py`, T-FB016-US01-12): la sesión
 * real del runtime como texto crudo, solo lectura — no una consola
 * interactiva.
 */
data class AgentPaneDto(
    val agent_id: String,
    val content: String,
)

/**
 * Repositorio descubierto en el workspace (T-FB016-US01-11), candidato a
 * proyecto activo — reflejo directo del JSON de `GET /projects`/
 * `GET /project`/`POST /project`.
 */
data class ProjectDto(
    val id: String,
    val name: String,
    val path: String,
    val repository: String,
)

internal data class SelectProjectRequestDto(
    val project_id: String,
)

/**
 * Job despachado a un agente (T-FB017-US01-03), reflejo directo del JSON
 * de `POST /jobs`/`GET /jobs/{id}`/`GET /jobs` (`_serialize_job`,
 * `brain/api/routes.py`) y del evento `job_status` publicado en
 * `WS /ws/jobs` (mismos campos, con `"event": "job_status"` añadido —
 * ver [JobStatusEvent]).
 */
data class JobDto(
    val id: String,
    val session_id: String,
    val agent_id: String,
    val description: String,
    val status: String,
    val result: String?,
)

internal data class CreateJobRequestDto(
    val agent_id: String,
    val description: String,
    val previous_job_id: String?,
)

/**
 * Respuesta de `POST /agents` (T-FB017-US06-01): envoltura del shape que
 * devuelve el endpoint combinado de T-FB016-US01-16 cuando
 * `initial_job_description` viene informado (`{"agent": {...}, "job":
 * {...}}`), reflejo directo del JSON real de `brain.api.routes::post_agents`
 * (agente + Job despachado, o su fallo — el agente queda registrado en
 * cualquier caso). `job` es `null` cuando no se envió tarea inicial (el
 * backend entonces devuelve el `AgentDto` plano de siempre, sin envoltura —
 * ver [BackendClient.launchAgent], que distingue ambos shapes).
 */
data class LaunchAgentResultDto(
    val agent: AgentDto,
    val job: JobDto? = null,
)

/**
 * Un paso del plan propuesto por el Critic (US-FB008-04), reflejo directo
 * de `get_plan_progress` (`brain/dispatcher/job_plan_dispatch.py`) — se
 * muestra tal cual (descripción y mecanismo), sin reformular ni resumir
 * (criterio de aceptación explícito de T-FB017-US01-04).
 */
data class PlanStepDto(
    val description: String,
    val mechanism: String,
    val status: String,
)

/**
 * Progreso completo de un plan (T-FB017-US01-04), reflejo directo del
 * payload de `POST /plans`/`GET /plans/{id}`/`POST /plans/{id}/approve`/
 * `/reject` y del evento `plan_progress` de `WS /ws/plans`.
 * `alreadyDecided` distingue una decisión que esta misma llamada acaba de
 * fijar de una que ya estaba fijada de antes (T-FB016-US01-08,
 * idempotencia) — no es un campo del propio [JobPlan] de dominio, solo
 * existe en la respuesta HTTP.
 */
data class PlanDto(
    val plan_id: String,
    val goal: String,
    val status: String,
    val steps: List<PlanStepDto>,
    val already_decided: Boolean? = null,
)

internal data class CreatePlanRequestDto(
    val goal: String,
)

/**
 * Cuerpo de `POST /scripts/{script_id}/run` (T-FB018-US01-03): `message`
 * es el único parámetro que necesita algún script del catálogo (el
 * genérico `commit`); los particulares y el resto de genéricos se ejecutan
 * sin él. Moshi omite los campos `null`, así que cuando no hay mensaje se
 * envía `{}` y el backend lo trata como ausencia del parámetro.
 */
internal data class RunScriptRequestDto(
    val message: String? = null,
)

/**
 * Script catalogado del proyecto activo (T-FB001-US03-03, T-FB018-US01-03),
 * reflejo directo del JSON de `GET /scripts`. `origin` distingue el
 * catálogo de origen: `"generic"` (scripts genéricos de Factory Brain,
 * T-FB018-US01-01 — `command`/`description` son `null`) o `"particular"`
 * (scripts del manifiesto del proyecto, T-FB001-US03-01).
 */
data class ScriptEntryDto(
    val id: String,
    val name: String,
    val command: String? = null,
    val description: String? = null,
    val origin: String = "particular",
)

/**
 * Resultado de ejecutar un script catalogado (T-FB001-US03-03), reflejo
 * directo del JSON de `POST /scripts/{script_id}/run` — `exitCode` es
 * `null` cuando el script nunca llegó a ejecutarse (id desconocido,
 * manifiesto roto, timeout), no `0` ni ningún valor inventado.
 *
 * T-FB018-US02-04: para `backlog_status`, `data` trae el informe ya
 * parseado (para presentarlo con formato, no como JSON crudo) y `prose`
 * la síntesis opcional en prosa de T-FB018-US02-03 cuando Scribe está
 * disponible. Ambos son `null` para el resto de scripts.
 */
data class ScriptRunResultDto(
    val success: Boolean,
    val exit_code: Int?,
    val stdout: String,
    val stderr: String,
    val error_message: String?,
    val data: BacklogReportDto? = null,
    val prose: String? = null,
)

/**
 * Informe estructurado del estado del backlog (T-FB018-US02-02), reflejo
 * del JSON de `build_backlog_report` — usado tanto por
 * `POST /scripts/backlog_status/run` (campo `data`) como, desde
 * T-FB020-US01-02, directamente por `GET /backlog` (T-FB020-US01-01,
 * mismo dict, lectura directa sin ejecutar el script). Solo se declaran
 * aquí los campos que algún cliente presenta con formato (conteo por
 * Epic, Tasks listas y cadena de mayor apalancamiento) — Moshi ignora
 * cualquier campo del JSON real no declarado (`items_bloqueada`,
 * `errors`, `backlog_path`), sin que eso rompa el parseo.
 */
data class BacklogReportDto(
    val empty: Boolean = true,
    val total: BacklogTotalDto? = null,
    val by_epic: List<BacklogEpicDto> = emptyList(),
    val items_lista: List<BacklogItemSummaryDto> = emptyList(),
    val max_leverage_chain: List<BacklogItemSummaryDto> = emptyList(),
)

data class BacklogTotalDto(
    val items: Int = 0,
    val user_stories: Map<String, Int> = emptyMap(),
    val tasks: Map<String, Int> = emptyMap(),
    val errors: Int = 0,
)

data class BacklogEpicDto(
    val epic: String = "",
    val user_stories: Map<String, Int> = emptyMap(),
    val tasks: Map<String, Int> = emptyMap(),
)

data class BacklogItemSummaryDto(
    val id: String = "",
    val priority: String? = null,
)

/**
 * Estado y detalle de una Epic/User Story/Task del backlog
 * (T-FB020-US01-02, consume `GET /backlog/{item_id}`, T-FB020-US01-01) —
 * un único DTO cubre ambas variantes reales que devuelve el backend
 * (`build_epic_detail`/`build_item_detail`, `brain/backlog/detail.py`):
 * campos de Epic (`kind == "epic"`: `objetivo`, `user_stories`) o de
 * Task/US (`kind == "T"`/`"US"`: `epic`, `state`, `priority`,
 * `dependencies`, `objetivo`, `criterios_aceptacion`, y `tasks` SOLO
 * presente para una US). `parse_warning` es común a ambas variantes —
 * presente solo si el fichero tenía una sección mal formada u opcional
 * ausente (criterio de aceptación explícito de T-FB020-US01-01: nunca
 * rompe la respuesta entera).
 */
data class BacklogItemDetailDto(
    val id: String,
    val kind: String,
    val epic: String? = null,
    val state: String? = null,
    val priority: String? = null,
    val dependencies: List<String> = emptyList(),
    val objetivo: String? = null,
    val criterios_aceptacion: String? = null,
    val user_stories: List<BacklogItemStateDto> = emptyList(),
    val tasks: List<BacklogItemStateDto> = emptyList(),
    val parse_warning: String? = null,
)

/**
 * Referencia mínima a un item del backlog con su estado (id + state) —
 * reflejo de las entradas de `user_stories`/`tasks` en
 * `BacklogItemDetailDto` (`brain/backlog/detail.py::build_epic_detail`/
 * `build_item_detail`), NO el mismo shape que [BacklogItemSummaryDto]
 * (que trae `priority`, no `state` — usado por `items_lista`/
 * `max_leverage_chain` de [BacklogReportDto], un cálculo distinto).
 */
data class BacklogItemStateDto(
    val id: String = "",
    val state: String = "",
)

/**
 * Cuerpo de `POST /backlog/{story_id}/launch-development` (T-FB020-US02-01/
 * T-FB020-US02-02): único campo que el endpoint necesita — el resto del
 * contexto (objetivo, Tasks pendientes) lo resuelve el propio backend.
 */
internal data class LaunchDevelopmentRequestDto(
    val agent_id: String,
)

/**
 * Error de dominio devuelto por el backend (400/404 con `detail`
 * explícito ya construido por `brain.*`, ver `api/routes.py`) — se
 * propaga tal cual a la UI, nunca reformulado (criterio de aceptación
 * explícito de T-FB017-US01-02).
 */
class BackendRequestException(message: String) : Exception(message)

/**
 * Cliente HTTP del backend (T-FB017-US01-01): envoltura fina sobre
 * OkHttp para los endpoints REST de FB-016 — mismo criterio ya aplicado
 * en el cliente Python de la TUI (`brain.tui.backend_client.BackendClient`,
 * T-FB016-US01-06), replicado aquí en Kotlin. Ninguna decisión de dominio
 * vive aquí: esta clase solo construye peticiones HTTP y expone el
 * resultado crudo (o el error), la interpretación de "qué significa un
 * agente idle" vive exclusivamente en el backend.
 *
 * `baseUrl` se recibe como parámetro de cada llamada (no fijo en el
 * constructor) porque es configurable en tiempo de ejecución
 * (`BackendConfig`, criterio de aceptación de esta Task) y puede cambiar
 * mientras la app está viva, sin tener que reconstruir el cliente.
 */
class BackendUnavailableException(message: String, cause: Throwable? = null) :
    Exception(message, cause)

class BackendClient(
    private val httpClient: OkHttpClient = defaultHttpClient(),
) {
    companion object {
        fun defaultHttpClient(): OkHttpClient =
            OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(10, TimeUnit.SECONDS)
                .build()

        private val JSON_MEDIA_TYPE = "application/json".toMediaType()
    }

    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val agentListAdapter =
        moshi.adapter<List<AgentDto>>(Types.newParameterizedType(List::class.java, AgentDto::class.java))
    private val agentAdapter = moshi.adapter(AgentDto::class.java)
    private val launchRequestAdapter = moshi.adapter(LaunchAgentRequestDto::class.java)
    private val launchResultAdapter = moshi.adapter(LaunchAgentResultDto::class.java)
    private val agentOptionListAdapter =
        moshi.adapter<List<AgentLaunchOptionDto>>(
            Types.newParameterizedType(List::class.java, AgentLaunchOptionDto::class.java)
        )
    private val projectListAdapter =
        moshi.adapter<List<ProjectDto>>(Types.newParameterizedType(List::class.java, ProjectDto::class.java))
    private val projectAdapter = moshi.adapter(ProjectDto::class.java)
    private val selectProjectRequestAdapter = moshi.adapter(SelectProjectRequestDto::class.java)
    private val jobAdapter = moshi.adapter(JobDto::class.java)
    private val jobListAdapter =
        moshi.adapter<List<JobDto>>(Types.newParameterizedType(List::class.java, JobDto::class.java))
    private val createJobRequestAdapter = moshi.adapter(CreateJobRequestDto::class.java)
    private val planAdapter = moshi.adapter(PlanDto::class.java)
    private val planListAdapter =
        moshi.adapter<List<PlanDto>>(Types.newParameterizedType(List::class.java, PlanDto::class.java))
    private val createPlanRequestAdapter = moshi.adapter(CreatePlanRequestDto::class.java)
    private val scriptListAdapter =
        moshi.adapter<List<ScriptEntryDto>>(Types.newParameterizedType(List::class.java, ScriptEntryDto::class.java))
    private val scriptRunResultAdapter = moshi.adapter(ScriptRunResultDto::class.java)
    private val runScriptRequestAdapter = moshi.adapter(RunScriptRequestDto::class.java)
    private val agentPaneAdapter = moshi.adapter(AgentPaneDto::class.java)
    private val backlogReportAdapter = moshi.adapter(BacklogReportDto::class.java)
    private val backlogItemDetailAdapter = moshi.adapter(BacklogItemDetailDto::class.java)
    private val launchDevelopmentRequestAdapter = moshi.adapter(LaunchDevelopmentRequestDto::class.java)

    // `POST /jobs` y `POST /plans/{id}/approve` son bloqueantes del lado
    // del backend (la respuesta solo llega cuando el Job/plan entero ya
    // terminó, mismo criterio que `dispatch_job`/`dispatch_plan` ya
    // tienen en dominio) — pueden tardar bastante más que el resto de
    // llamadas REST. Mismo timeout ya usado por el cliente Python de la
    // TUI para `POST /jobs`
    // (`_JOB_DISPATCH_TIMEOUT_SECONDS = 60.0`, `brain/tui/backend_client.py`);
    // aplicado también a `approve` porque despacha una secuencia de Jobs
    // (potencialmente más lenta que uno solo).
    private val longRunningDispatchHttpClient = httpClient.newBuilder()
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    /**
     * `GET /health` (T-FB016-US01-01) — criterio de aceptación de esta
     * Task: "la app muestra el resultado de GET /health correctamente".
     * Devuelve el cuerpo crudo de la respuesta (JSON como texto); el
     * parseo/interpretación vive en la capa de UI, no aquí.
     */
    suspend fun getHealth(baseUrl: String): String = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("$baseUrl/health")
            .get()
            .build()

        try {
            httpClient.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    throw BackendUnavailableException(
                        "El backend respondió ${response.code}: $body"
                    )
                }
                body
            }
        } catch (error: IOException) {
            throw BackendUnavailableException(
                "No se pudo contactar con el backend en '$baseUrl': ${error.message}",
                error,
            )
        }
    }

    /**
     * `GET /agents` (T-FB016-US01-02) — lista vacía si no hay sesión
     * activa (404), mismo criterio ya aplicado en el cliente Python de la
     * TUI (`BackendClient.get_agents`): "sin sesión activa" y "sesión
     * activa sin agentes" se muestran igual en el listado.
     */
    suspend fun getAgents(baseUrl: String): List<AgentDto> = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/agents").get().build()
        executeOrThrow(request, baseUrl, treatNotFoundAsEmpty = true) { response ->
            if (response.code == 404) {
                emptyList()
            } else {
                agentListAdapter.fromJson(response.body!!.string()) ?: emptyList()
            }
        }
    }

    /**
     * `POST /agents` (T-FB016-US01-02) — lanza un agente real. Un rechazo
     * del backend (400/404, combinación inválida o sin sesión/proyecto
     * activo) se propaga como [BackendRequestException] con el mismo
     * `detail` ya construido por el dominio (criterio de aceptación
     * explícito de T-FB017-US01-02: "muestra el motivo real devuelto por
     * la API, no un mensaje genérico").
     *
     * T-FB017-US06-01: `initialJobDescription` opcional. Si viene
     * informado viaja en el payload para el endpoint combinado de
     * T-FB016-US01-16; si es `null`/vacío se omite (Moshi no serializa
     * nulos) y la petición es idéntica a la de antes de esta Task.
     *
     * El tipo de retorno [LaunchAgentResultDto] distingue los dos shapes
     * que el backend puede devolver según si se envió tarea inicial:
     * sin tarea el cuerpo es el `AgentDto` plano de siempre (se envuelve
     * con `job = null`); con tarea el cuerpo es `{"agent": {...}, "job":
     * {...}}` (se parsea con [launchResultAdapter], `job` presente cuando
     * el Job se despachó y ya terminó — `completed`/`failed` — o `null`
     * si el agente se registró pero el Job no llegó a crearse).
     */
    suspend fun launchAgent(
        baseUrl: String,
        role: String,
        runtimeType: String,
        model: String?,
        initialJobDescription: String? = null,
    ): LaunchAgentResultDto =
        withContext(Dispatchers.IO) {
            val body = launchRequestAdapter.toJson(
                LaunchAgentRequestDto(role, runtimeType, model, initialJobDescription)
            ).toRequestBody(JSON_MEDIA_TYPE)
            val request = Request.Builder().url("$baseUrl/agents").post(body).build()
            executeOrThrow(request, baseUrl) { response ->
                if (initialJobDescription.isNullOrBlank()) {
                    LaunchAgentResultDto(
                        agent = agentAdapter.fromJson(response.body!!.string())
                            ?: throw BackendRequestException("Respuesta vacía del backend al lanzar el agente.")
                    )
                } else {
                    launchResultAdapter.fromJson(response.body!!.string())
                        ?: throw BackendRequestException("Respuesta vacía del backend al lanzar el agente con tarea inicial.")
                }
            }
        }

    /**
     * `POST /agents/{agent_id}/stop` (T-FB016-US01-03).
     */
    suspend fun stopAgent(baseUrl: String, agentId: String): AgentDto = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("$baseUrl/agents/$agentId/stop")
            .post("".toRequestBody(null))
            .build()
        executeOrThrow(request, baseUrl) { response ->
            agentAdapter.fromJson(response.body!!.string())
                ?: throw BackendRequestException("Respuesta vacía del backend al detener el agente.")
        }
    }

    /**
     * `GET /agents/{agent_id}/pane` (T-FB017-US01-08) — contenido actual
     * del pane de tmux del agente (T-FB016-US01-12). Un 404 (agente sin
     * sesión tmux viva, p. ej. detenido) se propaga como
     * [BackendRequestException] con el `detail` real del backend.
     */
    suspend fun getAgentPane(baseUrl: String, agentId: String): AgentPaneDto =
        withContext(Dispatchers.IO) {
            val request = Request.Builder()
                .url("$baseUrl/agents/$agentId/pane")
                .get()
                .build()
            executeOrThrow(request, baseUrl) { response ->
                agentPaneAdapter.fromJson(response.body!!.string())
                    ?: throw BackendRequestException("Respuesta vacía del backend al consultar la actividad.")
            }
        }

    /**
     * `GET /agents/options` (T-FB016-US01-18/T-FB017-US01-10) — catálogo
     * de combinaciones agente/runtime/modelo disponibles para lanzar.
     * Información estática sin estado (no depende de sesión activa,
     * mismo criterio que el propio endpoint documenta) — no necesita
     * `treatNotFoundAsEmpty` ni ningún tratamiento especial de 404.
     */
    suspend fun getAgentOptions(baseUrl: String): List<AgentLaunchOptionDto> =
        withContext(Dispatchers.IO) {
            val request = Request.Builder().url("$baseUrl/agents/options").get().build()
            executeOrThrow(request, baseUrl) { response ->
                agentOptionListAdapter.fromJson(response.body!!.string()) ?: emptyList()
            }
        }

    /**
     * `GET /projects` (T-FB016-US01-11) — repositorios descubiertos en el
     * workspace del backend, candidatos a proyecto activo.
     */
    suspend fun getProjects(baseUrl: String): List<ProjectDto> = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/projects").get().build()
        executeOrThrow(request, baseUrl) { response ->
            projectListAdapter.fromJson(response.body!!.string()) ?: emptyList()
        }
    }

    /**
     * `GET /project` (FB-001/T-FB016-US01-02) — proyecto activo actual,
     * o `null` si no hay ninguno seleccionado todavía (404, caso válido:
     * mismo criterio ya aplicado en [getAgents]).
     */
    suspend fun getProject(baseUrl: String): ProjectDto? = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/project").get().build()
        executeOrThrow(request, baseUrl, treatNotFoundAsEmpty = true) { response ->
            if (response.code == 404) null else projectAdapter.fromJson(response.body!!.string())
        }
    }

    /**
     * `POST /project` (T-FB016-US01-11) — selecciona un proyecto de
     * [getProjects] como activo y re-arranca la sesión de desarrollo del
     * backend para él. Un `project_id` que no pertenezca a la lista
     * descubierta se propaga como [BackendRequestException] con el
     * motivo real del dominio (mismo criterio ya aplicado en
     * [launchAgent]).
     */
    suspend fun selectProject(baseUrl: String, projectId: String): ProjectDto =
        withContext(Dispatchers.IO) {
            val body = selectProjectRequestAdapter.toJson(SelectProjectRequestDto(projectId))
                .toRequestBody(JSON_MEDIA_TYPE)
            val request = Request.Builder().url("$baseUrl/project").post(body).build()
            executeOrThrow(request, baseUrl) { response ->
                projectAdapter.fromJson(response.body!!.string())
                    ?: throw BackendRequestException("Respuesta vacía del backend al seleccionar el proyecto.")
            }
        }

    /**
     * `GET /jobs` (T-FB016-US01-04) — histórico de Jobs de la sesión
     * activa. Vacío si no hay sesión activa (404), mismo criterio ya
     * aplicado en [getAgents].
     */
    suspend fun getJobs(baseUrl: String): List<JobDto> = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/jobs").get().build()
        executeOrThrow(request, baseUrl, treatNotFoundAsEmpty = true) { response ->
            if (response.code == 404) {
                emptyList()
            } else {
                jobListAdapter.fromJson(response.body!!.string()) ?: emptyList()
            }
        }
    }

    /**
     * `POST /jobs` (T-FB016-US01-04) — crea y despacha un Job real a
     * `agentId`, encadenando opcionalmente el resultado de un Job previo
     * (`previousJobId`). Bloqueante: la respuesta solo llega cuando el
     * Job ya terminó (`completed`/`failed`) — usa [jobDispatchHttpClient]
     * (timeout extendido, ver su comentario) en vez del cliente por
     * defecto. Un rechazo del backend (400/404) se propaga como
     * [BackendRequestException] con el motivo real, sin reformular.
     */
    suspend fun createAndDispatchJob(
        baseUrl: String,
        agentId: String,
        description: String,
        previousJobId: String?,
    ): JobDto = withContext(Dispatchers.IO) {
        val body = createJobRequestAdapter
            .toJson(CreateJobRequestDto(agentId, description, previousJobId))
            .toRequestBody(JSON_MEDIA_TYPE)
        val request = Request.Builder().url("$baseUrl/jobs").post(body).build()
        executeOrThrow(request, baseUrl, client = longRunningDispatchHttpClient) { response ->
            jobAdapter.fromJson(response.body!!.string())
                ?: throw BackendRequestException("Respuesta vacía del backend al crear el Job.")
        }
    }

    /**
     * `POST /jobs/{job_id}/cancel` (T-FB016-US01-15, T-FB017-US04-05):
     * cancela un Job `running` — el agente involucrado queda `idle`
     * (nunca se mata su sesión tmux). Cliente HTTP por defecto (no el de
     * despacho largo): la propia espera de confirmación del backend ya
     * está acotada a unos segundos
     * (`_CANCEL_CONFIRMATION_TIMEOUT_SECONDS`, `brain/api/routes.py`), no
     * al timeout de despacho completo de `POST /jobs`. 400 (Job no
     * `running`) o 404 (Job inexistente) se propagan como
     * [BackendRequestException] con el motivo real, sin reformular.
     */
    suspend fun cancelJob(baseUrl: String, jobId: String): JobDto = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("$baseUrl/jobs/$jobId/cancel")
            .post("".toRequestBody(null))
            .build()
        executeOrThrow(request, baseUrl) { response ->
            jobAdapter.fromJson(response.body!!.string())
                ?: throw BackendRequestException("Respuesta vacía del backend al cancelar el Job.")
        }
    }

    /**
     * `POST /plans` (T-FB016-US01-05/US-FB008-04) — solicita al Critic un
     * plan de Jobs para la User Story `goal` (p. ej. `"US-FB008-04"`).
     * Se presenta en estado `proposed`, sin despachar nada todavía.
     */
    suspend fun requestPlan(baseUrl: String, goal: String): PlanDto = withContext(Dispatchers.IO) {
        val body = createPlanRequestAdapter.toJson(CreatePlanRequestDto(goal)).toRequestBody(JSON_MEDIA_TYPE)
        val request = Request.Builder().url("$baseUrl/plans").post(body).build()
        executeOrThrow(request, baseUrl) { response ->
            planAdapter.fromJson(response.body!!.string())
                ?: throw BackendRequestException("Respuesta vacía del backend al solicitar el plan.")
        }
    }

    /**
     * `GET /plans/{plan_id}` — progreso actual de un plan ya emitido, sin
     * depender solo del WebSocket (misma simetría que `GET /jobs/{id}`).
     */
    suspend fun getPlan(baseUrl: String, planId: String): PlanDto = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/plans/$planId").get().build()
        executeOrThrow(request, baseUrl) { response ->
            planAdapter.fromJson(response.body!!.string())
                ?: throw BackendRequestException("Respuesta vacía del backend al consultar el plan.")
        }
    }

    /**
     * `GET /plans` (T-FB016-US01-14/T-FB017-US01-09) — todos los planes
     * registrados del proceso, en orden de registro (`list_plans`,
     * `brain/api/plan_registry.py`), cada uno con su estado final o
     * `proposed`. Lo consume `PlanViewModel` al iniciar para recuperar un
     * plan `proposed` pendiente tras reabrir la app.
     */
    suspend fun getPlans(baseUrl: String): List<PlanDto> = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/plans").get().build()
        executeOrThrow(request, baseUrl) { response ->
            planListAdapter.fromJson(response.body!!.string()) ?: emptyList()
        }
    }

    /**
     * `POST /plans/{plan_id}/approve` (T-FB008-US04-02/03) — aprueba el
     * plan completo y despacha su secuencia entera de Jobs, sin
     * aprobación por paso individual (criterio de aceptación explícito
     * de T-FB017-US01-04: "un único tap despacha la secuencia completa").
     * Bloqueante hasta que el despacho entero termina — usa
     * [longRunningDispatchHttpClient]. Idempotente del lado del backend
     * (T-FB016-US01-08): una llamada tras el plan ya decidido devuelve el
     * estado ya fijado (`already_decided = true`), sin re-despachar.
     */
    suspend fun approvePlan(baseUrl: String, planId: String): PlanDto = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("$baseUrl/plans/$planId/approve")
            .post("".toRequestBody(null))
            .build()
        executeOrThrow(request, baseUrl, client = longRunningDispatchHttpClient) { response ->
            planAdapter.fromJson(response.body!!.string())
                ?: throw BackendRequestException("Respuesta vacía del backend al aprobar el plan.")
        }
    }

    /**
     * `POST /plans/{plan_id}/reject` (T-FB008-US04-02) — rechaza el plan
     * completo, sin despachar ningún Job (criterio de aceptación
     * explícito: verificable también desde la app).
     */
    suspend fun rejectPlan(baseUrl: String, planId: String): PlanDto = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("$baseUrl/plans/$planId/reject")
            .post("".toRequestBody(null))
            .build()
        executeOrThrow(request, baseUrl) { response ->
            planAdapter.fromJson(response.body!!.string())
                ?: throw BackendRequestException("Respuesta vacía del backend al rechazar el plan.")
        }
    }

    /**
     * `GET /scripts` (T-FB001-US03-03) — catálogo de scripts particulares
     * del proyecto activo.
     */
    suspend fun getScripts(baseUrl: String): List<ScriptEntryDto> = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/scripts").get().build()
        executeOrThrow(request, baseUrl) { response ->
            scriptListAdapter.fromJson(response.body!!.string()) ?: emptyList()
        }
    }

    /**
     * `POST /scripts/{script_id}/run` (T-FB001-US03-03) — ejecuta un
     * script catalogado y devuelve su resultado estructurado tal cual
     * (éxito, fallo con exit code real, o error sin llegar a ejecutarse —
     * `script_id` desconocido, timeout). A diferencia de [launchAgent]/
     * [createAndDispatchJob], este endpoint nunca devuelve 4xx para esos
     * casos (ver docstring de `post_script_run`, `brain/api/routes.py`):
     * el resultado siempre es 200 con el detalle completo en el cuerpo,
     * así que no hace falta [BackendRequestException] aquí — solo un
     * fallo real de red o de sesión (404 sin proyecto activo, que sí se
     * propaga como excepción). `message` es el parámetro opcional que
     * necesita el genérico `commit` (T-FB018-US01-03); cuando es `null` se
     * envía un body vacío, como antes.
     */
    suspend fun runScript(
        baseUrl: String,
        scriptId: String,
        message: String? = null,
    ): ScriptRunResultDto = withContext(Dispatchers.IO) {
        val body = runScriptRequestAdapter
            .toJson(RunScriptRequestDto(message))
            .toRequestBody(JSON_MEDIA_TYPE)
        val request = Request.Builder()
            .url("$baseUrl/scripts/$scriptId/run")
            .post(body)
            .build()
        executeOrThrow(request, baseUrl, client = longRunningDispatchHttpClient) { response ->
            scriptRunResultAdapter.fromJson(response.body!!.string())
                ?: throw BackendRequestException("Respuesta vacía del backend al ejecutar el script.")
        }
    }

    /**
     * `GET /backlog` (T-FB020-US01-01/T-FB020-US01-02) — informe
     * estructurado del backlog del proyecto activo (conteo por Epic,
     * mismo dict que `POST /scripts/backlog_status/run` ya presentaba en
     * `data`). 404 (sin proyecto activo) se propaga como
     * [BackendRequestException] — a diferencia de [getAgents]/[getJobs],
     * NO es un estado válido "lista vacía": sin proyecto activo no hay
     * nada que listar y la UI debe distinguir ese caso de "proyecto
     * activo con backlog vacío" (`empty = true`, un 200 real).
     */
    suspend fun getBacklog(baseUrl: String): BacklogReportDto = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$baseUrl/backlog").get().build()
        executeOrThrow(request, baseUrl) { response ->
            backlogReportAdapter.fromJson(response.body!!.string())
                ?: throw BackendRequestException("Respuesta vacía del backend al consultar el backlog.")
        }
    }

    /**
     * `GET /backlog/{item_id}` (T-FB020-US01-01/T-FB020-US01-02) —
     * detalle de una Epic (`itemId` con forma `FB-xxx`)/User Story/Task
     * concreta. Un `item_id` inexistente (404, con el motivo real —
     * incluido el de un fallo de parseo, ver `brain/backlog/detail.py`)
     * se propaga como [BackendRequestException], sin tratamiento
     * especial: a diferencia de `GET /backlog`, aquí un 404 siempre es un
     * error real de navegación (el usuario pidió un id que no existe),
     * nunca un estado válido.
     */
    suspend fun getBacklogItem(baseUrl: String, itemId: String): BacklogItemDetailDto =
        withContext(Dispatchers.IO) {
            val request = Request.Builder().url("$baseUrl/backlog/$itemId").get().build()
            executeOrThrow(request, baseUrl) { response ->
                backlogItemDetailAdapter.fromJson(response.body!!.string())
                    ?: throw BackendRequestException("Respuesta vacía del backend al consultar el item de backlog.")
            }
        }

    /**
     * `POST /backlog/{story_id}/launch-development` (T-FB020-US02-01/
     * T-FB020-US02-02) — lanza el desarrollo de la User Story `storyId`
     * con contexto ya resuelto por el backend (objetivo + Tasks `TODO`
     * concatenados en la `description` del Job) y lo despacha al agente
     * `agentId`. Bloqueante como `POST /jobs` (mismo motor de despacho,
     * la respuesta solo llega cuando el Job ya terminó) — usa
     * [longRunningDispatchHttpClient], mismo criterio que
     * [createAndDispatchJob].
     *
     * 400 (User Story sin ninguna Task `TODO`) y 404 (`story_id`
     * inexistente, o `agentId` desconocido) se propagan como
     * [BackendRequestException] con el `detail` REAL del backend — NUNCA
     * reformulado aquí (criterio de aceptación explícito de
     * T-FB020-US02-02: "mostrar el motivo explícito devuelto por el
     * backend, no un error genérico").
     */
    suspend fun launchDevelopment(baseUrl: String, storyId: String, agentId: String): JobDto =
        withContext(Dispatchers.IO) {
            val body = launchDevelopmentRequestAdapter
                .toJson(LaunchDevelopmentRequestDto(agentId))
                .toRequestBody(JSON_MEDIA_TYPE)
            val request = Request.Builder()
                .url("$baseUrl/backlog/$storyId/launch-development")
                .post(body)
                .build()
            executeOrThrow(request, baseUrl, client = longRunningDispatchHttpClient) { response ->
                jobAdapter.fromJson(response.body!!.string())
                    ?: throw BackendRequestException(
                        "Respuesta vacía del backend al lanzar el desarrollo de la User Story."
                    )
            }
        }

    /**
     * Ejecuta la petición y aplica la misma traducción de errores en los
     * métodos anteriores: fallo de red -> [BackendUnavailableException],
     * respuesta 4xx/5xx -> [BackendRequestException] con el `detail` real
     * del backend, sin reformular. `treatNotFoundAsEmpty` es el único caso
     * en que un 404 no se trata como error (usado solo por [getAgents],
     * donde "sin sesión activa" es un estado válido, no un fallo).
     */
    private inline fun <T> executeOrThrow(
        request: Request,
        baseUrl: String,
        treatNotFoundAsEmpty: Boolean = false,
        client: OkHttpClient = httpClient,
        onSuccess: (okhttp3.Response) -> T,
    ): T {
        val response = try {
            client.newCall(request).execute()
        } catch (error: IOException) {
            throw BackendUnavailableException(
                "No se pudo contactar con el backend en '$baseUrl': ${error.message}",
                error,
            )
        }
        return response.use {
            val notFoundIsValid = treatNotFoundAsEmpty && it.code == 404
            if (!it.isSuccessful && !notFoundIsValid) {
                throw BackendRequestException(extractDetail(it))
            }
            onSuccess(it)
        }
    }

    private fun extractDetail(response: okhttp3.Response): String {
        val body = response.body?.string().orEmpty()
        return try {
            val detail = moshi.adapter(Map::class.java).fromJson(body)?.get("detail")
            detail?.toString() ?: body
        } catch (error: Exception) {
            body
        }
    }
}

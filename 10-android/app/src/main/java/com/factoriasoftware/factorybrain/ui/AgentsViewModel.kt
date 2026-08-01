package com.factoriasoftware.factorybrain.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.factoriasoftware.factorybrain.net.AgentDto
import com.factoriasoftware.factorybrain.net.BackendClient
import com.factoriasoftware.factorybrain.net.BackendConfig
import com.factoriasoftware.factorybrain.net.BackendRequestException
import com.factoriasoftware.factorybrain.net.BackendUnavailableException
import com.factoriasoftware.factorybrain.net.JobDto
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Pantalla de agentes (T-FB017-US01-02, criterio de aceptación: "la
 * pantalla muestra los agentes lanzados y su estado, reflejando cambios
 * sin que el usuario tenga que refrescar manualmente").
 *
 * ## Mecanismo de actualización automática: polling ligero, no WebSocket
 *
 * `WS /ws/jobs` (T-FB016-US01-05, `brain/api/app.py`/`routes.py`) solo
 * publica eventos `job_status` — verificado leyendo el propio backend: no
 * existe ningún evento de cambio de estado de agente en ningún canal
 * WebSocket expuesto por FB-016 hoy. La propia Descripción de esta Task
 * ya preveía este caso explícitamente ("vía WS /ws/jobs si el cambio de
 * estado de agente se emite ahí, **o polling ligero si no** — decidir y
 * documentar... según lo que exponga realmente T-FB016-US01-02/03"). Se
 * usa por tanto polling ligero de `GET /agents` cada
 * [POLL_INTERVAL_MILLIS] mientras la pantalla está visible — intervalo
 * corto (no minutos) porque el volumen de datos es pequeño (unos pocos
 * agentes por sesión) y la latencia real de la red Tailscale es baja,
 * mismo criterio de simplicidad ya aplicado en el resto del proyecto
 * (ver `ReconnectingWebSocket`: "backoff fijo simple... sin necesidad
 * real en v1").
 */
sealed interface AgentsUiState {
    data object Loading : AgentsUiState
    data class Loaded(
        val agents: List<AgentDto>,
        val stale: Boolean = false,
        /**
         * `agent.id` de los agentes con un Job `running` en este instante
         * (T-FB017-US04-01, criterio de aceptación: el diálogo de
         * "Detener" debe advertir explícitamente si el agente tiene una
         * tarea en curso). No es un campo nuevo del backend — `GET
         * /agents` no expone esta relación (verificado leyendo
         * `_serialize_agent`, `brain/api/routes.py`: solo
         * `id/name/role/status/runtime_id/model`) y no hacía falta
         * ampliarlo: ya es derivable en el cliente cruzando `GET /jobs`
         * (que sí expone `agent_id` + `status` por Job, T-FB016-US01-04)
         * con la lista de agentes — ver [agentsWithRunningJob].
         */
        val agentsWithRunningJob: Set<String> = emptySet(),
    ) : AgentsUiState
    data class Unavailable(val message: String) : AgentsUiState
}

/**
 * Deriva, a partir del histórico de Jobs de la sesión activa, el conjunto
 * de `agent_id` con un Job actualmente `running` (T-FB017-US04-01) —
 * función pura extraída para poder testearla sin instanciar un
 * `AndroidViewModel`, mismo criterio ya aplicado en
 * `nextStateAfterPollFailure`/`visibleAgentsFor`.
 */
internal fun agentsWithRunningJob(jobs: List<JobDto>): Set<String> =
    jobs.filter { it.status == "running" }.map { it.agent_id }.toSet()

/**
 * Decisión pura de qué [AgentsUiState] nuevo corresponde tras un ciclo de
 * polling fallido — extraída de [AgentsViewModel] para poder testearla
 * sin instanciar un `AndroidViewModel` (que requiere `Application`, no
 * disponible en tests JVM puros sin Robolectric, que este proyecto no
 * usa). Único punto de la regla del criterio de aceptación 5 de la Story:
 * un fallo puntual de un ciclo de polling no borra la última lista de
 * agentes ya vista — solo se transiciona a `Unavailable` si nunca hubo un
 * `Loaded` previo.
 */
internal fun nextStateAfterPollFailure(
    previousState: AgentsUiState,
    errorMessage: String?,
): AgentsUiState =
    if (previousState is AgentsUiState.Loaded) {
        previousState.copy(stale = true)
    } else {
        AgentsUiState.Unavailable(errorMessage ?: "No se pudo contactar con el backend.")
    }

class AgentsViewModel(application: Application) : AndroidViewModel(application) {
    companion object {
        const val POLL_INTERVAL_MILLIS = 3_000L
    }

    private val backendClient = BackendClient()

    private val _uiState = MutableStateFlow<AgentsUiState>(AgentsUiState.Loading)
    val uiState: StateFlow<AgentsUiState> = _uiState.asStateFlow()

    private val _actionMessage = MutableStateFlow<String?>(null)
    val actionMessage: StateFlow<String?> = _actionMessage.asStateFlow()

    // T-FB017-US04-02: evita doble Job/doble agente por doble tap en
    // "Lanzar"/"Detener" mientras la petición anterior sigue en vuelo —
    // `SingleFlightAction` ignora la segunda invocación en vez de
    // encolarla, y `_isLaunching`/`_isStopping` alimentan la UI para
    // deshabilitar el botón correspondiente mientras tanto.
    private val launchGuard = SingleFlightAction()
    private val stopGuard = SingleFlightAction()
    private val _isLaunching = MutableStateFlow(false)
    val isLaunching: StateFlow<Boolean> = _isLaunching.asStateFlow()
    private val _isStopping = MutableStateFlow(false)
    val isStopping: StateFlow<Boolean> = _isStopping.asStateFlow()

    private var baseUrl: String = BackendConfig.DEFAULT_BASE_URL

    init {
        viewModelScope.launch {
            baseUrl = BackendConfig.baseUrlFlow(getApplication()).first()
            while (isActive) {
                refresh()
                delay(POLL_INTERVAL_MILLIS)
            }
        }
    }

    /**
     * Un fallo puntual de un ciclo de polling (corte breve de red,
     * Tailscale reconectando) no debe borrar la última lista de agentes
     * ya vista (criterio de aceptación 5 de la Story, "la app... no
     * pierde el estado ya cargado en pantalla ante un corte de red") —
     * si ya había un [AgentsUiState.Loaded] previo, se conserva esa misma
     * lista marcada `stale = true` (señal visual de "puede estar
     * desactualizado", sin descartarla) en vez de transicionar a
     * [AgentsUiState.Unavailable]. Solo se transiciona a `Unavailable`
     * cuando nunca hubo un `Loaded` previo (primer arranque sin backend
     * disponible) — ahí no hay ninguna lista que conservar.
     */
    private suspend fun refresh() {
        try {
            val agents = backendClient.getAgents(baseUrl)
            // El histórico de Jobs es información secundaria de esta
            // pantalla (T-FB017-US04-01, solo alimenta el aviso del
            // diálogo de "Detener") — un fallo puntual al consultarlo no
            // debe tumbar el refresco de la lista de agentes, que es la
            // información primaria: se degrada a "sin Jobs en curso
            // conocidos" (conjunto vacío) en vez de propagar el error.
            val runningJobAgentIds = try {
                agentsWithRunningJob(backendClient.getJobs(baseUrl))
            } catch (error: BackendUnavailableException) {
                emptySet()
            }
            _uiState.value = AgentsUiState.Loaded(agents, agentsWithRunningJob = runningJobAgentIds)
        } catch (error: BackendUnavailableException) {
            _uiState.value = nextStateAfterPollFailure(_uiState.value, error.message)
        }
    }

    fun launchAgent(role: String, runtimeType: String, model: String?) {
        viewModelScope.launch {
            launchGuard.runExclusive {
                _isLaunching.value = true
                _actionMessage.value = null
                try {
                    val agent = backendClient.launchAgent(baseUrl, role, runtimeType, model)
                    _actionMessage.value = "Agente '${agent.name}' (${agent.role}) operativo, estado: ${agent.status}."
                    refresh()
                } catch (error: BackendUnavailableException) {
                    _actionMessage.value = error.message
                } catch (error: BackendRequestException) {
                    // Motivo real ya construido por el dominio (criterio de
                    // aceptación explícito): se muestra tal cual, sin
                    // reformular.
                    _actionMessage.value = error.message
                } finally {
                    _isLaunching.value = false
                }
            }
        }
    }

    fun stopAgent(agentId: String) {
        viewModelScope.launch {
            stopGuard.runExclusive {
                _isStopping.value = true
                _actionMessage.value = null
                try {
                    val agent = backendClient.stopAgent(baseUrl, agentId)
                    _actionMessage.value = "Agente '${agent.name}' detenido (${agent.status})."
                    refresh()
                } catch (error: BackendUnavailableException) {
                    _actionMessage.value = error.message
                } catch (error: BackendRequestException) {
                    _actionMessage.value = error.message
                } finally {
                    _isStopping.value = false
                }
            }
        }
    }
}

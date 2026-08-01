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
import com.factoriasoftware.factorybrain.net.ReconnectingWebSocket
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Pantalla de Jobs (T-FB017-US01-03): crea y despacha un Job a un agente
 * ya lanzado, muestra su progreso en tiempo real vía `WS /ws/jobs`
 * (T-FB016-US01-05, sin polling manual — criterio de aceptación
 * explícito), y el histórico de la sesión (`GET /jobs`).
 *
 * ## `POST /jobs` es bloqueante, pero la UI no debe congelarse
 *
 * El backend solo responde a `POST /jobs` cuando el Job ya terminó
 * (mismo criterio que `dispatch_job` ya tiene en dominio, ver docstring
 * de `brain/api/routes.py::post_jobs`) — igual que la TUI, que despacha
 * en un worker de hilo aparte (`@work(thread=True)`,
 * `brain/tui/screens/jobs.py`), aquí se lanza en su propia corrutina
 * (`viewModelScope.launch`, que no bloquea el hilo principal de Compose)
 * en paralelo al WebSocket: la petición HTTP evoluciona en background
 * mientras `WS /ws/jobs` entrega los eventos `created`/`completed`/
 * `failed` que ya publica el propio endpoint (`jobs_hub.publish`, antes y
 * después de `dispatch_job`) — el resultado final llega por ambos
 * caminos (la respuesta de `POST /jobs` y el evento WebSocket), pero solo
 * el WebSocket entrega el estado intermedio `created` mientras el Job
 * sigue en curso.
 */
sealed interface JobProgressState {
    data object Idle : JobProgressState
    // `jobId` (T-FB017-US04-05, criterio de aceptación: verificar si el
    // estado de progreso ya expone el id necesario para POST
    // /jobs/{id}/cancel — NO lo exponía hasta esta Task, solo `status`
    // textual) permite al botón "Cancelar" de JobsScreen invocar el
    // endpoint sin tener que rastrear el id por otra vía.
    data class InProgress(val status: String, val jobId: String) : JobProgressState
    data class Finished(val job: JobDto) : JobProgressState
    data class Error(val message: String) : JobProgressState
}

class JobsViewModel(application: Application) : AndroidViewModel(application) {
    private val backendClient = BackendClient()
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val jobStatusEventAdapter = moshi.adapter(JobDto::class.java)

    private val _agents = MutableStateFlow<List<AgentDto>>(emptyList())
    val agents: StateFlow<List<AgentDto>> = _agents.asStateFlow()

    private val _history = MutableStateFlow<List<JobDto>>(emptyList())
    val history: StateFlow<List<JobDto>> = _history.asStateFlow()

    private val _progress = MutableStateFlow<JobProgressState>(JobProgressState.Idle)
    val progress: StateFlow<JobProgressState> = _progress.asStateFlow()

    // T-FB017-US04-02: evita doble Job por doble tap en "Enviar" mientras
    // la petición anterior sigue en vuelo — mismo mecanismo ya aplicado en
    // AgentsViewModel/PlanViewModel. `_progress == InProgress` ya refleja
    // "hay un Job en curso" para la UI, pero el guard es lo que impide de
    // verdad la segunda llamada real al backend (la recomposición de
    // Compose tras el primer `_progress.value = InProgress` no es
    // instantánea respecto al segundo tap).
    private val dispatchGuard = SingleFlightAction()

    private var baseUrl: String = BackendConfig.DEFAULT_BASE_URL
    private var webSocket: ReconnectingWebSocket? = null

    init {
        viewModelScope.launch {
            baseUrl = BackendConfig.baseUrlFlow(getApplication()).first()
            refreshAgents()
            refreshHistory()
            connectWebSocket()
        }
    }

    private fun connectWebSocket() {
        val wsUrl = baseUrl.replaceFirst(Regex("^http"), "ws") + "/ws/jobs"
        val socket = ReconnectingWebSocket(url = wsUrl, scope = viewModelScope)
        webSocket = socket
        viewModelScope.launch {
            socket.events.collect { event ->
                if (event is ReconnectingWebSocket.ConnectionEvent.MessageReceived) {
                    handleJobStatusEvent(event.text)
                }
            }
        }
        socket.start()
    }

    private fun handleJobStatusEvent(rawJson: String) {
        val job = try {
            jobStatusEventAdapter.fromJson(rawJson)
        } catch (error: Exception) {
            null
        } ?: return

        _progress.value = if (
            job.status == "completed" || job.status == "failed" || job.status == "cancelled"
        ) {
            refreshHistory()
            JobProgressState.Finished(job)
        } else {
            JobProgressState.InProgress(job.status, jobId = job.id)
        }
    }

    fun refreshAgents() {
        viewModelScope.launch {
            try {
                _agents.value = backendClient.getAgents(baseUrl)
            } catch (error: BackendUnavailableException) {
                // El estado de progreso ya refleja errores de backend;
                // una lista de agentes vacía por indisponibilidad se
                // maneja igual que "sin agentes lanzados todavía" en la
                // UI (misma pantalla, mensaje distinto no aporta aquí).
            }
        }
    }

    fun refreshHistory() {
        viewModelScope.launch {
            try {
                _history.value = backendClient.getJobs(baseUrl)
            } catch (error: BackendUnavailableException) {
                // Mismo criterio que refreshAgents: no interrumpe el
                // flujo de progreso del Job en curso.
            }
        }
    }

    fun createAndDispatchJob(agentId: String, description: String, previousJobId: String?) {
        viewModelScope.launch {
            dispatchGuard.runExclusive {
                // `jobId` todavía vacío: el Job real ni se ha creado en
                // el backend en este instante. El evento `job_status`
                // real (`created`, publicado por POST /jobs de inmediato,
                // antes de que dispatch_job empiece a esperar) llega vía
                // WebSocket casi al instante y sobrescribe este estado
                // transitorio con el `jobId` verdadero — `JobsScreen`
                // solo habilita "Cancelar" cuando `jobId` no está vacío.
                _progress.value = JobProgressState.InProgress("created", jobId = "")
                try {
                    val job = backendClient.createAndDispatchJob(baseUrl, agentId, description, previousJobId)
                    _progress.value = JobProgressState.Finished(job)
                    refreshHistory()
                } catch (error: BackendUnavailableException) {
                    _progress.value = JobProgressState.Error(error.message ?: "Backend no disponible.")
                } catch (error: BackendRequestException) {
                    _progress.value = JobProgressState.Error(error.message ?: "El backend rechazó el Job.")
                }
            }
        }
    }

    // T-FB017-US04-05: cancelar un Job DISTINTO de detener un agente
    // (AgentsViewModel.stopAgent) — solo interrumpe la espera de ESTE Job
    // concreto, el agente queda `idle` y disponible de inmediato, su
    // sesión tmux no se toca. Guard propio (no dispatchGuard): cancelar
    // es una acción distinta a crear un Job, no deben bloquearse entre sí.
    private val cancelGuard = SingleFlightAction()
    private val _isCancelling = MutableStateFlow(false)
    val isCancelling: StateFlow<Boolean> = _isCancelling.asStateFlow()

    fun cancelJob(jobId: String) {
        viewModelScope.launch {
            cancelGuard.runExclusive {
                _isCancelling.value = true
                try {
                    val job = backendClient.cancelJob(baseUrl, jobId)
                    _progress.value = JobProgressState.Finished(job)
                    refreshHistory()
                } catch (error: BackendUnavailableException) {
                    _progress.value = JobProgressState.Error(error.message ?: "Backend no disponible.")
                } catch (error: BackendRequestException) {
                    _progress.value = JobProgressState.Error(error.message ?: "El backend rechazó la cancelación.")
                } finally {
                    _isCancelling.value = false
                }
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        webSocket?.stop()
    }
}

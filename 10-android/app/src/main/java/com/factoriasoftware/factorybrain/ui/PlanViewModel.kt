package com.factoriasoftware.factorybrain.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.factoriasoftware.factorybrain.net.BackendClient
import com.factoriasoftware.factorybrain.net.BackendConfig
import com.factoriasoftware.factorybrain.net.BackendRequestException
import com.factoriasoftware.factorybrain.net.BackendUnavailableException
import com.factoriasoftware.factorybrain.net.PlanDto
import com.factoriasoftware.factorybrain.net.ReconnectingWebSocket
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Pantalla del plan del Critic (T-FB017-US01-04): solicita un plan para
 * una User Story (`POST /plans`), lo muestra completo antes de cualquier
 * acción, permite aprobar/rechazar con un tap
 * (`POST /plans/{id}/approve`/`/reject`, T-FB008-US04-02/03), y sigue el
 * progreso del despacho vía `WS /ws/plans` (T-FB016-US01-05).
 *
 * ## Filtrado por `plan_id` (hallazgo del crítico en T-FB017-US01-03,
 * aplicado aquí también)
 *
 * `handleJobStatusEvent` en `JobsViewModel` acepta cualquier evento de
 * `/ws/jobs` sin comprobar a qué Job pertenece — anotado como hallazgo no
 * bloqueante allí (un único cliente, un Job a la vez, es el caso
 * cubierto). Aquí el mismo riesgo es más concreto: `WS /ws/plans` puede
 * llevar eventos de MÚLTIPLES planes distintos (cada `POST /plans`
 * registra uno nuevo, sin descartar los anteriores — ver
 * `brain/api/plan_registry.py`), así que sin filtrar, el progreso de un
 * plan ajeno podría sobrescribir el que esta pantalla está mostrando.
 * `handlePlanProgressEvent` descarta cualquier evento cuyo `plan_id` no
 * coincida con el plan actualmente cargado.
 */
sealed interface PlanUiState {
    data object NoPlanRequested : PlanUiState
    data object Loading : PlanUiState
    data class Loaded(val plan: PlanDto) : PlanUiState
    data class Error(val message: String) : PlanUiState
}

/**
 * Plan `proposed` (pendiente de decisión) a recuperar al reabrir la app
 * (T-FB017-US01-09) — función pura extraída para testearla sin instanciar
 * un `AndroidViewModel`, mismo criterio ya aplicado a
 * `agentsWithRunningJob`/`visibleAgentsFor`.
 *
 * `GET /plans` devuelve los planes en orden de registro
 * (`list_plans`, `brain/api/plan_registry.py`), sin purgar los ya
 * decididos — el ÚLTIMO `proposed` de la lista es el MÁS RECIENTE.
 * Criterio explícito ante más de un plan `proposed` (caso límite, no se
 * espera en uso normal): recuperar el más reciente, documentado aquí.
 * `null` si no hay ningún plan pendiente.
 */
internal fun mostRecentPendingPlan(plans: List<PlanDto>): PlanDto? =
    plans.lastOrNull { it.status == "proposed" }

class PlanViewModel(application: Application) : AndroidViewModel(application) {
    private val backendClient = BackendClient()
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val planProgressEventAdapter = moshi.adapter(PlanDto::class.java)

    private val _uiState = MutableStateFlow<PlanUiState>(PlanUiState.NoPlanRequested)
    val uiState: StateFlow<PlanUiState> = _uiState.asStateFlow()

    // T-FB017-US04-02: evita doble aprobación (y por tanto doble despacho
    // de la secuencia completa de Jobs del plan) por doble tap en
    // "Aprobar plan completo" mientras la petición anterior sigue en
    // vuelo — mismo mecanismo ya aplicado en AgentsViewModel.
    private val approveGuard = SingleFlightAction()
    private val _isApproving = MutableStateFlow(false)
    val isApproving: StateFlow<Boolean> = _isApproving.asStateFlow()

    private var baseUrl: String = BackendConfig.DEFAULT_BASE_URL
    private var webSocket: ReconnectingWebSocket? = null
    private var currentPlanId: String? = null

    init {
        viewModelScope.launch {
            baseUrl = BackendConfig.baseUrlFlow(getApplication()).first()
            connectWebSocket()
            // T-FB017-US01-09: recuperar un plan `proposed` pendiente al
            // reabrir la app — `currentPlanId` solo vivía en memoria y si
            // el proceso se mata en segundo plano se perdía la referencia
            // al plan sin decidir. Se consulta `GET /plans` y, si existe,
            // se restaura como plan actual (en vez de partir siempre de
            // cero).
            recoverPendingPlan()
        }
    }

    /**
     * Recupera el plan `proposed` más reciente de la sesión al arrancar
     * (T-FB017-US01-09, `GET /plans`). Si existe, se fija como
     * `currentPlanId` y se muestra; si no hay ninguno, la pantalla se
     * comporta como hoy (estado inicial `NoPlanRequested`).
     *
     * Un fallo de red o del backend en este paso de recuperación es
     * SILENCIOSO (se queda el estado inicial vacío): no debe tumbar ni
     * bloquear la pantalla de Plan en un arranque en frío — el usuario
     * siempre puede solicitar un plan nuevo. Documentado como decisión.
     */
    private suspend fun recoverPendingPlan() {
        try {
            val plans = backendClient.getPlans(baseUrl)
            val pending = mostRecentPendingPlan(plans)
            if (pending != null) {
                currentPlanId = pending.plan_id
                _uiState.value = PlanUiState.Loaded(pending)
            }
        } catch (error: BackendUnavailableException) {
            // Silencioso por diseño (ver docstring de la función).
        } catch (error: BackendRequestException) {
            // Ídem.
        }
    }

    private fun connectWebSocket() {
        val wsUrl = baseUrl.replaceFirst(Regex("^http"), "ws") + "/ws/plans"
        val socket = ReconnectingWebSocket(url = wsUrl, scope = viewModelScope)
        webSocket = socket
        viewModelScope.launch {
            socket.events.collect { event ->
                if (event is ReconnectingWebSocket.ConnectionEvent.MessageReceived) {
                    handlePlanProgressEvent(event.text)
                }
            }
        }
        socket.start()
    }

    private fun handlePlanProgressEvent(rawJson: String) {
        val plan = try {
            planProgressEventAdapter.fromJson(rawJson)
        } catch (error: Exception) {
            null
        } ?: return

        // Descarta eventos de un plan distinto al que esta pantalla
        // tiene cargado — ver docstring de la clase.
        if (plan.plan_id != currentPlanId) return

        _uiState.value = PlanUiState.Loaded(plan)
    }

    fun requestPlan(goal: String) {
        viewModelScope.launch {
            _uiState.value = PlanUiState.Loading
            try {
                val plan = backendClient.requestPlan(baseUrl, goal)
                currentPlanId = plan.plan_id
                _uiState.value = PlanUiState.Loaded(plan)
            } catch (error: BackendUnavailableException) {
                _uiState.value = PlanUiState.Error(error.message ?: "Backend no disponible.")
            } catch (error: BackendRequestException) {
                _uiState.value = PlanUiState.Error(error.message ?: "El backend rechazó la solicitud del plan.")
            }
        }
    }

    fun approvePlan() {
        val planId = currentPlanId ?: return
        viewModelScope.launch {
            approveGuard.runExclusive {
                _isApproving.value = true
                try {
                    val plan = backendClient.approvePlan(baseUrl, planId)
                    _uiState.value = PlanUiState.Loaded(plan)
                } catch (error: BackendUnavailableException) {
                    _uiState.value = PlanUiState.Error(error.message ?: "Backend no disponible.")
                } catch (error: BackendRequestException) {
                    _uiState.value = PlanUiState.Error(error.message ?: "El backend rechazó la aprobación.")
                } finally {
                    _isApproving.value = false
                }
            }
        }
    }

    fun rejectPlan() {
        val planId = currentPlanId ?: return
        viewModelScope.launch {
            try {
                val plan = backendClient.rejectPlan(baseUrl, planId)
                _uiState.value = PlanUiState.Loaded(plan)
            } catch (error: BackendUnavailableException) {
                _uiState.value = PlanUiState.Error(error.message ?: "Backend no disponible.")
            } catch (error: BackendRequestException) {
                _uiState.value = PlanUiState.Error(error.message ?: "El backend rechazó el rechazo del plan.")
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        webSocket?.stop()
    }
}

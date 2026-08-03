package com.factoriasoftware.factorybrain.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.factoriasoftware.factorybrain.net.AgentDto
import com.factoriasoftware.factorybrain.net.BackendClient
import com.factoriasoftware.factorybrain.net.BackendConfig
import com.factoriasoftware.factorybrain.net.BackendRequestException
import com.factoriasoftware.factorybrain.net.BackendUnavailableException
import com.factoriasoftware.factorybrain.net.BacklogEpicDto
import com.factoriasoftware.factorybrain.net.BacklogItemDetailDto
import com.factoriasoftware.factorybrain.net.JobDto
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Pantalla de Backlog (T-FB020-US01-02, consume `GET /backlog`/
 * `GET /backlog/{item_id}` de T-FB020-US01-01): lista de Epics con
 * conteo de sus User Stories por estado; tocar una Epic despliega sus
 * User Stories con el mismo desglose; tocar una User Story navega al
 * detalle (objetivo, criterios de aceptación, Tasks con estado). Ambos
 * niveles de detalle son pantalla-por-nivel (mismo criterio de
 * navegación ya usado en toda la app — un `sealed interface` de estado,
 * sin pila de navegación real: "volver" reconstruye el nivel anterior a
 * partir del estado ya guardado en el ViewModel, no releyendo el
 * backend).
 *
 * La navegación de lectura (Epics/US/Tasks) no necesita guard de
 * doble-tap: pedir dos veces el mismo `GET` en paralelo no tiene ningún
 * efecto observable distinto de pedirlo una vez. `launchDevelopment`
 * (T-FB020-US02-02, `POST /backlog/{story_id}/launch-development`) SÍ es
 * una escritura real (despacha un Job) — usa `SingleFlightAction`, mismo
 * mecanismo ya aplicado en `JobsViewModel.createAndDispatchJob`/
 * `PlanViewModel.approvePlan`.
 */
sealed interface BacklogUiState {
    data object Loading : BacklogUiState
    data class EpicList(val epics: List<BacklogEpicDto>) : BacklogUiState
    data class EpicDetail(val epicId: String, val detail: BacklogItemDetailDto, val epics: List<BacklogEpicDto>) :
        BacklogUiState
    data class ItemDetail(val itemId: String, val detail: BacklogItemDetailDto, val previous: BacklogUiState) :
        BacklogUiState
    data class Unavailable(val message: String) : BacklogUiState
}

/**
 * Identificador de Epic (`FB-xxx`) a partir de la etiqueta libre
 * `**Epic:**` de una US/Task (p. ej. `"FB-020 · Gestión de Backlog
 * (alcance v1)"` -> `"FB-020"`) — función pura extraída para testearla
 * sin backend real, mismo criterio ya aplicado a
 * `mostRecentPendingPlan`/`agentsWithRunningJob`. Replica en Kotlin el
 * mismo criterio que `_EPIC_LABEL_PREFIX_PATTERN` en
 * `brain/backlog/detail.py` (backend): el prefijo `FB-\d{3,}`, no el
 * string completo — distintas Tasks/US de la MISMA Epic real traen
 * sufijos distintos (verificado sobre el backlog real de este proyecto:
 * `FB-008` con 8 variantes), así que la lista de Epics de `GET /backlog`
 * (`by_epic`, agrupada por label completo) necesita este mismo prefijo
 * para poder pedir `GET /backlog/{epicId}` (que sí agrupa por prefijo).
 * `null` si el label no sigue la convención (p. ej. el caso real
 * `"(ninguna — infraestructura de proyecto)"`).
 */
internal fun epicIdFromLabel(epicLabel: String): String? =
    Regex("^(FB-\\d{3,})").find(epicLabel.trim())?.groupValues?.get(1)

/**
 * Estado de "Lanzar desarrollo" (T-FB020-US02-02, `POST
 * /backlog/{story_id}/launch-development`) — propio de esta acción, no
 * mezclado con `BacklogUiState` (la navegación de lectura sigue intacta
 * mientras el lanzamiento está en curso o falla, mismo criterio que
 * `JobProgressState` en `JobsViewModel` es independiente del resto de la
 * pantalla).
 */
sealed interface LaunchDevelopmentState {
    data object Idle : LaunchDevelopmentState
    data object Launching : LaunchDevelopmentState
    data class Finished(val job: JobDto) : LaunchDevelopmentState
    // 400 (sin Tasks `TODO`) y 404 (agente inválido) llegan aquí con el
    // `detail` REAL del backend — criterio de aceptación explícito de la
    // Task: nunca un mensaje genérico.
    data class Error(val message: String) : LaunchDevelopmentState
}

class BacklogViewModel(application: Application) : AndroidViewModel(application) {
    private val backendClient = BackendClient()

    private val _uiState = MutableStateFlow<BacklogUiState>(BacklogUiState.Loading)
    val uiState: StateFlow<BacklogUiState> = _uiState.asStateFlow()

    private val _developerAgents = MutableStateFlow<List<AgentDto>>(emptyList())
    val developerAgents: StateFlow<List<AgentDto>> = _developerAgents.asStateFlow()

    private val _launchDevelopmentState =
        MutableStateFlow<LaunchDevelopmentState>(LaunchDevelopmentState.Idle)
    val launchDevelopmentState: StateFlow<LaunchDevelopmentState> = _launchDevelopmentState.asStateFlow()

    // T-FB020-US02-02, criterio de aceptación explícito: "un doble clic en
    // 'Lanzar desarrollo' no despacha dos Jobs" — mismo mecanismo ya
    // aplicado en `JobsViewModel.createAndDispatchJob`/
    // `PlanViewModel.approvePlan`.
    private val launchDevelopmentGuard = SingleFlightAction()

    private var baseUrl: String = BackendConfig.DEFAULT_BASE_URL

    init {
        viewModelScope.launch {
            baseUrl = BackendConfig.baseUrlFlow(getApplication()).first()
            refresh()
            refreshDeveloperAgents()
        }
    }

    /**
     * Catálogo de agentes Developer disponibles como destinatario de
     * "Lanzar desarrollo" — mismo `GET /agents` que ya consume
     * `JobsViewModel`, filtrado a `role == "developer"` (criterio de
     * aceptación: "elegir el agente Developer destinatario, mismo
     * catálogo/patrón ya usado en AgentsScreen/JobsScreen — no un
     * selector nuevo"). Refrescado al arrancar y cada vez que se abre el
     * detalle de una User Story (ver `openItem`), mismo criterio que
     * `JobsScreen` refresca su lista al entrar a la pantalla.
     */
    fun refreshDeveloperAgents() {
        viewModelScope.launch {
            try {
                _developerAgents.value = backendClient.getAgents(baseUrl).filter { it.role == "developer" }
            } catch (error: BackendUnavailableException) {
                // Mismo criterio que `JobsViewModel.refreshAgents`: un
                // fallo aquí no debe romper la navegación de lectura ya
                // funcionando — el selector simplemente queda vacío.
            }
        }
    }

    /**
     * Recarga la lista de Epics desde cero (`GET /backlog`) — usado tanto
     * al arrancar como al recontextualizar por cambio de proyecto activo
     * (criterio de aceptación explícito de la Task: "cambiar el proyecto
     * activo recarga la vista con los datos del nuevo proyecto, no
     * mezcla datos de ambos" — mismo mecanismo ya aplicado en
     * `ScriptsViewModel.refresh`/`JobsViewModel.refreshHistory`, cableado
     * desde `MainActivity` vía `LaunchedEffect(activeProjectId)`).
     * Vuelve siempre al nivel de lista, descartando cualquier detalle de
     * Epic/item que estuviera abierto del proyecto anterior — nunca
     * conserva ese estado de navegación entre proyectos distintos.
     */
    fun refresh() {
        viewModelScope.launch {
            _uiState.value = BacklogUiState.Loading
            try {
                val report = backendClient.getBacklog(baseUrl)
                _uiState.value = BacklogUiState.EpicList(report.by_epic)
            } catch (error: BackendUnavailableException) {
                _uiState.value = BacklogUiState.Unavailable(
                    error.message ?: "No se pudo contactar con el backend."
                )
            } catch (error: BackendRequestException) {
                // T-FB020-US01-01: 404 real (sin proyecto activo) trae el
                // motivo del propio backend — se muestra tal cual, mismo
                // criterio que el resto de la app (nunca reformulado).
                _uiState.value = BacklogUiState.Unavailable(
                    error.message ?: "El backend rechazó la consulta del backlog."
                )
            }
        }
    }

    /**
     * Abre el detalle de una Epic (`GET /backlog/{epicId}`) — conserva la
     * lista de Epics ya cargada (`epics`) para poder "volver" sin una
     * segunda llamada al backend.
     */
    fun openEpic(epicLabel: String) {
        val epicId = epicIdFromLabel(epicLabel) ?: return
        val currentEpics = (uiState.value as? BacklogUiState.EpicList)?.epics
            ?: (uiState.value as? BacklogUiState.EpicDetail)?.epics
            ?: emptyList()
        viewModelScope.launch {
            _uiState.value = BacklogUiState.Loading
            try {
                val detail = backendClient.getBacklogItem(baseUrl, epicId)
                _uiState.value = BacklogUiState.EpicDetail(epicId, detail, currentEpics)
            } catch (error: BackendUnavailableException) {
                _uiState.value = BacklogUiState.Unavailable(
                    error.message ?: "No se pudo contactar con el backend."
                )
            } catch (error: BackendRequestException) {
                _uiState.value = BacklogUiState.Unavailable(
                    error.message ?: "El backend rechazó la consulta de la Epic."
                )
            }
        }
    }

    /**
     * Abre el detalle de una User Story/Task (`GET /backlog/{itemId}`) —
     * conserva el estado actual (`previous`) para "volver" sin releer el
     * backend (criterio de refresco: nunca sustituye la última lista
     * vista por un error genérico ante un fallo puntual — un fallo aquí
     * dejaría intacto el nivel anterior si el usuario pulsa "volver" en
     * vez de propagarse hacia arriba).
     */
    fun openItem(itemId: String) {
        val previous = uiState.value
        viewModelScope.launch {
            _uiState.value = BacklogUiState.Loading
            try {
                val detail = backendClient.getBacklogItem(baseUrl, itemId)
                _uiState.value = BacklogUiState.ItemDetail(itemId, detail, previous)
                // T-FB020-US02-02: refresca el catálogo de agentes
                // Developer al entrar al detalle — mismo criterio que
                // `JobsScreen` refresca su selector al entrar a la
                // pantalla, para que un agente recién lanzado desde
                // Agentes aparezca sin reiniciar la app.
                refreshDeveloperAgents()
                _launchDevelopmentState.value = LaunchDevelopmentState.Idle
            } catch (error: BackendUnavailableException) {
                _uiState.value = BacklogUiState.Unavailable(
                    error.message ?: "No se pudo contactar con el backend."
                )
            } catch (error: BackendRequestException) {
                _uiState.value = BacklogUiState.Unavailable(
                    error.message ?: "El backend rechazó la consulta del item."
                )
            }
        }
    }

    /**
     * Vuelve al nivel anterior de navegación sin releer el backend
     * (`EpicDetail`/`ItemDetail` ya conservan el estado previo) — desde
     * `EpicList` no hay nivel anterior, no hace nada.
     */
    fun goBack() {
        when (val state = uiState.value) {
            is BacklogUiState.ItemDetail -> _uiState.value = state.previous
            is BacklogUiState.EpicDetail -> _uiState.value = BacklogUiState.EpicList(state.epics)
            else -> {}
        }
    }

    /**
     * Lanza el desarrollo de la User Story `storyId` con el agente
     * Developer `agentId` (T-FB020-US02-02, `POST
     * /backlog/{story_id}/launch-development`) — el backend resuelve el
     * contexto completo (objetivo + Tasks `TODO`), esta función solo
     * despacha. `SingleFlightAction` evita un segundo Job por doble tap
     * (criterio de aceptación explícito). Tras el éxito, el Job despachado
     * ya es consultable en `GET /jobs` (pantalla Jobs) sin ningún cambio
     * adicional aquí — mismo mecanismo que `POST /jobs` normal, criterio
     * de aceptación de T-FB020-US02-01 ("indistinguible de un Job
     * normal").
     */
    fun launchDevelopment(storyId: String, agentId: String) {
        viewModelScope.launch {
            launchDevelopmentGuard.runExclusive {
                _launchDevelopmentState.value = LaunchDevelopmentState.Launching
                try {
                    val job = backendClient.launchDevelopment(baseUrl, storyId, agentId)
                    _launchDevelopmentState.value = LaunchDevelopmentState.Finished(job)
                } catch (error: BackendUnavailableException) {
                    _launchDevelopmentState.value =
                        LaunchDevelopmentState.Error(error.message ?: "Backend no disponible.")
                } catch (error: BackendRequestException) {
                    // Criterio de aceptación explícito: el motivo REAL del
                    // backend (400 sin Tasks TODO, 404 agente inválido),
                    // nunca un mensaje genérico.
                    _launchDevelopmentState.value =
                        LaunchDevelopmentState.Error(error.message ?: "El backend rechazó el lanzamiento.")
                }
            }
        }
    }
}

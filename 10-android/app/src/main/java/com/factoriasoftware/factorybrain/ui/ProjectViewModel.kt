package com.factoriasoftware.factorybrain.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.factoriasoftware.factorybrain.net.AgentDto
import com.factoriasoftware.factorybrain.net.BackendClient
import com.factoriasoftware.factorybrain.net.BackendConfig
import com.factoriasoftware.factorybrain.net.BackendRequestException
import com.factoriasoftware.factorybrain.net.BackendUnavailableException
import com.factoriasoftware.factorybrain.net.ProjectDto
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Pantalla de selección de proyecto (T-FB017-US01-05): lista los
 * repositorios descubiertos (`GET /projects`), muestra cuál es el activo
 * en todo momento (`GET /project`, criterio de aceptación explícito: "no
 * solo en el momento de cambiarlo"), y permite seleccionar uno
 * (`POST /project`, T-FB016-US01-11).
 *
 * ## Aviso de agentes activos antes de cambiar (criterio de aceptación
 * explícito, "mismo criterio de transparencia que T-FB016-US01-11 exige
 * documentar en el backend")
 *
 * El backend ya detiene los agentes de la sesión anterior al cambiar de
 * proyecto (`POST /project`, ver `brain/api/routes.py`) — pero esa acción
 * es irreversible desde el punto de vista del usuario (los procesos tmux
 * reales se paran), así que antes de confirmar el cambio se consulta
 * `GET /agents` del proyecto ACTUAL y, si hay alguno todavía no
 * `stopped`, se muestra un aviso explícito con el conteo antes de
 * proceder — el usuario decide si continuar, en vez de que el cambio de
 * proyecto detenga agentes en marcha sin que nadie lo supiera de
 * antemano.
 */
sealed interface ProjectUiState {
    data object Loading : ProjectUiState
    data class Loaded(val projects: List<ProjectDto>, val activeProject: ProjectDto?) : ProjectUiState
    data class Unavailable(val message: String) : ProjectUiState
}

data class PendingProjectSelection(val project: ProjectDto, val activeAgentsCount: Int)

class ProjectViewModel(application: Application) : AndroidViewModel(application) {
    private val backendClient = BackendClient()

    private val _uiState = MutableStateFlow<ProjectUiState>(ProjectUiState.Loading)
    val uiState: StateFlow<ProjectUiState> = _uiState.asStateFlow()

    private val _actionMessage = MutableStateFlow<String?>(null)
    val actionMessage: StateFlow<String?> = _actionMessage.asStateFlow()

    // Selección pendiente de confirmación tras detectar agentes activos
    // en la sesión actual — `null` cuando no hay ningún aviso mostrado.
    private val _pendingSelection = MutableStateFlow<PendingProjectSelection?>(null)
    val pendingSelection: StateFlow<PendingProjectSelection?> = _pendingSelection.asStateFlow()

    private var baseUrl: String = BackendConfig.DEFAULT_BASE_URL

    init {
        viewModelScope.launch {
            baseUrl = BackendConfig.baseUrlFlow(getApplication()).first()
            refresh()
        }
    }

    fun refresh() {
        viewModelScope.launch {
            try {
                val projects = backendClient.getProjects(baseUrl)
                val activeProject = backendClient.getProject(baseUrl)
                _uiState.value = ProjectUiState.Loaded(projects, activeProject)
            } catch (error: BackendUnavailableException) {
                _uiState.value = ProjectUiState.Unavailable(
                    error.message ?: "No se pudo contactar con el backend."
                )
            }
        }
    }

    /**
     * Primer paso al tocar un proyecto de la lista: consulta si hay
     * agentes activos en la sesión actual. Si los hay, deja la selección
     * en [pendingSelection] para que la UI muestre el aviso y pida
     * confirmación explícita ([confirmPendingSelection]) en vez de
     * cambiar de proyecto directamente.
     */
    fun requestSelectProject(project: ProjectDto) {
        viewModelScope.launch {
            _actionMessage.value = null
            val activeAgents: List<AgentDto> = try {
                backendClient.getAgents(baseUrl)
            } catch (error: BackendUnavailableException) {
                _actionMessage.value = error.message
                return@launch
            }
            val stillRunning = activeAgents.count { it.status != "stopped" }

            if (stillRunning > 0) {
                _pendingSelection.value = PendingProjectSelection(project, stillRunning)
            } else {
                selectProject(project)
            }
        }
    }

    fun confirmPendingSelection() {
        val pending = _pendingSelection.value ?: return
        _pendingSelection.value = null
        selectProject(pending.project)
    }

    fun cancelPendingSelection() {
        _pendingSelection.value = null
    }

    private fun selectProject(project: ProjectDto) {
        viewModelScope.launch {
            try {
                val selected = backendClient.selectProject(baseUrl, project.id)
                _actionMessage.value = "Proyecto activo: '${selected.name}'."
                refresh()
            } catch (error: BackendUnavailableException) {
                _actionMessage.value = error.message
            } catch (error: BackendRequestException) {
                _actionMessage.value = error.message
            }
        }
    }
}

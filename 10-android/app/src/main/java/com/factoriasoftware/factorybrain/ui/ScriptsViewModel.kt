package com.factoriasoftware.factorybrain.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.factoriasoftware.factorybrain.net.BackendClient
import com.factoriasoftware.factorybrain.net.BackendConfig
import com.factoriasoftware.factorybrain.net.BackendUnavailableException
import com.factoriasoftware.factorybrain.net.ScriptEntryDto
import com.factoriasoftware.factorybrain.net.ScriptRunResultDto
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Pantalla de Scripts (T-FB001-US03-03): lista los scripts particulares
 * catalogados del proyecto activo (`GET /scripts`) y permite ejecutar uno
 * (`POST /scripts/{id}/run`), viendo su resultado sin teclear el comando
 * manualmente — sin WebSocket (a diferencia de Jobs/Plan): el endpoint no
 * publica ningún evento de progreso intermedio, es una llamada bloqueante
 * simple que devuelve el resultado completo de una vez (mismo criterio ya
 * documentado en `post_script_run`, `brain/api/routes.py`).
 */
sealed interface ScriptsUiState {
    data object Loading : ScriptsUiState
    data class Loaded(val scripts: List<ScriptEntryDto>) : ScriptsUiState
    data class Unavailable(val message: String) : ScriptsUiState
}

sealed interface ScriptRunState {
    data object Idle : ScriptRunState
    data object Running : ScriptRunState
    data class Finished(val scriptId: String, val result: ScriptRunResultDto) : ScriptRunState
    data class Error(val message: String) : ScriptRunState
}

class ScriptsViewModel(application: Application) : AndroidViewModel(application) {
    private val backendClient = BackendClient()

    private val _uiState = MutableStateFlow<ScriptsUiState>(ScriptsUiState.Loading)
    val uiState: StateFlow<ScriptsUiState> = _uiState.asStateFlow()

    private val _runState = MutableStateFlow<ScriptRunState>(ScriptRunState.Idle)
    val runState: StateFlow<ScriptRunState> = _runState.asStateFlow()

    // T-FB017-US04-02: evita ejecutar el mismo script dos veces por doble
    // tap en "Ejecutar" mientras la petición anterior sigue en vuelo —
    // mismo mecanismo ya aplicado en el resto de ViewModels de esta Task.
    private val runGuard = SingleFlightAction()

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
                _uiState.value = ScriptsUiState.Loaded(backendClient.getScripts(baseUrl))
            } catch (error: BackendUnavailableException) {
                _uiState.value = ScriptsUiState.Unavailable(
                    error.message ?: "No se pudo contactar con el backend."
                )
            }
        }
    }

    fun runScript(scriptId: String, message: String? = null) {
        viewModelScope.launch {
            runGuard.runExclusive {
                _runState.value = ScriptRunState.Running
                try {
                    val result = backendClient.runScript(baseUrl, scriptId, message)
                    _runState.value = ScriptRunState.Finished(scriptId, result)
                } catch (error: BackendUnavailableException) {
                    _runState.value = ScriptRunState.Error(error.message ?: "Backend no disponible.")
                }
            }
        }
    }
}

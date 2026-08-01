package com.factoriasoftware.factorybrain.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.factoriasoftware.factorybrain.net.BackendClient
import com.factoriasoftware.factorybrain.net.BackendConfig
import com.factoriasoftware.factorybrain.net.BackendUnavailableException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Pantalla mínima de verificación (T-FB017-US01-01, criterio de
 * aceptación explícito): confirma que la app puede hablar con el backend
 * real llamando a `GET /health` (T-FB016-US01-01) — ninguna decisión de
 * dominio aquí, solo mostrar el resultado crudo de esa llamada.
 */
sealed interface HealthCheckState {
    data object Idle : HealthCheckState
    data object Loading : HealthCheckState
    data class Success(val body: String) : HealthCheckState
    data class Failure(val message: String) : HealthCheckState
}

class HealthCheckViewModel(application: Application) : AndroidViewModel(application) {
    private val backendClient = BackendClient()

    private val _state = MutableStateFlow<HealthCheckState>(HealthCheckState.Idle)
    val state: StateFlow<HealthCheckState> = _state.asStateFlow()

    private val _baseUrl = MutableStateFlow(BackendConfig.DEFAULT_BASE_URL)
    val baseUrl: StateFlow<String> = _baseUrl.asStateFlow()

    init {
        viewModelScope.launch {
            _baseUrl.value = BackendConfig.baseUrlFlow(getApplication()).first()
            checkHealth()
        }
    }

    fun updateBaseUrl(newBaseUrl: String) {
        viewModelScope.launch {
            BackendConfig.setBaseUrl(getApplication(), newBaseUrl)
            _baseUrl.value = newBaseUrl.trimEnd('/')
        }
    }

    fun checkHealth() {
        viewModelScope.launch {
            _state.value = HealthCheckState.Loading
            _state.value = try {
                HealthCheckState.Success(backendClient.getHealth(_baseUrl.value))
            } catch (error: BackendUnavailableException) {
                HealthCheckState.Failure(error.message ?: "Error desconocido")
            }
        }
    }
}

package com.factoriasoftware.factorybrain.net

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/**
 * Configuración del host del backend (T-FB017-US01-01, criterio de
 * aceptación explícito de la Task: "la URL del backend es configurable
 * desde la propia app, sin recompilar"). Persistida con DataStore
 * (reemplazo recomendado por Android de SharedPreferences) en vez de
 * hardcodeada en el código o en un recurso de compilación — el host real
 * (100.86.252.40:8000, el backend systemd de T-FB016-US01-09) es el valor
 * por defecto, pero cualquier host Tailscale distinto debe poder
 * configurarse sin recompilar el APK (p. ej. si la VM cambia de IP
 * Tailscale, o para apuntar a un backend de desarrollo).
 */
private val Context.dataStore by preferencesDataStore(name = "factory_brain_settings")

object BackendConfig {
    // Backend real desplegado (T-FB016-US01-09, verificado en esa Task:
    // `sudo ss -tlnp` confirmó el socket escuchando en esta IP Tailscale,
    // puerto por defecto de `brain-api`, T-FB016-US01-01) — valor inicial,
    // no fijo: el usuario puede cambiarlo desde la pantalla de ajustes sin
    // recompilar.
    const val DEFAULT_BASE_URL = "http://100.86.252.40:8000"

    private val BASE_URL_KEY = stringPreferencesKey("backend_base_url")

    fun baseUrlFlow(context: Context): Flow<String> =
        context.dataStore.data.map { preferences ->
            preferences[BASE_URL_KEY] ?: DEFAULT_BASE_URL
        }

    suspend fun setBaseUrl(context: Context, baseUrl: String) {
        context.dataStore.edit { preferences ->
            preferences[BASE_URL_KEY] = baseUrl.trimEnd('/')
        }
    }
}

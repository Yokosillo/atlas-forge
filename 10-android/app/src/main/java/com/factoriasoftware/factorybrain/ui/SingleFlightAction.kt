package com.factoriasoftware.factorybrain.ui

import kotlinx.coroutines.sync.Mutex

/**
 * Envuelve una operación `suspend` (T-FB017-US04-02) garantizando que una
 * segunda invocación mientras la primera sigue en vuelo se ignora en vez
 * de disparar una segunda llamada real al backend — el guard para el
 * "doble tap" que motiva esta Task (doble Job, doble aprobación de plan).
 *
 * `Mutex.tryLock()` (no `lock()`/`withLock`, que esperarían) es la
 * primitiva correcta: la segunda invocación no debe bloquearse hasta que
 * la primera termine, debe descartarse de inmediato — el usuario ya
 * recibe feedback visual (botón deshabilitado) de que hay una operación
 * en curso, un segundo tap mientras tanto no debería encolar nada.
 *
 * Extraída como clase propia (en vez de un `Boolean` mutable ad-hoc por
 * `ViewModel`) para poder testearla de forma aislada con corrutinas
 * reales, sin necesitar un `AndroidViewModel` (que exige `Application`,
 * no disponible en tests JVM puros sin Robolectric — mismo motivo por el
 * que `nextStateAfterPollFailure`/`visibleAgentsFor`/`agentsWithRunningJob`
 * ya viven fuera del `ViewModel`).
 */
class SingleFlightAction {
    private val mutex = Mutex()

    /**
     * Ejecuta `block` si no hay ninguna ejecución en curso; si ya la hay,
     * no hace nada y devuelve `false` sin invocar `block`. Devuelve `true`
     * si `block` se ejecutó (haya terminado en éxito o con excepción — el
     * guard se libera siempre en un `finally`, nunca queda "atascado" tras
     * un fallo, criterio de aceptación explícito de la Task).
     */
    suspend fun runExclusive(block: suspend () -> Unit): Boolean {
        if (!mutex.tryLock()) return false
        try {
            block()
        } finally {
            mutex.unlock()
        }
        return true
    }

    val isRunning: Boolean
        get() = mutex.isLocked
}

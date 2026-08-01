package com.factoriasoftware.factorybrain

import com.factoriasoftware.factorybrain.ui.SingleFlightAction
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Verifica `SingleFlightAction` (T-FB017-US04-02), el guard que evita
 * doble Job/doble aprobación de plan/doble ejecución de script por doble
 * tap: dos corrutinas reales concurrentes (no un mock de la propia
 * primitiva de concurrencia) compiten por `runExclusive` mientras la
 * primera está "en vuelo" (un `delay` real simula la latencia de una
 * llamada HTTP bloqueante, mismo criterio de "comportamiento real, no
 * simulado" ya aplicado en `BackendClientTest` con `MockWebServer`) —
 * exactamente el escenario de "pulsar dos veces seguidas antes de que la
 * primera petición responda" del criterio de aceptación de la Task.
 *
 * No se testean los `AndroidViewModel` directamente (`AgentsViewModel`,
 * `JobsViewModel`, `PlanViewModel`, `ScriptsViewModel`) porque requieren
 * `Application`, no disponible en tests JVM puros sin Robolectric (que
 * este proyecto no usa) — por eso el guard se extrajo como clase propia,
 * mismo criterio ya aplicado a `nextStateAfterPollFailure`/
 * `visibleAgentsFor`/`agentsWithRunningJob`.
 */
class SingleFlightActionTest {
    @Test
    fun `a second invocation while the first is still in flight does not run the block`() = runBlocking {
        val guard = SingleFlightAction()
        val callCount = AtomicInteger(0)
        val firstStarted = AtomicInteger(0)

        val first = async {
            guard.runExclusive {
                firstStarted.incrementAndGet()
                callCount.incrementAndGet()
                delay(200) // Simula una llamada HTTP bloqueante real en vuelo.
            }
        }

        // Espera activa breve a que la primera corrutina haya entrado de
        // verdad en el bloque protegido (evita una condición de carrera
        // contra el arranque de `first`, sin depender de temporización
        // fija para el propio comportamiento verificado).
        while (firstStarted.get() == 0) {
            delay(1)
        }

        // Segundo "tap" mientras el primero sigue en `delay` — debe
        // descartarse sin ejecutar el bloque ni incrementar callCount.
        val secondRan = guard.runExclusive { callCount.incrementAndGet() }

        assertFalse("La segunda invocación no debía ejecutar el bloque", secondRan)
        assertEquals("Solo una llamada real al bloque protegido", 1, callCount.get())

        val firstRan = first.await()
        assertTrue("La primera invocación sí debía ejecutar el bloque", firstRan)
        assertEquals(1, callCount.get())
    }

    @Test
    fun `a second invocation after the first one finishes runs normally`() = runBlocking {
        val guard = SingleFlightAction()
        val callCount = AtomicInteger(0)

        val firstRan = guard.runExclusive { callCount.incrementAndGet() }
        val secondRan = guard.runExclusive { callCount.incrementAndGet() }

        assertTrue(firstRan)
        assertTrue(secondRan)
        assertEquals(2, callCount.get())
    }

    @Test
    fun `the guard is released even if the block throws, so a later call can run`() = runBlocking {
        val guard = SingleFlightAction()

        try {
            guard.runExclusive { throw RuntimeException("fallo simulado de la llamada al backend") }
        } catch (error: RuntimeException) {
            // Esperado: el guard no debe tragarse la excepción del bloque.
        }

        assertFalse("El guard no debe quedar bloqueado tras un fallo", guard.isRunning)

        val ranAfterFailure = guard.runExclusive { /* no-op */ }
        assertTrue("Una llamada posterior al fallo debe poder ejecutarse", ranAfterFailure)
    }

    @Test
    fun `isRunning reflects whether a block is currently executing`() = runBlocking {
        val guard = SingleFlightAction()
        val started = AtomicInteger(0)

        assertFalse(guard.isRunning)

        val job = async {
            guard.runExclusive {
                started.incrementAndGet()
                delay(100)
            }
        }

        while (started.get() == 0) {
            delay(1)
        }
        assertTrue(guard.isRunning)

        job.await()
        assertFalse(guard.isRunning)
    }
}

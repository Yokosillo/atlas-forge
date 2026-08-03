package com.factoriasoftware.factorybrain

import com.factoriasoftware.factorybrain.net.AgentDto
import com.factoriasoftware.factorybrain.net.JobDto
import com.factoriasoftware.factorybrain.ui.launchFeedbackMessageFor
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Verifica el reflejo del Job inicial despachado en el mensaje de feedback
 * tras lanzar un agente (T-FB017-US06-01, punto 3) a través de
 * `launchFeedbackMessageFor`, función pura extraída de `AgentsViewModel`
 * (mismo criterio que `nextStateAfterPollFailure`/`agentsWithRunningJob`:
 * un `AndroidViewModel` exige `Application`, no disponible en tests JVM
 * puros sin Robolectric).
 *
 * Decisión documentada del mecanismo: un mensaje breve en
 * `_actionMessage` (el mismo canal de feedback del éxito/fallo de
 * lanzamiento y detención), no navegación programática — la navegación
 * por pestañas vive en `MainActivity` y ningún ViewModel la toca, y el
 * Job llega igualmente a la lista de Jobs vía el WebSocket `WS /jobs`
 * existente. El mensaje nunca bloquea el flujo: el agente ya quedó
 * registrado y el mensaje lo reitera incluso cuando el Job inicial falló.
 */
class LaunchAgentFeedbackTest {
    private val agent = AgentDto(id = "a1", name = "Developer", role = "developer", status = "idle")

    @Test
    fun `without a job the message is the regular agent success message`() {
        val message = launchFeedbackMessageFor(agent, null)

        assertEquals("Agente 'Developer' (developer) operativo, estado: idle.", message)
    }

    @Test
    fun `with a completed job the message reports the dispatched task without hiding the agent`() {
        val job = JobDto(
            id = "j1",
            session_id = "s1",
            agent_id = "a1",
            description = "Analizar el modelo de dominio",
            status = "completed",
            result = "hecho",
        )

        val message = launchFeedbackMessageFor(agent, job)

        assertTrue(message.contains("Agente 'Developer' (developer) operativo"))
        assertTrue(message.contains("Tarea inicial despachada y completada"))
    }

    @Test
    fun `with a failed job the message reports the failure but keeps the agent registered and visible`() {
        val job = JobDto(
            id = "j2",
            session_id = "s1",
            agent_id = "a1",
            description = "hacer X",
            status = "failed",
            result = "El agente no tiene la herramienta necesaria",
        )

        val message = launchFeedbackMessageFor(agent, job)

        assertTrue(message.contains("La tarea inicial falló: El agente no tiene la herramienta necesaria"))
        assertTrue(message.contains("El agente queda registrado y disponible"))
        assertTrue(message.contains("estado: idle"))
    }

    @Test
    fun `a failed job without a result falls back to a generic detail instead of a crash`() {
        val job = JobDto(
            id = "j3",
            session_id = "s1",
            agent_id = "a1",
            description = "hacer Y",
            status = "failed",
            result = null,
        )

        val message = launchFeedbackMessageFor(agent, job)

        assertTrue(message.contains("La tarea inicial falló: sin detalle"))
        assertTrue(message.contains("El agente queda registrado y disponible"))
    }

    @Test
    fun `an unexpected job status is reported as-is without blocking the agent message`() {
        val job = JobDto(
            id = "j4",
            session_id = "s1",
            agent_id = "a1",
            description = "hacer Z",
            status = "running",
            result = null,
        )

        val message = launchFeedbackMessageFor(agent, job)

        assertTrue(message.contains("Agente 'Developer' (developer) operativo"))
        assertTrue(message.contains("estado 'running'"))
    }
}

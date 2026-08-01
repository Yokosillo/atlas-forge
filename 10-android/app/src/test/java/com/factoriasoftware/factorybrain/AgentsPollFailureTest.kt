package com.factoriasoftware.factorybrain

import com.factoriasoftware.factorybrain.net.AgentDto
import com.factoriasoftware.factorybrain.ui.AgentsUiState
import com.factoriasoftware.factorybrain.ui.nextStateAfterPollFailure
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Verifica el criterio de aceptación 5 de US-FB017-01 ("la app... no
 * pierde el estado ya cargado en pantalla ante un corte de red") tal como
 * se aplica a `AgentsViewModel`: un fallo puntual de un ciclo de polling
 * no debe borrar la última lista de agentes ya vista. `AgentsViewModel`
 * es un `AndroidViewModel` (requiere `Application`, no disponible en
 * tests JVM puros sin Robolectric, que este proyecto no usa) — la
 * decisión de transición se extrajo a `nextStateAfterPollFailure`, una
 * función pura, precisamente para poder testearla directamente.
 */
class AgentsPollFailureTest {
    private val someAgents = listOf(AgentDto(id = "a1", name = "Developer", role = "developer", status = "idle"))

    @Test
    fun `a poll failure after a previous Loaded state keeps the same agents, marked stale`() {
        val previousState: AgentsUiState = AgentsUiState.Loaded(someAgents)

        val nextState = nextStateAfterPollFailure(previousState, "backend no disponible")

        assertTrue(nextState is AgentsUiState.Loaded)
        val loaded = nextState as AgentsUiState.Loaded
        assertEquals(someAgents, loaded.agents)
        assertTrue(loaded.stale)
    }

    @Test
    fun `a poll failure with no previous Loaded state transitions to Unavailable`() {
        val previousState: AgentsUiState = AgentsUiState.Loading

        val nextState = nextStateAfterPollFailure(previousState, "backend no disponible")

        assertTrue(nextState is AgentsUiState.Unavailable)
        assertEquals("backend no disponible", (nextState as AgentsUiState.Unavailable).message)
    }

    @Test
    fun `a poll failure after an already-stale Loaded state keeps it stale (idempotent)`() {
        val previousState: AgentsUiState = AgentsUiState.Loaded(someAgents, stale = true)

        val nextState = nextStateAfterPollFailure(previousState, "backend no disponible")

        assertTrue(nextState is AgentsUiState.Loaded)
        val loaded = nextState as AgentsUiState.Loaded
        assertEquals(someAgents, loaded.agents)
        assertTrue(loaded.stale)
    }
}

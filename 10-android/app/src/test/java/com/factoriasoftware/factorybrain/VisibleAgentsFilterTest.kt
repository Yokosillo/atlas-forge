package com.factoriasoftware.factorybrain

import com.factoriasoftware.factorybrain.net.AgentDto
import com.factoriasoftware.factorybrain.ui.visibleAgentsFor
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Verifica el filtro de agentes `stopped` de T-FB017-US01-07: con
 * `showStopped = false` (por defecto en la pantalla), los agentes
 * `stopped` no aparecen en la lista; con `true`, se muestran todos.
 * `AgentsScreen` es un `@Composable` (no testeable sin instrumentación en
 * este proyecto, que no usa Robolectric) — la decisión de filtrado se
 * extrajo a `visibleAgentsFor`, una función pura, precisamente para poder
 * verificarla directamente.
 */
class VisibleAgentsFilterTest {
    private val idleAgent = AgentDto(id = "a1", name = "Developer-1", role = "developer", status = "idle")
    private val workingAgent = AgentDto(id = "a2", name = "Developer-2", role = "developer", status = "working")
    private val stoppedAgent = AgentDto(id = "a3", name = "Developer-3", role = "developer", status = "stopped")
    private val unavailableAgent = AgentDto(id = "a4", name = "Critic", role = "critic", status = "unavailable")

    @Test
    fun `with showStopped false, stopped agents are excluded from the list`() {
        val agents = listOf(idleAgent, workingAgent, stoppedAgent, unavailableAgent)

        val visible = visibleAgentsFor(agents, showStopped = false)

        assertEquals(listOf(idleAgent, workingAgent, unavailableAgent), visible)
    }

    @Test
    fun `with showStopped true, all agents including stopped are shown`() {
        val agents = listOf(idleAgent, workingAgent, stoppedAgent, unavailableAgent)

        val visible = visibleAgentsFor(agents, showStopped = true)

        assertEquals(agents, visible)
    }

    @Test
    fun `a list with no stopped agents is unaffected by the filter either way`() {
        val agents = listOf(idleAgent, workingAgent)

        assertEquals(agents, visibleAgentsFor(agents, showStopped = false))
        assertEquals(agents, visibleAgentsFor(agents, showStopped = true))
    }

    @Test
    fun `a list of only stopped agents becomes empty when hidden`() {
        val agents = listOf(stoppedAgent)

        assertEquals(emptyList<AgentDto>(), visibleAgentsFor(agents, showStopped = false))
        assertEquals(agents, visibleAgentsFor(agents, showStopped = true))
    }
}

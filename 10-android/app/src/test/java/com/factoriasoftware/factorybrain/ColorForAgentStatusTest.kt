package com.factoriasoftware.factorybrain

import com.factoriasoftware.factorybrain.ui.colorForAgentStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

/**
 * Verifica `colorForAgentStatus` (T-FB017-US04-05): un color asociado a
 * cada `agent.status`, complementario al texto de estado (nunca su
 * sustituto — eso se verifica en el propio Composable, no aquí, este test
 * cubre solo la función pura de mapeo).
 */
class ColorForAgentStatusTest {
    @Test
    fun `each known status maps to its own distinct color`() {
        val idle = colorForAgentStatus("idle")
        val working = colorForAgentStatus("working")
        val stopped = colorForAgentStatus("stopped")
        val unavailable = colorForAgentStatus("unavailable")

        val colors = listOf(idle, working, stopped, unavailable)
        assertEquals("Los 4 estados conocidos deben tener colores distintos entre sí", 4, colors.toSet().size)
    }

    @Test
    fun `the same status always maps to the same color`() {
        assertEquals(colorForAgentStatus("idle"), colorForAgentStatus("idle"))
        assertEquals(colorForAgentStatus("working"), colorForAgentStatus("working"))
    }

    @Test
    fun `an unknown status does not crash and falls back to the stopped color`() {
        // No debería ocurrir con el dominio actual, pero un `when` no
        // exhaustivo ante una futura ampliación del backend no debe
        // lanzar — cae al mismo gris neutro que `stopped`.
        assertEquals(colorForAgentStatus("stopped"), colorForAgentStatus("some-future-status"))
    }

    @Test
    fun `unavailable is not the same color as idle`() {
        // Caso concreto de mayor riesgo real: confundir "disponible" con
        // "fallo no solicitado" sería el peor error de este indicador.
        assertNotEquals(colorForAgentStatus("idle"), colorForAgentStatus("unavailable"))
    }
}

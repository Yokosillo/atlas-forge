package com.factoriasoftware.factorybrain

import androidx.compose.ui.graphics.Color
import com.factoriasoftware.factorybrain.ui.colorForBacklogState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Verifica `colorForBacklogState` (T-FB020-US03-01): color asociado al
 * `state` literal de un item de backlog (Epic/US/Task), complementario al
 * texto de estado (nunca su sustituto — eso se verifica en el propio
 * Composable, no aquí). Mismos valores fijos ya validados con WCAG 1.4.11
 * que `colorForAgentStatus` (ver `ColorForAgentStatusTest`/
 * `ContrastRatioTest`) — reutilizados literalmente, no reinventados.
 */
class ColorForBacklogStateTest {
    @Test
    fun `DONE and TODO map to distinct colors`() {
        assertNotEquals(colorForBacklogState("DONE"), colorForBacklogState("TODO"))
    }

    @Test
    fun `the same state always maps to the same color`() {
        assertEquals(colorForBacklogState("DONE"), colorForBacklogState("DONE"))
        assertEquals(colorForBacklogState("TODO"), colorForBacklogState("TODO"))
    }

    @Test
    fun `DONE and TODO reuse the exact same values as colorForAgentStatus`() {
        // Criterio de la Task: "reutilizando la paleta WCAG ya validada de
        // colorForAgentStatus" — no una paleta nueva.
        assertEquals(Color(0xFF2E7D32), colorForBacklogState("DONE"))
        assertEquals(Color(0xFFEF6C00), colorForBacklogState("TODO"))
    }

    @Test
    fun `an unrecognized state falls back to a neutral grey, never DONE or TODO`() {
        // Criterio de aceptación explícito: "un estado no reconocido usa
        // un color neutro explícito, nunca se confunde visualmente con
        // DONE o TODO".
        val neutral = colorForBacklogState("SUPERADA (ver US-FB017-03)")
        assertNotEquals(colorForBacklogState("DONE"), neutral)
        assertNotEquals(colorForBacklogState("TODO"), neutral)
        assertEquals(Color(0xFF757575), neutral)
    }

    @Test
    fun `a DONE value with a real parenthetical suffix is treated as unrecognized, not DONE`() {
        // Caso real verificado sobre el backlog de este proyecto:
        // "DONE (aplicada directamente por el crítico...)" — el propio
        // backend compara `state == "DONE"` por IGUALDAD EXACTA
        // (`brain/models/backlog.py::STATE_DONE`,
        // `parser.py::classify_todo_items`), así que este valor NO cuenta
        // como DONE para el dominio. El cliente debe ser coherente con
        // esa misma igualdad exacta, no inventar una heurística de
        // prefijo que discrepe del propio backend.
        val realWorldValue = "DONE (aplicada directamente por el crítico para desbloquear la verificación)"
        assertEquals(Color(0xFF757575), colorForBacklogState(realWorldValue))
        assertNotEquals(Color(0xFF2E7D32), colorForBacklogState(realWorldValue))
    }

    @Test
    fun `a null state falls back to the neutral color without crashing`() {
        assertEquals(Color(0xFF757575), colorForBacklogState(null))
    }

    @Test
    fun `the palette keeps traffic light semantics`() {
        val done = colorForBacklogState("DONE")
        val todo = colorForBacklogState("TODO")
        val unknown = colorForBacklogState("anything-else")

        assertTrue("DONE debe ser verde (G dominante)", done.green > done.red && done.green > done.blue)
        assertTrue("TODO debe ser ámbar/naranja (R y G altos, B bajo)", todo.red > todo.blue && todo.green > todo.blue)
        assertTrue("desconocido debe ser gris (R≈G≈B)", unknown.red == unknown.green && unknown.green == unknown.blue)
    }
}

package com.factoriasoftware.factorybrain

import androidx.compose.ui.graphics.Color
import com.factoriasoftware.factorybrain.ui.colorForAgentStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Verifica `colorForAgentStatus` (T-FB017-US04-05 / T-FB017-US04-06): un
 * color asociado a cada `agent.status`, complementario al texto de estado
 * (nunca su sustituto — eso se verifica en el propio Composable, no aquí,
 * este test cubre solo la función pura de mapeo).
 *
 * Desde US04-06 la función devuelve colores FIJOS, independientes del tema:
 * US05-02 los mapeó a roles del `ColorScheme` (que con Dynamic Color toman
 * el tono del wallpaper del usuario — bug real detectado en dispositivo, un
 * wallpaper rojo/terracota dejaba los 4 estados en tonos rojizos casi
 * indistinguibles). Un indicador tipo semáforo debe reconocerse de un
 * vistazo siempre igual, sin importar el tema: por eso aquí se valida el
 * VALOR concreto de cada estado y su semántica de semáforo, no un rol del
 * esquema.
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
        assertEquals(colorForAgentStatus("stopped"), colorForAgentStatus("stopped"))
        assertEquals(colorForAgentStatus("unavailable"), colorForAgentStatus("unavailable"))
    }

    @Test
    fun `an unknown status does not crash and falls back to the stopped color`() {
        // No debería ocurrir con el dominio actual, pero un `when` no
        // exhaustivo ante una futura ampliación del backend no debe
        // lanzar — cae al mismo gris neutro que `stopped`.
        assertEquals(colorForAgentStatus("stopped"), colorForAgentStatus("some-future-status"))
    }

    @Test
    fun `the colors are fixed and do not depend on the theme or dynamic color`() {
        // Criterio US04-06: colores fijos, NO roles del ColorScheme. La
        // función ya no recibe ningún esquema: el valor debe ser un color
        // literal fijo, el mismo para cualquier tema/wallpaper.
        assertEquals(Color(0xFF2E7D32), colorForAgentStatus("idle"))
        assertEquals(Color(0xFFEF6C00), colorForAgentStatus("working"))
        assertEquals(Color(0xFF757575), colorForAgentStatus("stopped"))
        assertEquals(Color(0xFFD32F2F), colorForAgentStatus("unavailable"))
    }

    @Test
    fun `unavailable is not the same color as idle`() {
        // Caso concreto de mayor riesgo real: confundir "disponible" con
        // "fallo no solicitado" sería el peor error de este indicador.
        assertNotEquals(colorForAgentStatus("idle"), colorForAgentStatus("unavailable"))
    }

    @Test
    fun `the palette keeps traffic light semantics`() {
        // Verde = disponible, ámbar = ocupado, gris = detenido, rojo = fallo.
        // Verificamos el canal dominante para confirmar la semántica de
        // semáforo (no solo que sean distintos).
        val idle = colorForAgentStatus("idle")
        val working = colorForAgentStatus("working")
        val stopped = colorForAgentStatus("stopped")
        val unavailable = colorForAgentStatus("unavailable")

        assertTrue("idle debe ser verde (G dominante)", idle.green > idle.red && idle.green > idle.blue)
        assertTrue("working debe ser ámbar/naranja (R y G altos, B bajo)", working.red > working.blue && working.green > working.blue)
        assertTrue("stopped debe ser gris (R≈G≈B)", stopped.red == stopped.green && stopped.green == stopped.blue)
        assertTrue("unavailable debe ser rojo (R dominante)", unavailable.red > unavailable.green && unavailable.red > unavailable.blue)
    }
}

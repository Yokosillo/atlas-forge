package com.factoriasoftware.factorybrain

import androidx.compose.ui.graphics.Color
import com.factoriasoftware.factorybrain.ui.DARK_THEME_BACKGROUND
import com.factoriasoftware.factorybrain.ui.LIGHT_THEME_BACKGROUND
import com.factoriasoftware.factorybrain.ui.colorForAgentStatus
import com.factoriasoftware.factorybrain.ui.colorForBacklogState
import com.factoriasoftware.factorybrain.ui.wcagContrastRatio
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Verifica el ratio de contraste WCAG 1.4.11 REAL (no solo una afirmación
 * de diseño en un comentario) de los indicadores de color de estado
 * contra los fondos reales del tema claro/oscuro (T-FB020-US03-01,
 * criterio de aceptación explícito: "contraste ≥3:1 verificado en claro y
 * oscuro"). `colorForBacklogState` reutiliza literalmente los mismos
 * valores que `colorForAgentStatus` ("idle"=DONE, "working"=TODO), así
 * que ambos se verifican aquí con la misma fórmula.
 */
class ContrastRatioTest {
    private val minimumContrast = 3.0

    @Test
    fun `identical colors have a contrast ratio of exactly 1`() {
        assertEquals(1.0, wcagContrastRatio(Color(0xFF000000), Color(0xFF000000)), 0.0001)
    }

    @Test
    fun `black on white has the maximum possible contrast ratio, 21`() {
        assertEquals(21.0, wcagContrastRatio(Color(0xFF000000), Color(0xFFFFFFFF)), 0.01)
    }

    @Test
    fun `contrast ratio is symmetric regardless of argument order`() {
        val a = wcagContrastRatio(Color(0xFF2E7D32), LIGHT_THEME_BACKGROUND)
        val b = wcagContrastRatio(LIGHT_THEME_BACKGROUND, Color(0xFF2E7D32))
        assertEquals(a, b, 0.0001)
    }

    @Test
    fun `colorForBacklogState DONE meets 3 to 1 contrast against both theme backgrounds`() {
        val done = colorForBacklogState("DONE")
        assertTrue(
            "DONE contra fondo claro debe ser >=3:1",
            wcagContrastRatio(done, LIGHT_THEME_BACKGROUND) >= minimumContrast,
        )
        assertTrue(
            "DONE contra fondo oscuro debe ser >=3:1",
            wcagContrastRatio(done, DARK_THEME_BACKGROUND) >= minimumContrast,
        )
    }

    @Test
    fun `colorForBacklogState TODO meets 3 to 1 contrast against both theme backgrounds`() {
        val todo = colorForBacklogState("TODO")
        assertTrue(
            "TODO contra fondo claro debe ser >=3:1",
            wcagContrastRatio(todo, LIGHT_THEME_BACKGROUND) >= minimumContrast,
        )
        assertTrue(
            "TODO contra fondo oscuro debe ser >=3:1",
            wcagContrastRatio(todo, DARK_THEME_BACKGROUND) >= minimumContrast,
        )
    }

    @Test
    fun `colorForBacklogState unrecognized (neutral grey) meets 3 to 1 contrast against both theme backgrounds`() {
        val neutral = colorForBacklogState("SUPERADA")
        assertTrue(
            "gris neutro contra fondo claro debe ser >=3:1",
            wcagContrastRatio(neutral, LIGHT_THEME_BACKGROUND) >= minimumContrast,
        )
        assertTrue(
            "gris neutro contra fondo oscuro debe ser >=3:1",
            wcagContrastRatio(neutral, DARK_THEME_BACKGROUND) >= minimumContrast,
        )
    }

    @Test
    fun `every colorForAgentStatus value meets 3 to 1 contrast against both theme backgrounds`() {
        // Mismo criterio ya reclamado en el comentario de `colorForAgentStatus`
        // (T-FB017-US04-06) — verificado aquí con la fórmula real por
        // primera vez, no solo documentado.
        for (status in listOf("idle", "working", "stopped", "unavailable")) {
            val color = colorForAgentStatus(status)
            assertTrue(
                "$status contra fondo claro debe ser >=3:1",
                wcagContrastRatio(color, LIGHT_THEME_BACKGROUND) >= minimumContrast,
            )
            assertTrue(
                "$status contra fondo oscuro debe ser >=3:1",
                wcagContrastRatio(color, DARK_THEME_BACKGROUND) >= minimumContrast,
            )
        }
    }
}

package com.factoriasoftware.factorybrain

import com.factoriasoftware.factorybrain.ui.epicIdFromLabel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Verifica `epicIdFromLabel` (T-FB020-US01-02): el prefijo `FB-xxx` de la
 * etiqueta libre `**Epic:**` de una US/Task, replicando en Kotlin el
 * mismo criterio que `_EPIC_LABEL_PREFIX_PATTERN` del backend
 * (`brain/backlog/detail.py`) — necesario porque `by_epic` (`GET
 * /backlog`) agrupa por el STRING COMPLETO del label (con sufijos
 * distintos para la misma Epic real), pero `GET /backlog/{epicId}` solo
 * acepta el prefijo limpio.
 */
class EpicIdFromLabelTest {
    @Test
    fun `extracts the FB-xxx prefix from a clean label`() {
        assertEquals("FB-020", epicIdFromLabel("FB-020 · Gestión de Backlog"))
    }

    @Test
    fun `extracts the prefix even with a suffix variant`() {
        // Caso real verificado sobre el backlog de este proyecto: la
        // misma Epic FB-008 aparece con 8 variantes de sufijo distintas
        // entre sus propias Tasks/US.
        assertEquals(
            "FB-008",
            epicIdFromLabel("FB-008 · Despacho y Coordinación de Trabajo (alcance v1 — Dispatcher manual)"),
        )
    }

    @Test
    fun `handles a four-digit epic number`() {
        assertEquals("FB-1234", epicIdFromLabel("FB-1234 · Epic futura"))
    }

    @Test
    fun `returns null for a label that does not follow the FB-xxx convention`() {
        // Caso real verificado sobre el backlog de este proyecto.
        assertNull(epicIdFromLabel("(ninguna — infraestructura de proyecto)"))
    }

    @Test
    fun `trims surrounding whitespace before matching`() {
        assertEquals("FB-020", epicIdFromLabel("  FB-020 · Gestión de Backlog  "))
    }
}

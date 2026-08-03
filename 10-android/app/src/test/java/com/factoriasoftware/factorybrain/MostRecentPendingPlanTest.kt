package com.factoriasoftware.factorybrain

import com.factoriasoftware.factorybrain.net.PlanDto
import com.factoriasoftware.factorybrain.net.PlanStepDto
import com.factoriasoftware.factorybrain.ui.mostRecentPendingPlan
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Verifica `mostRecentPendingPlan` (T-FB017-US01-09): qué plan `proposed`
 * recuperar al reabrir la app desde `GET /plans`. `GET /plans` devuelve
 * los planes en orden de registro (sin purgar los ya decididos), así que
 * el criterio es el ÚLTIMO `proposed` = el más reciente.
 */
class MostRecentPendingPlanTest {
    private fun plan(id: String, status: String) = PlanDto(
        plan_id = id,
        goal = "US-$id",
        status = status,
        steps = emptyList<PlanStepDto>(),
    )

    @Test
    fun `returns null when there are no proposed plans`() {
        val plans = listOf(
            plan("p1", "approved"),
            plan("p2", "rejected"),
        )
        assertNull(mostRecentPendingPlan(plans))
    }

    @Test
    fun `returns the only proposed plan when it exists`() {
        val plans = listOf(
            plan("p1", "approved"),
            plan("p2", "proposed"),
        )
        assertEquals("p2", mostRecentPendingPlan(plans)?.plan_id)
    }

    @Test
    fun `returns the most recent of several proposed plans`() {
        // Caso límite documentado: más de un plan `proposed` (no se espera
        // en uso normal) -> se recupera el MÁS RECIENTE, i.e. el último en
        // el orden de registro devuelto por `GET /plans`.
        val plans = listOf(
            plan("p1", "proposed"),
            plan("p2", "approved"),
            plan("p3", "proposed"),
            plan("p4", "proposed"),
        )
        assertEquals("p4", mostRecentPendingPlan(plans)?.plan_id)
    }

    @Test
    fun `an empty list returns null`() {
        assertNull(mostRecentPendingPlan(emptyList()))
    }
}

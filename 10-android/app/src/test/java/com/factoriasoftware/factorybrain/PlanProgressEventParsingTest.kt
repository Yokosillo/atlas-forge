package com.factoriasoftware.factorybrain

import com.factoriasoftware.factorybrain.net.PlanDto
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Verifica que el payload real que `WS /ws/plans` publica
 * (`plans_hub.publish({"event": "plan_progress", **result})`,
 * `brain/api/routes.py`) se parsea correctamente como [PlanDto] pese al
 * campo `event` adicional que ese DTO no declara — mismo caso ya cubierto
 * para Jobs en `JobStatusEventParsingTest`, aquí para planes
 * (T-FB017-US01-04). También cubre que `already_decided` (ausente en el
 * payload de `POST /plans`, presente en approve/reject/get) se parsea
 * como `null` cuando falta, sin lanzar.
 */
class PlanProgressEventParsingTest {
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val planAdapter = moshi.adapter(PlanDto::class.java)

    @Test
    fun `parses a real plan_progress WebSocket payload with the extra 'event' field`() {
        val rawPayload = """
            {"event":"plan_progress","plan_id":"p1","already_decided":false,
             "goal":"US-FB008-04","status":"approved",
             "steps":[{"description":"do X","mechanism":"agent","status":"running"}]}
        """.trimIndent()

        val plan = planAdapter.fromJson(rawPayload)

        assertEquals("p1", plan?.plan_id)
        assertEquals("approved", plan?.status)
        assertEquals(false, plan?.already_decided)
        assertEquals("running", plan?.steps?.get(0)?.status)
    }

    @Test
    fun `parses a blocked plan distinctly from running`() {
        val rawPayload = """
            {"event":"plan_progress","plan_id":"p1","already_decided":false,
             "goal":"US-FB008-04","status":"blocked",
             "steps":[{"description":"do X","mechanism":"agent","status":"failed"},
                       {"description":"do Y","mechanism":"agent","status":"pending"}]}
        """.trimIndent()

        val plan = planAdapter.fromJson(rawPayload)

        assertEquals("blocked", plan?.status)
        assertEquals("failed", plan?.steps?.get(0)?.status)
        assertEquals("pending", plan?.steps?.get(1)?.status)
    }

    @Test
    fun `already_decided defaults to null when absent, as in POST plans response`() {
        val rawPayload = """
            {"plan_id":"p1","goal":"US-FB008-04","status":"proposed","steps":[]}
        """.trimIndent()

        val plan = planAdapter.fromJson(rawPayload)

        assertNull(plan?.already_decided)
    }
}

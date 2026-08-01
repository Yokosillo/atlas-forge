package com.factoriasoftware.factorybrain

import com.factoriasoftware.factorybrain.net.JobDto
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Verifica que el payload real que `WS /ws/jobs` publica
 * (`jobs_hub.publish({"event": "job_status", **_serialize_job(job)})`,
 * `brain/api/routes.py`) se parsea correctamente como [JobDto] pese al
 * campo `event` adicional que ese DTO no declara — `JobsViewModel`
 * (T-FB017-US01-03) parsea cada mensaje entrante de ese WebSocket
 * directamente como `JobDto`, así que este test cubre el caso real sin
 * necesitar Robolectric solo para instanciar el `AndroidViewModel`
 * completo.
 */
class JobStatusEventParsingTest {
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val jobAdapter = moshi.adapter(JobDto::class.java)

    @Test
    fun `parses a real job_status WebSocket payload with the extra 'event' field`() {
        val rawPayload = """
            {"event":"job_status","id":"j1","session_id":"s1","agent_id":"a1",
             "description":"implement the feature","status":"completed","result":"done"}
        """.trimIndent()

        val job = jobAdapter.fromJson(rawPayload)

        assertEquals("j1", job?.id)
        assertEquals("completed", job?.status)
        assertEquals("done", job?.result)
    }

    @Test
    fun `parses the intermediate created event with a null result`() {
        val rawPayload = """
            {"event":"job_status","id":"j2","session_id":"s1","agent_id":"a1",
             "description":"implement the feature","status":"created","result":null}
        """.trimIndent()

        val job = jobAdapter.fromJson(rawPayload)

        assertEquals("created", job?.status)
        assertEquals(null, job?.result)
    }
}

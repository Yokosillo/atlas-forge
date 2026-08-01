package com.factoriasoftware.factorybrain

import com.factoriasoftware.factorybrain.net.JobDto
import com.factoriasoftware.factorybrain.ui.agentsWithRunningJob
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Verifica la función pura de T-FB017-US04-01 que deriva, a partir del
 * histórico de Jobs de la sesión (`GET /jobs`), qué agentes tienen
 * actualmente un Job `running` — usada por `AgentsScreen` para advertir
 * explícitamente en el diálogo de "Detener" cuando el agente tiene una
 * tarea en curso, sin necesitar ningún campo nuevo en `GET /agents`.
 */
class AgentsWithRunningJobTest {
    private fun job(agentId: String, status: String) =
        JobDto(id = "j-$agentId-$status", session_id = "s1", agent_id = agentId, description = "d", status = status, result = null)

    @Test
    fun `an agent with a running job is included in the result`() {
        val jobs = listOf(job("a1", "running"))

        assertEquals(setOf("a1"), agentsWithRunningJob(jobs))
    }

    @Test
    fun `an agent with only completed or failed jobs is not included`() {
        val jobs = listOf(job("a1", "completed"), job("a1", "failed"))

        assertEquals(emptySet<String>(), agentsWithRunningJob(jobs))
    }

    @Test
    fun `an agent with a past completed job and a new running job is included`() {
        val jobs = listOf(job("a1", "completed"), job("a1", "running"))

        assertEquals(setOf("a1"), agentsWithRunningJob(jobs))
    }

    @Test
    fun `multiple agents with running jobs are all included`() {
        val jobs = listOf(job("a1", "running"), job("a2", "running"), job("a3", "completed"))

        assertEquals(setOf("a1", "a2"), agentsWithRunningJob(jobs))
    }

    @Test
    fun `an empty job history results in an empty set`() {
        assertEquals(emptySet<String>(), agentsWithRunningJob(emptyList()))
    }

    @Test
    fun `a cancelled job is not considered running`() {
        val jobs = listOf(job("a1", "cancelled"))

        assertEquals(emptySet<String>(), agentsWithRunningJob(jobs))
    }
}

package com.factoriasoftware.factorybrain

import com.factoriasoftware.factorybrain.net.BackendClient
import com.factoriasoftware.factorybrain.net.BackendRequestException
import com.factoriasoftware.factorybrain.net.BackendUnavailableException
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

/**
 * Tests del cliente HTTP (T-FB017-US01-01) contra un servidor HTTP real
 * de prueba (`MockWebServer`, no un mock de la capa de red de OkHttp) —
 * mismo criterio de "comportamiento real, no simulado" ya aplicado en el
 * backend Python (nunca se mockea la llamada HTTP entera, se levanta un
 * servidor real de prueba).
 */
class BackendClientTest {
    private lateinit var server: MockWebServer
    private lateinit var client: BackendClient

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        client = BackendClient()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun `getHealth returns the real response body on success`() = runBlocking {
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody("""{"status":"ok","session_id":null}"""),
        )

        val body = client.getHealth(server.url("/").toString().trimEnd('/'))

        assertEquals("""{"status":"ok","session_id":null}""", body)
    }

    @Test
    fun `getHealth throws BackendUnavailableException on non-2xx response`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(500).setBody("internal error"))

        try {
            client.getHealth(server.url("/").toString().trimEnd('/'))
            fail("Expected BackendUnavailableException")
        } catch (error: BackendUnavailableException) {
            assertTrue(error.message!!.contains("500"))
        }
    }

    @Test
    fun `getHealth throws BackendUnavailableException when the host is unreachable`() =
        runBlocking {
            server.shutdown()

            try {
                client.getHealth(server.url("/").toString().trimEnd('/'))
                fail("Expected BackendUnavailableException")
            } catch (error: BackendUnavailableException) {
                assertTrue(error.cause != null)
            }
        }

    @Test
    fun `getAgents parses the real JSON list returned by GET agents`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """[{"id":"a1","name":"agent-1","role":"developer","status":"idle"}]"""
            ),
        )

        val agents = client.getAgents(server.url("/").toString().trimEnd('/'))

        assertEquals(1, agents.size)
        assertEquals("a1", agents[0].id)
        assertEquals("agent-1", agents[0].name)
        assertEquals("developer", agents[0].role)
        assertEquals("idle", agents[0].status)
    }

    @Test
    fun `getAgents returns an empty list when there is no active session (404)`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(404).setBody(
                """{"detail":"No hay ninguna sesión de desarrollo activa."}"""
            ),
        )

        val agents = client.getAgents(server.url("/").toString().trimEnd('/'))

        assertTrue(agents.isEmpty())
    }

    @Test
    fun `launchAgent posts the request body and parses the launched agent`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(201).setBody(
                """{"id":"a2","name":"agent-2","role":"critic","status":"idle"}"""
            ),
        )

        val agent = client.launchAgent(
            server.url("/").toString().trimEnd('/'),
            role = "critic",
            runtimeType = "opencode",
            model = "deepseek/deepseek-chat",
        )

        assertEquals("a2", agent.id)
        assertEquals("critic", agent.role)

        val recordedRequest = server.takeRequest()
        assertEquals("POST", recordedRequest.method)
        assertEquals("/agents", recordedRequest.path)
        val sentBody = recordedRequest.body.readUtf8()
        assertTrue(sentBody.contains("\"role\":\"critic\""))
        assertTrue(sentBody.contains("\"runtime_type\":\"opencode\""))
        assertTrue(sentBody.contains("\"model\":\"deepseek/deepseek-chat\""))
    }

    @Test
    fun `launchAgent propagates the real domain reason on a rejected combination`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(400).setBody(
                """{"detail":"El runtime 'claude-code' no admite indicar un modelo."}"""
            ),
        )

        try {
            client.launchAgent(
                server.url("/").toString().trimEnd('/'),
                role = "developer",
                runtimeType = "claude-code",
                model = "some-model",
            )
            fail("Expected BackendRequestException")
        } catch (error: BackendRequestException) {
            assertEquals("El runtime 'claude-code' no admite indicar un modelo.", error.message)
        }
    }

    @Test
    fun `stopAgent posts to the stop endpoint and parses the updated agent`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"id":"a1","name":"agent-1","role":"developer","status":"stopped"}"""
            ),
        )

        val agent = client.stopAgent(server.url("/").toString().trimEnd('/'), "a1")

        assertEquals("stopped", agent.status)

        val recordedRequest = server.takeRequest()
        assertEquals("POST", recordedRequest.method)
        assertEquals("/agents/a1/stop", recordedRequest.path)
    }

    @Test
    fun `getProjects parses the real JSON list returned by GET projects`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """[{"id":"/ws/project-a","name":"project-a","path":"/ws/project-a","repository":""}]"""
            ),
        )

        val projects = client.getProjects(server.url("/").toString().trimEnd('/'))

        assertEquals(1, projects.size)
        assertEquals("/ws/project-a", projects[0].id)
        assertEquals("project-a", projects[0].name)
    }

    @Test
    fun `getProject returns null when there is no active project (404)`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(404).setBody(
                """{"detail":"No hay ningún proyecto activo."}"""
            ),
        )

        val project = client.getProject(server.url("/").toString().trimEnd('/'))

        assertEquals(null, project)
    }

    @Test
    fun `getProject parses the real active project when one exists`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"id":"/ws/project-a","name":"project-a","path":"/ws/project-a","repository":""}"""
            ),
        )

        val project = client.getProject(server.url("/").toString().trimEnd('/'))

        assertEquals("project-a", project?.name)
    }

    @Test
    fun `selectProject posts the project_id and parses the newly active project`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"id":"/ws/project-b","name":"project-b","path":"/ws/project-b","repository":""}"""
            ),
        )

        val selected = client.selectProject(server.url("/").toString().trimEnd('/'), "/ws/project-b")

        assertEquals("project-b", selected.name)

        val recordedRequest = server.takeRequest()
        assertEquals("POST", recordedRequest.method)
        assertEquals("/project", recordedRequest.path)
        assertTrue(recordedRequest.body.readUtf8().contains("\"project_id\":\"/ws/project-b\""))
    }

    @Test
    fun `selectProject propagates the real domain reason for an unknown project`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(400).setBody(
                """{"detail":"El proyecto '/does/not/exist' no pertenece a la lista de repositorios descubiertos."}"""
            ),
        )

        try {
            client.selectProject(server.url("/").toString().trimEnd('/'), "/does/not/exist")
            fail("Expected BackendRequestException")
        } catch (error: BackendRequestException) {
            assertTrue(error.message!!.contains("no pertenece"))
        }
    }

    @Test
    fun `getJobs parses the real JSON history returned by GET jobs`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """[{"id":"j1","session_id":"s1","agent_id":"a1","description":"do it","status":"completed","result":"done"}]"""
            ),
        )

        val jobs = client.getJobs(server.url("/").toString().trimEnd('/'))

        assertEquals(1, jobs.size)
        assertEquals("j1", jobs[0].id)
        assertEquals("completed", jobs[0].status)
        assertEquals("done", jobs[0].result)
    }

    @Test
    fun `getJobs returns an empty list when there is no active session (404)`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(404).setBody(
                """{"detail":"No hay ninguna sesión de desarrollo activa."}"""
            ),
        )

        val jobs = client.getJobs(server.url("/").toString().trimEnd('/'))

        assertTrue(jobs.isEmpty())
    }

    @Test
    fun `createAndDispatchJob posts the request body and parses the finished job`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(201).setBody(
                """{"id":"j2","session_id":"s1","agent_id":"a1","description":"implement X","status":"completed","result":"implemented"}"""
            ),
        )

        val job = client.createAndDispatchJob(
            server.url("/").toString().trimEnd('/'),
            agentId = "a1",
            description = "implement X",
            previousJobId = "j1",
        )

        assertEquals("j2", job.id)
        assertEquals("completed", job.status)
        assertEquals("implemented", job.result)

        val recordedRequest = server.takeRequest()
        assertEquals("POST", recordedRequest.method)
        assertEquals("/jobs", recordedRequest.path)
        val sentBody = recordedRequest.body.readUtf8()
        assertTrue(sentBody.contains("\"agent_id\":\"a1\""))
        assertTrue(sentBody.contains("\"description\":\"implement X\""))
        assertTrue(sentBody.contains("\"previous_job_id\":\"j1\""))
    }

    @Test
    fun `createAndDispatchJob propagates the real domain reason on rejection`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(404).setBody(
                """{"detail":"No existe ningún agente con id 'unknown'."}"""
            ),
        )

        try {
            client.createAndDispatchJob(
                server.url("/").toString().trimEnd('/'),
                agentId = "unknown",
                description = "do it",
                previousJobId = null,
            )
            fail("Expected BackendRequestException")
        } catch (error: BackendRequestException) {
            assertEquals("No existe ningún agente con id 'unknown'.", error.message)
        }
    }

    @Test
    fun `requestPlan posts the goal and parses the proposed plan`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(201).setBody(
                """{"plan_id":"p1","goal":"US-FB008-04","status":"proposed",
                    "steps":[{"description":"do X","mechanism":"agent","status":"pending"}]}"""
            ),
        )

        val plan = client.requestPlan(server.url("/").toString().trimEnd('/'), "US-FB008-04")

        assertEquals("p1", plan.plan_id)
        assertEquals("proposed", plan.status)
        assertEquals(1, plan.steps.size)
        assertEquals("do X", plan.steps[0].description)

        val recordedRequest = server.takeRequest()
        assertEquals("POST", recordedRequest.method)
        assertEquals("/plans", recordedRequest.path)
        assertTrue(recordedRequest.body.readUtf8().contains("\"goal\":\"US-FB008-04\""))
    }

    @Test
    fun `getPlan parses the real progress of an already emitted plan`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"plan_id":"p1","goal":"US-FB008-04","status":"approved",
                    "steps":[{"description":"do X","mechanism":"agent","status":"completed"}]}"""
            ),
        )

        val plan = client.getPlan(server.url("/").toString().trimEnd('/'), "p1")

        assertEquals("approved", plan.status)
        assertEquals("completed", plan.steps[0].status)
    }

    @Test
    fun `approvePlan posts to the approve endpoint and parses the dispatched plan`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"plan_id":"p1","goal":"US-FB008-04","status":"approved","already_decided":false,
                    "steps":[{"description":"do X","mechanism":"agent","status":"completed"}]}"""
            ),
        )

        val plan = client.approvePlan(server.url("/").toString().trimEnd('/'), "p1")

        assertEquals("approved", plan.status)
        assertEquals(false, plan.already_decided)

        val recordedRequest = server.takeRequest()
        assertEquals("POST", recordedRequest.method)
        assertEquals("/plans/p1/approve", recordedRequest.path)
    }

    @Test
    fun `rejectPlan posts to the reject endpoint and parses the rejected plan`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"plan_id":"p1","goal":"US-FB008-04","status":"rejected","already_decided":false,"steps":[]}"""
            ),
        )

        val plan = client.rejectPlan(server.url("/").toString().trimEnd('/'), "p1")

        assertEquals("rejected", plan.status)

        val recordedRequest = server.takeRequest()
        assertEquals("POST", recordedRequest.method)
        assertEquals("/plans/p1/reject", recordedRequest.path)
    }

    @Test
    fun `approvePlan propagates already_decided true without re-dispatching`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"plan_id":"p1","goal":"US-FB008-04","status":"approved","already_decided":true,
                    "steps":[{"description":"do X","mechanism":"agent","status":"completed"}]}"""
            ),
        )

        val plan = client.approvePlan(server.url("/").toString().trimEnd('/'), "p1")

        assertEquals(true, plan.already_decided)
    }

    @Test
    fun `getScripts parses the real JSON list returned by GET scripts`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """[{"id":"lint","name":"Lint","command":"ruff check .","description":"Runs the linter."}]"""
            ),
        )

        val scripts = client.getScripts(server.url("/").toString().trimEnd('/'))

        assertEquals(1, scripts.size)
        assertEquals("lint", scripts[0].id)
        assertEquals("ruff check .", scripts[0].command)
    }

    @Test
    fun `runScript posts to the run endpoint and parses a successful result`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"success":true,"exit_code":0,"stdout":"hello","stderr":"","error_message":null}"""
            ),
        )

        val result = client.runScript(server.url("/").toString().trimEnd('/'), "greet")

        assertEquals(true, result.success)
        assertEquals(0, result.exit_code)
        assertEquals("hello", result.stdout)

        val recordedRequest = server.takeRequest()
        assertEquals("POST", recordedRequest.method)
        assertEquals("/scripts/greet/run", recordedRequest.path)
    }

    @Test
    fun `runScript parses an error result for an unknown script_id without throwing`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"success":false,"exit_code":null,"stdout":"","stderr":"","error_message":"No existe ningún script catalogado con id 'unknown'."}"""
            ),
        )

        val result = client.runScript(server.url("/").toString().trimEnd('/'), "unknown")

        assertEquals(false, result.success)
        assertEquals(null, result.exit_code)
        assertTrue(result.error_message!!.contains("unknown"))
    }

    @Test
    fun `runScript parses a failing script result with its nonzero exit code`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"success":false,"exit_code":3,"stdout":"","stderr":"something went wrong","error_message":null}"""
            ),
        )

        val result = client.runScript(server.url("/").toString().trimEnd('/'), "broken")

        assertEquals(false, result.success)
        assertEquals(3, result.exit_code)
        assertEquals("something went wrong", result.stderr)
    }

    @Test
    fun `cancelJob posts to the cancel endpoint and parses the cancelled job`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"id":"j1","session_id":"s1","agent_id":"a1","description":"d","status":"cancelled","result":"cancelado"}"""
            ),
        )

        val job = client.cancelJob(server.url("/").toString().trimEnd('/'), "j1")

        assertEquals("cancelled", job.status)
        assertEquals("cancelado", job.result)

        val recordedRequest = server.takeRequest()
        assertEquals("POST", recordedRequest.method)
        assertEquals("/jobs/j1/cancel", recordedRequest.path)
    }

    @Test
    fun `cancelJob propagates the real domain reason when the job is not running`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(400).setBody(
                """{"detail":"No se puede cancelar el Job 'j1': está en estado 'completed', debe estar 'running'."}"""
            ),
        )

        try {
            client.cancelJob(server.url("/").toString().trimEnd('/'), "j1")
            fail("Expected BackendRequestException")
        } catch (error: BackendRequestException) {
            assertTrue(error.message!!.contains("debe estar 'running'"))
        }
    }
}

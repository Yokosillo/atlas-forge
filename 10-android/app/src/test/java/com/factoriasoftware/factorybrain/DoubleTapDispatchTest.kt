package com.factoriasoftware.factorybrain

import com.factoriasoftware.factorybrain.net.BackendClient
import com.factoriasoftware.factorybrain.ui.SingleFlightAction
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

/**
 * Test end-to-end del escenario completo de T-FB017-US04-02 (criterio de
 * aceptación literal: "pulsar dos veces seguidas... antes de que la
 * primera petición responda solo dispara una llamada real al backend,
 * verificado con test... mock del cliente HTTP con delay simulado") —
 * reproduce lo que ocurriría en un `ViewModel` real: dos "taps"
 * concurrentes reales (dos corrutinas) contra un `BackendClient` real
 * (mismo cliente que usan los ViewModels, no un doble) apuntando a un
 * `MockWebServer` real con una respuesta deliberadamente lenta
 * (`setBodyDelay`), ambos protegidos por el mismo `SingleFlightAction`
 * que ya usan `AgentsViewModel`/`JobsViewModel`/`PlanViewModel`/
 * `ScriptsViewModel`.
 *
 * No instancia ningún `AndroidViewModel` directamente (requieren
 * `Application`) — el guard + el cliente HTTP real son exactamente las
 * dos piezas que un `ViewModel` combina, así que verificarlas juntas aquí
 * cubre el comportamiento real sin necesitar Robolectric.
 */
class DoubleTapDispatchTest {
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
    fun `two concurrent taps while the request is in flight only reach the backend once`() =
        runBlocking {
            // Respuesta deliberadamente lenta (delay real de red, no
            // simulado con un mock de la capa HTTP) — reproduce el caso
            // real de POST /agents tardando en responder mientras el
            // usuario podría pulsar "Lanzar" una segunda vez.
            server.enqueue(
                MockResponse()
                    .setResponseCode(201)
                    .setBodyDelay(300, TimeUnit.MILLISECONDS)
                    .setBody(
                        """{"id":"a1","name":"Developer-1","role":"developer","status":"idle"}"""
                    ),
            )

            val baseUrl = server.url("/").toString().trimEnd('/')
            val guard = SingleFlightAction()
            var firstRan = false

            val firstTap = async {
                firstRan = guard.runExclusive {
                    client.launchAgent(baseUrl, "developer", "claude-code", null)
                }
            }

            // Espera determinista a que el guard esté realmente tomado
            // por el primer tap (no una temporización fija adivinada) —
            // en cuanto `isRunning` es `true`, el primer tap ya entró en
            // `runExclusive` y su llamada de red (con `setBodyDelay` de
            // 300ms) está en curso.
            while (!guard.isRunning) {
                delay(1)
            }

            // Segundo "tap": la respuesta del primero sigue en vuelo
            // (setBodyDelay de 300ms) — debe descartarse sin llegar al
            // backend.
            val secondRan = guard.runExclusive {
                client.launchAgent(baseUrl, "developer", "claude-code", null)
            }

            firstTap.await()

            assertEquals("El segundo tap no debía ejecutar ninguna llamada", false, secondRan)
            assertEquals("El primer tap sí debía ejecutar la llamada", true, firstRan)
            assertEquals(
                "Solo una petición HTTP real debió llegar al backend",
                1,
                server.requestCount,
            )
        }
}

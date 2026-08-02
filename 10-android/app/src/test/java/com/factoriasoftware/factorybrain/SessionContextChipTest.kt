package com.factoriasoftware.factorybrain

import com.factoriasoftware.factorybrain.net.ProjectDto
import com.factoriasoftware.factorybrain.ui.HealthCheckState
import com.factoriasoftware.factorybrain.ui.ProjectUiState
import com.factoriasoftware.factorybrain.ui.activeProjectNameFor
import com.factoriasoftware.factorybrain.ui.isBackendConnected
import com.factoriasoftware.factorybrain.ui.isSessionContextResolved
import com.factoriasoftware.factorybrain.ui.sessionContextText
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Verifica las funciones puras de `SessionContextChip` (T-FB017-US03-01)
 * — el chip fusiona `HealthCheckScreen`/`ProjectScreen` reutilizando sus
 * `StateFlow` ya existentes, sin ninguna lógica de dominio nueva; estos
 * tests cubren solo la derivación de texto/estado del chip, no los
 * `ViewModel` en sí (ya cubiertos indirectamente por sus propias
 * pantallas).
 */
class SessionContextChipTest {
    private val project = ProjectDto(id = "p1", name = "factory-brain", path = "/repo", repository = "git")

    @Test
    fun `isBackendConnected is true only for Success`() {
        assertEquals(true, isBackendConnected(HealthCheckState.Success("ok")))
        assertEquals(false, isBackendConnected(HealthCheckState.Idle))
        assertEquals(false, isBackendConnected(HealthCheckState.Loading))
        assertEquals(false, isBackendConnected(HealthCheckState.Failure("no disponible")))
    }

    @Test
    fun `activeProjectNameFor returns the active project name when loaded`() {
        val state = ProjectUiState.Loaded(projects = listOf(project), activeProject = project)

        assertEquals("factory-brain", activeProjectNameFor(state))
    }

    @Test
    fun `activeProjectNameFor returns null when loaded without an active project`() {
        val state = ProjectUiState.Loaded(projects = listOf(project), activeProject = null)

        assertNull(activeProjectNameFor(state))
    }

    @Test
    fun `activeProjectNameFor returns null while still loading or unavailable`() {
        assertNull(activeProjectNameFor(ProjectUiState.Loading))
        assertNull(activeProjectNameFor(ProjectUiState.Unavailable("no disponible")))
    }

    @Test
    fun `sessionContextText combines connection and project name as specified`() {
        assertEquals(
            "Conectado · Proyecto: factory-brain",
            sessionContextText(isConnected = true, projectName = "factory-brain"),
        )
        assertEquals(
            "Sin conexión · Proyecto: ninguno",
            sessionContextText(isConnected = false, projectName = null),
        )
        assertEquals(
            "Conectado · Proyecto: ninguno",
            sessionContextText(isConnected = true, projectName = null),
        )
    }

    @Test
    fun `isSessionContextResolved is true only when connected AND a project is chosen`() {
        // T-FB017-US03-02: los 4 casos posibles de la combinación —
        // "resuelto" exige AMBAS condiciones, ninguna basta por sí sola.
        assertTrue(isSessionContextResolved(isConnected = true, projectName = "factory-brain"))
        assertFalse(isSessionContextResolved(isConnected = true, projectName = null))
        assertFalse(isSessionContextResolved(isConnected = false, projectName = "factory-brain"))
        assertFalse(isSessionContextResolved(isConnected = false, projectName = null))
    }
}

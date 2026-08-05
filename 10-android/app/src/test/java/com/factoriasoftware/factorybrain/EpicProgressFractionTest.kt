package com.factoriasoftware.factorybrain

import com.factoriasoftware.factorybrain.net.BacklogEpicDto
import com.factoriasoftware.factorybrain.ui.epicProgressFraction
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Verifica `epicProgressFraction` (T-FB020-US03-01, criterio de
 * aceptación 2): progreso agregado `DONE / total` de una Epic, calculado
 * sobre el conteo de User Stories (decisión documentada en el propio
 * `epicProgressFraction`, no de Tasks).
 */
class EpicProgressFractionTest {
    @Test
    fun `all done user stories is a fraction of 1`() {
        val epic = BacklogEpicDto(epic = "FB-999", user_stories = mapOf("DONE" to 3))
        assertEquals(1.0f, epicProgressFraction(epic), 0.0001f)
    }

    @Test
    fun `no done user stories is a fraction of 0`() {
        val epic = BacklogEpicDto(epic = "FB-999", user_stories = mapOf("TODO" to 5))
        assertEquals(0.0f, epicProgressFraction(epic), 0.0001f)
    }

    @Test
    fun `a mix of states computes the exact DONE over total ratio`() {
        val epic = BacklogEpicDto(epic = "FB-999", user_stories = mapOf("DONE" to 3, "TODO" to 2))
        assertEquals(0.6f, epicProgressFraction(epic), 0.0001f)
    }

    @Test
    fun `an epic with no user stories at all returns 0, not NaN or a crash`() {
        val epic = BacklogEpicDto(epic = "FB-999", user_stories = emptyMap(), tasks = mapOf("TODO" to 2))
        assertEquals(0.0f, epicProgressFraction(epic), 0.0001f)
    }

    @Test
    fun `progress is based on user stories, never on tasks`() {
        // Decisión documentada explícitamente en epicProgressFraction: el
        // conteo de Tasks no afecta el resultado en absoluto.
        val epic = BacklogEpicDto(
            epic = "FB-999",
            user_stories = mapOf("DONE" to 1, "TODO" to 1),
            tasks = mapOf("DONE" to 100),
        )
        assertEquals(0.5f, epicProgressFraction(epic), 0.0001f)
    }
}

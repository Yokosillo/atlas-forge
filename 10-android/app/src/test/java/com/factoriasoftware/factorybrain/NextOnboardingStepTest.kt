package com.factoriasoftware.factorybrain

import com.factoriasoftware.factorybrain.ui.OnboardingStep
import com.factoriasoftware.factorybrain.ui.nextOnboardingStep
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Verifica `nextOnboardingStep` (T-FB017-US03-03): decide qué paso del
 * flujo guiado mostrar — secuencia esperada por la Descripción de la
 * Task: paso 1 (conectar) mientras no hay conexión, paso 2 (elegir
 * proyecto) una vez conectado pero sin proyecto activo.
 */
class NextOnboardingStepTest {
    @Test
    fun `without connection, the step is always ConnectBackend regardless of project`() {
        assertEquals(OnboardingStep.ConnectBackend, nextOnboardingStep(isConnected = false, projectName = null))
        assertEquals(
            OnboardingStep.ConnectBackend,
            nextOnboardingStep(isConnected = false, projectName = "factory-brain"),
        )
    }

    @Test
    fun `connected without a project chosen, the step is ChooseProject`() {
        assertEquals(OnboardingStep.ChooseProject, nextOnboardingStep(isConnected = true, projectName = null))
    }
}

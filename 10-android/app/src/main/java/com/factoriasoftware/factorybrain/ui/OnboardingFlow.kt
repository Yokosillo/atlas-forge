package com.factoriasoftware.factorybrain.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

/**
 * Flujo de onboarding guiado (T-FB017-US03-03) que ocupa el hueco que
 * deja la navegación operativa (T-FB017-US03-02) cuando el contexto de
 * sesión no está resuelto — sustituye el mensaje mínimo de texto plano
 * que dejó esa Task por las 3 guías de Nielsen Norman Group para empty
 * states/onboarding:
 *
 * 1. **Comunicar el estado del sistema explícitamente** — [OnboardingStep]
 *    distingue "sin conexión" de "conectado pero sin proyecto", cada uno
 *    con su propio mensaje, nunca una pantalla en blanco ni un error
 *    técnico crudo.
 * 2. **Explicar qué falta y por qué**, en el lugar donde el usuario lo
 *    necesita — el mensaje aparece exactamente donde antes había
 *    solo las pestañas operativas vacías, no como un tutorial forzado al
 *    abrir la app.
 * 3. **Ofrecer una ruta directa a la acción que resuelve el vacío** — el
 *    botón de cada paso abre la MISMA hoja modal que
 *    [SessionContextChip] (`onOpenContextSheet`, la ruta ya construida en
 *    T-FB017-US03-01), no un flujo/pantalla duplicado.
 *
 * ## Secuencia de dos pasos (Descripción de la Task)
 *
 * `nextOnboardingStep` (función pura, ver más abajo) decide qué paso
 * mostrar: paso 1 (conectar) mientras no hay conexión; paso 2 (elegir
 * proyecto) una vez conectado pero sin proyecto activo. En cuanto ambos
 * se resuelven, `isSessionContextResolved` (T-FB017-US03-02) pasa a
 * `true` y `MainActivity` deja de montar este componente por completo —
 * la navegación operativa "aparece automáticamente" (criterio de
 * aceptación explícito) porque es la MISMA condición ya evaluada ahí, no
 * una segunda comprobación redundante.
 */
internal sealed interface OnboardingStep {
    data object ConnectBackend : OnboardingStep
    data object ChooseProject : OnboardingStep
}

/**
 * Decide qué paso del onboarding mostrar — función pura, testeable sin
 * `@Composable`, mismo criterio ya aplicado en toda la app. Reutiliza
 * [isBackendConnected]/[activeProjectNameFor] a través de sus resultados
 * ya calculados (`isConnected`/`projectName`), sin volver a inspeccionar
 * `HealthCheckState`/`ProjectUiState` aquí — ninguna lógica de "¿hay
 * conexión? ¿hay proyecto?" se duplica.
 */
internal fun nextOnboardingStep(isConnected: Boolean, projectName: String?): OnboardingStep =
    if (!isConnected) OnboardingStep.ConnectBackend else OnboardingStep.ChooseProject

@Composable
fun OnboardingFlow(
    isConnected: Boolean,
    projectName: String?,
    onOpenContextSheet: () -> Unit,
) {
    val step = nextOnboardingStep(isConnected, projectName)

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        when (step) {
            is OnboardingStep.ConnectBackend -> Column(
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                Text(
                    "No hay conexión con el backend",
                    style = MaterialTheme.typography.titleLarge,
                    textAlign = TextAlign.Start,
                )
                Text(
                    "Factory Brain necesita hablar con el backend antes de poder " +
                        "mostrar agentes, Jobs o el plan del Critic. Configura la URL " +
                        "y comprueba la conexión para continuar.",
                )
                Button(
                    onClick = onOpenContextSheet,
                    modifier = Modifier.fillMaxSize().height(48.dp),
                ) {
                    Text("Configurar conexión")
                }
            }
            is OnboardingStep.ChooseProject -> Column(
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                Text(
                    "No has elegido un proyecto todavía",
                    style = MaterialTheme.typography.titleLarge,
                    textAlign = TextAlign.Start,
                )
                Text(
                    "Ya hay conexión con el backend. Elige sobre qué proyecto " +
                        "quieres trabajar para acceder a Agentes, Jobs, Plan y Scripts.",
                )
                Button(
                    onClick = onOpenContextSheet,
                    modifier = Modifier.fillMaxSize().height(48.dp),
                ) {
                    Text("Elegir proyecto")
                }
            }
        }
    }
}

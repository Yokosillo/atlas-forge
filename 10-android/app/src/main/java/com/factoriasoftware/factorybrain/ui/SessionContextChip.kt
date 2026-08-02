package com.factoriasoftware.factorybrain.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/**
 * Componente de contexto de sesión persistente (T-FB017-US03-01):
 * fusiona `HealthCheckScreen` y `ProjectScreen` en un único elemento
 * visible desde cualquier pantalla operativa (Agentes, Jobs, Plan,
 * Scripts) — antes de esta Task, saber "¿estoy conectado? ¿a qué
 * proyecto?" exigía navegar a dos pantallas de verificación aparte,
 * indistinguibles en la lista de destinos de las 4 pantallas de trabajo
 * real (hallazgo de la auditoría de arquitectura de información,
 * US-FB017-03).
 *
 * ## Reutilización sin duplicar lógica (criterio de aceptación explícito)
 *
 * Este componente NO reimplementa `HealthCheckViewModel`/`ProjectViewModel`
 * — solo LEE sus `StateFlow` ya expuestos (`state`/`baseUrl` del primero,
 * `uiState` del segundo) para componer el texto del chip, y al tocarlo
 * monta `HealthCheckScreen`/`ProjectScreen` tal cual dentro de un
 * `ModalBottomSheet` — mismos `@Composable` ya construidos en
 * T-FB017-US01-01/-05, sin ninguna copia de su contenido. El cambio es
 * puramente de CONTENEDOR (dos pantallas de nivel superior → una hoja
 * modal), no de comportamiento.
 *
 * ## Por qué el estado no se comparte vía un ViewModel nuevo a nivel de
 * MainActivity (punto 3 de la Descripción de la Task)
 *
 * Se evaluó introducir un `SessionContextViewModel` compartido que
 * envolviera a los otros dos. Se descartó: `HealthCheckViewModel` y
 * `ProjectViewModel` YA son instancias únicas a nivel de `MainActivity`
 * (`by viewModels()`, ver `MainActivity.kt`) — cualquier `@Composable`
 * que reciba esas MISMAS instancias ya observa el mismo estado
 * compartido sin ningún mecanismo adicional, `StateFlow` ya es
 * multicast por diseño. Envolverlos en un tercer `ViewModel` solo para
 * "propagarlos" habría sido una capa de indirección sin ningún problema
 * real que resolver — se pasan las mismas dos instancias de
 * `MainActivity` a este componente y a las 4 pantallas operativas,
 * exactamente igual que ya se hacía con `healthCheckViewModel`/
 * `projectViewModel` antes de esta Task.
 */
/**
 * Deriva si hay conexión real con el backend a partir de
 * [HealthCheckState] — función pura extraída para poder testearla sin
 * `@Composable`, mismo criterio ya aplicado en el resto de la app
 * (`visibleAgentsFor`, `agentsWithRunningJob`, `colorForAgentStatus`).
 */
internal fun isBackendConnected(state: HealthCheckState): Boolean = state is HealthCheckState.Success

/**
 * Nombre del proyecto activo a partir de [ProjectUiState], o `null` si
 * todavía no se cargó o no hay ninguno seleccionado — mismos dos casos
 * ("aún cargando" y "sin proyecto") se muestran igual en el chip
 * ("ninguno"), ya que ninguno de los dos tiene un nombre real que
 * mostrar todavía.
 */
internal fun activeProjectNameFor(state: ProjectUiState): String? =
    (state as? ProjectUiState.Loaded)?.activeProject?.name

/**
 * Texto completo del chip de contexto — combina las dos derivaciones
 * anteriores en el formato pedido por la Task ("● Conectado · Proyecto:
 * nombre-real" / "○ Sin conexión" / "Sin proyecto").
 */
internal fun sessionContextText(isConnected: Boolean, projectName: String?): String =
    buildString {
        append(if (isConnected) "Conectado" else "Sin conexión")
        append(" · Proyecto: ")
        append(projectName ?: "ninguno")
    }

/**
 * ¿El contexto de sesión está completo (T-FB017-US03-02)? — condiciona
 * si `MainActivity` muestra la `NavigationBar` operativa y las 4
 * pantallas de trabajo, o el hueco reservado para T-FB017-US03-03
 * (onboarding). Reutiliza [isBackendConnected]/[activeProjectNameFor]
 * (ya construidas en T-FB017-US03-01) en vez de reimplementar la lógica
 * de "¿hay conexión? ¿hay proyecto?" — este predicado solo combina
 * ambas con Y lógico, sin ninguna decisión nueva.
 */
internal fun isSessionContextResolved(isConnected: Boolean, projectName: String?): Boolean =
    isConnected && projectName != null

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SessionContextChip(
    healthCheckViewModel: HealthCheckViewModel,
    projectViewModel: ProjectViewModel,
    // T-FB017-US03-03: estado elevado (no `remember` interno) para que el
    // flujo de onboarding (`OnboardingFlow.kt`) pueda abrir esta MISMA
    // hoja modal desde su botón de acción ("ruta directa", criterio de
    // Nielsen Norman Group 3) — sin este parámetro, el onboarding solo
    // podría duplicar el contenido de `HealthCheckScreen`/`ProjectScreen`
    // en otro sitio, en vez de reutilizar el único punto de entrada ya
    // construido en T-FB017-US03-01. `false` por defecto: ningún llamador
    // existente antes de esta Task necesita cambiar su código.
    showContextSheet: Boolean = false,
    onShowContextSheetChange: (Boolean) -> Unit = {},
) {
    val healthState by healthCheckViewModel.state.collectAsState()
    val projectUiState by projectViewModel.uiState.collectAsState()

    val isConnected = isBackendConnected(healthState)
    val projectName = activeProjectNameFor(projectUiState)

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onShowContextSheetChange(true) }
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        // Indicador de color complementario al texto (mismo criterio ya
        // aplicado en `colorForAgentStatus`, T-FB017-US04-05: nunca
        // sustituye al texto, solo lo refuerza visualmente).
        Box(
            modifier = Modifier
                .size(10.dp)
                .clip(CircleShape)
                .background(if (isConnected) Color(0xFF4CAF50) else Color(0xFF9E9E9E)),
        )
        Text(
            text = sessionContextText(isConnected, projectName),
            style = MaterialTheme.typography.bodyMedium,
        )
    }

    if (showContextSheet) {
        val sheetState = rememberModalBottomSheetState()
        ModalBottomSheet(
            onDismissRequest = { onShowContextSheetChange(false) },
            sheetState = sheetState,
        ) {
            SessionContextSheetContent(
                healthCheckViewModel = healthCheckViewModel,
                projectViewModel = projectViewModel,
            )
        }
    }
}

/**
 * Contenido de la hoja modal: `HealthCheckScreen` y `ProjectScreen`
 * reales, una debajo de la otra, con altura acotada por scroll propio
 * (cada una ya usa `Modifier.fillMaxSize()` internamente — dentro de un
 * `ModalBottomSheet`, que no impone una altura infinita como
 * `fillMaxSize` esperaría, se les da una altura fija razonable en su
 * lugar para que ambas quepan sin recortarse).
 */
@Composable
private fun SessionContextSheetContent(
    healthCheckViewModel: HealthCheckViewModel,
    projectViewModel: ProjectViewModel,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 24.dp),
    ) {
        Box(modifier = Modifier.fillMaxWidth().height(320.dp)) {
            HealthCheckScreen(viewModel = healthCheckViewModel)
        }
        Box(modifier = Modifier.fillMaxWidth().height(400.dp)) {
            ProjectScreen(viewModel = projectViewModel)
        }
    }
}

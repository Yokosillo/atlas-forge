package com.factoriasoftware.factorybrain.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.factoriasoftware.factorybrain.net.AgentDto
import com.factoriasoftware.factorybrain.net.BacklogEpicDto
import com.factoriasoftware.factorybrain.net.BacklogItemDetailDto
import com.factoriasoftware.factorybrain.net.BacklogItemStateDto

/**
 * Pantalla de Backlog (T-FB020-US01-02): lista de Epics del proyecto
 * activo con conteo de sus User Stories por estado (`GET /backlog`,
 * criterio 1); tocar una despliega sus User Stories con el mismo
 * desglose (`GET /backlog/{epicId}`, criterio 2); tocar una User Story
 * navega a su detalle completo — objetivo, criterios de aceptación,
 * Tasks con estado (`GET /backlog/{itemId}`, criterio 3). Navegación
 * pantalla-por-nivel dentro del mismo Composable (mismo patrón ya usado
 * en `PlanScreen`/`ScriptsScreen`: un `when` sobre el estado, sin
 * `NavHost`), con botón "Volver" explícito en cada nivel salvo el
 * primero.
 *
 * T-FB020-US03-01: código de color por estado (`colorForBacklogState`),
 * progreso agregado por Epic (`EpicCard`) y expandir/colapsar in-place
 * (`EpicListView`) — sin tocar los endpoints, todo derivado de los
 * mismos campos que `GET /backlog`/`GET /backlog/{item_id}` ya traían.
 */
/**
 * Color asociado al `state` literal de un item de backlog (Epic/US/Task)
 * — indicador visual complementario, NUNCA sustituto del texto de estado
 * ya existente (mismo criterio de accesibilidad que `colorForAgentStatus`,
 * `AgentsScreen.kt`). Mismos valores fijos ya validados con WCAG 1.4.11
 * (≥3:1 sobre los fondos de tema claro `0xFFFAFDFD`/oscuro `0xFF191C1C`,
 * ver `ContrastRatioTest.kt`) — NO se reinventa una paleta nueva, se
 * reutiliza literalmente `colorForAgentStatus("idle")`/`"working"`/
 * `"stopped"` (mismo verde/ámbar/gris, distinto significado de dominio).
 *
 * El backend compara el `state` de un item por IGUALDAD EXACTA contra
 * `"DONE"`/`"TODO"` (`brain/models/backlog.py::STATE_DONE`/`STATE_TODO`,
 * `parser.py::classify_todo_items`) — un valor como
 * `"DONE (aplicada directamente por el crítico...)"` (caso real
 * verificado en el backlog de este proyecto) NO es `state == "DONE"`
 * para el propio dominio, así que tampoco lo es aquí: cae al gris neutro
 * de "estado no reconocido" (criterio de aceptación explícito de esta
 * Task — nunca se confunde con `DONE`/`TODO` por defecto), coherente con
 * el propio backend en vez de una heurística de texto libre inventada
 * aquí.
 */
internal fun colorForBacklogState(state: String?): Color = when (state) {
    "DONE" -> Color(0xFF2E7D32) // verde (Green 800) — mismo valor que colorForAgentStatus("idle")
    "TODO" -> Color(0xFFEF6C00) // ámbar/naranja (Orange 800) — mismo valor que colorForAgentStatus("working")
    else -> Color(0xFF757575) // gris (Grey 600) — estado no reconocido, nunca DONE/TODO por defecto
}

/**
 * Indicador de color (10dp, círculo) junto al texto de estado — mismo
 * tamaño/forma que el indicador de `AgentsScreen.kt` (`Box().size(10.dp)
 * .clip(CircleShape).background(color)`), nunca en lugar del texto.
 */
@Composable
private fun BacklogStateDot(state: String?) {
    Box(
        modifier = Modifier
            .size(10.dp)
            .clip(CircleShape)
            .background(colorForBacklogState(state)),
    )
}
@Composable
fun BacklogScreen(viewModel: BacklogViewModel) {
    val uiState by viewModel.uiState.collectAsState()
    val developerAgents by viewModel.developerAgents.collectAsState()
    val launchDevelopmentState by viewModel.launchDevelopmentState.collectAsState()

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text("Backlog", style = MaterialTheme.typography.headlineMedium)

        Box(modifier = Modifier.weight(1f)) {
            when (val state = uiState) {
                is BacklogUiState.Loading -> Text("Cargando…", modifier = Modifier.padding(vertical = 8.dp))
                is BacklogUiState.Unavailable -> Text(
                    "No se pudo contactar con el backend: ${state.message}",
                    modifier = Modifier.padding(vertical = 8.dp),
                )
                is BacklogUiState.EpicList -> EpicListView(
                    epics = state.epics,
                    onEpicSelected = viewModel::openEpic,
                )
                is BacklogUiState.EpicDetail -> EpicDetailView(
                    detail = state.detail,
                    onUserStorySelected = viewModel::openItem,
                    onBack = viewModel::goBack,
                )
                is BacklogUiState.ItemDetail -> ItemDetailView(
                    detail = state.detail,
                    onBack = viewModel::goBack,
                    developerAgents = developerAgents,
                    launchDevelopmentState = launchDevelopmentState,
                    onLaunchDevelopment = { agentId -> viewModel.launchDevelopment(state.detail.id, agentId) },
                )
            }
        }
    }
}

@Composable
private fun EpicListView(
    epics: List<BacklogEpicDto>,
    onEpicSelected: (String) -> Unit,
) {
    if (epics.isEmpty()) {
        // Criterio de aceptación explícito de T-FB020-US01-01 (`empty`
        // del informe): un backlog sin Epics todavía es un resultado
        // válido, no un error — se muestra como lista vacía.
        Text(
            "El backlog está vacío (aún no hay Epics/User Stories).",
            modifier = Modifier.padding(vertical = 8.dp),
        )
        return
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(epics, key = { it.epic }) { epic ->
            EpicCard(epic = epic, onClick = { onEpicSelected(epic.epic) })
        }
    }
}

/**
 * Progreso agregado `DONE / total` de una Epic (T-FB020-US03-01, criterio
 * de aceptación 2) — función pura extraída para testearla sin Compose,
 * mismo criterio ya aplicado a `epicIdFromLabel`/`mostRecentPendingPlan`.
 *
 * Decisión documentada (la Task deja elegir US o Tasks, "documentar la
 * elección"): se usa el conteo de **User Stories**, no de Tasks. Motivo:
 * `by_epic` (`GET /backlog`) puede traer una Epic con Tasks pero sin
 * ninguna US todavía decompuesta a nivel raíz del backlog (caso real:
 * Tasks huérfanas de una US ya `DONE` que no vuelve a aparecer en
 * `by_epic` si esa US ya no tiene Tasks TODO) — las User Stories son la
 * unidad de valor que el propio backlog usa para medir avance de producto
 * (`01-documentacion`, convención ya establecida), más estable como
 * denominador que el conteo de Tasks (que puede crecer/decrecer según el
 * nivel de descomposición elegido para cada US). Si una Epic no tiene
 * ninguna User Story todavía (`total == 0`), se considera `0f` (ninguna
 * evidencia de progreso, no un `NaN`/división por cero).
 */
internal fun epicProgressFraction(epic: BacklogEpicDto): Float {
    val total = epic.user_stories.values.sum()
    if (total == 0) return 0f
    val done = epic.user_stories["DONE"] ?: 0
    return done.toFloat() / total.toFloat()
}

@Composable
private fun EpicCard(epic: BacklogEpicDto, onClick: () -> Unit) {
    // T-FB020-US03-01, criterio de aceptación 3: expandir/colapsar el
    // desglose sin abandonar el listado. Convive con la navegación de
    // drill-down ya construida en T-FB020-US01-02 (decisión documentada
    // en el docstring de módulo): expandir muestra el mismo resumen
    // agregado por estado ya visible hoy (ahora con color), tocar el
    // resto de la tarjeta sigue navegando al detalle completo de la Epic
    // (sus User Stories una a una, con id y estado) — mismo criterio
    // "resumen rápido vs. detalle completo" que la propia Task sugiere.
    // Estado puramente de presentación (`remember`, no ViewModel): mismo
    // patrón ya usado para `showStopped` en `AgentsScreen.kt` — no
    // necesita sobrevivir a la muerte del proceso ni compartirse entre
    // pantallas.
    var isExpanded by remember { mutableStateOf(false) }
    val doneUserStories = epic.user_stories["DONE"] ?: 0
    val totalUserStories = epic.user_stories.values.sum()

    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(epic.epic, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                Button(onClick = { isExpanded = !isExpanded }) {
                    Text(if (isExpanded) "Colapsar" else "Expandir")
                }
            }

            if (totalUserStories > 0) {
                LinearProgressIndicator(
                    progress = { epicProgressFraction(epic) },
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                )
                Text(
                    "User Stories: $doneUserStories/$totalUserStories DONE",
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }

            if (isExpanded) {
                if (epic.user_stories.isNotEmpty()) {
                    Text(
                        "US:",
                        style = MaterialTheme.typography.labelMedium,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                    epic.user_stories.entries.sortedBy { it.key }.forEach { (state, count) ->
                        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 2.dp)) {
                            BacklogStateDot(state)
                            Text(" $state = $count", modifier = Modifier.padding(start = 4.dp))
                        }
                    }
                }
                if (epic.tasks.isNotEmpty()) {
                    Text(
                        "Task:",
                        style = MaterialTheme.typography.labelMedium,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                    epic.tasks.entries.sortedBy { it.key }.forEach { (state, count) ->
                        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 2.dp)) {
                            BacklogStateDot(state)
                            Text(" $state = $count", modifier = Modifier.padding(start = 4.dp))
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun EpicDetailView(
    detail: BacklogItemDetailDto,
    onUserStorySelected: (String) -> Unit,
    onBack: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxSize()) {
        Button(onClick = onBack, modifier = Modifier.padding(bottom = 8.dp)) {
            Text("Volver a Epics")
        }
        Text(detail.id, style = MaterialTheme.typography.titleLarge)
        ParseWarningBanner(detail.parse_warning)
        Text(
            detail.objetivo ?: "(sin objetivo declarado)",
            modifier = Modifier.padding(vertical = 8.dp),
        )
        Text("User Stories:", style = MaterialTheme.typography.titleSmall)
        if (detail.user_stories.isEmpty()) {
            Text("(ninguna)", modifier = Modifier.padding(vertical = 4.dp))
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxWidth(),
                contentPadding = PaddingValues(vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(detail.user_stories, key = { it.id }) { userStory ->
                    ItemStateCard(item = userStory, onClick = { onUserStorySelected(userStory.id) })
                }
            }
        }
    }
}

@Composable
private fun ItemDetailView(
    detail: BacklogItemDetailDto,
    onBack: () -> Unit,
    developerAgents: List<AgentDto> = emptyList(),
    launchDevelopmentState: LaunchDevelopmentState = LaunchDevelopmentState.Idle,
    onLaunchDevelopment: (agentId: String) -> Unit = {},
) {
    Column(modifier = Modifier.fillMaxSize()) {
        Button(onClick = onBack, modifier = Modifier.padding(bottom = 8.dp)) {
            Text("Volver")
        }
        Text(detail.id, style = MaterialTheme.typography.titleLarge)
        Row(verticalAlignment = Alignment.CenterVertically) {
            BacklogStateDot(detail.state)
            Text(" Estado: ${detail.state ?: "desconocido"}", modifier = Modifier.padding(start = 4.dp))
        }
        if (detail.epic != null) {
            Text("Epic: ${detail.epic}")
        }
        ParseWarningBanner(detail.parse_warning)

        Text("Objetivo:", style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 8.dp))
        Text(detail.objetivo ?: "(sin objetivo declarado)")

        Text(
            "Criterios de aceptación:",
            style = MaterialTheme.typography.titleSmall,
            modifier = Modifier.padding(top = 8.dp),
        )
        Text(detail.criterios_aceptacion ?: "(sin criterios declarados)")

        // Solo presente para una User Story (`kind == "US"`) — una Task
        // no trae este campo (backend: `build_item_detail`,
        // `brain/backlog/detail.py`). "Lanzar desarrollo"
        // (T-FB020-US02-02) es también exclusivo de una User Story, mismo
        // criterio: el endpoint `POST /backlog/{story_id}/launch-development`
        // (T-FB020-US02-01) solo acepta ids de User Story.
        if (detail.kind == "US") {
            Text("Tasks:", style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 8.dp))
            if (detail.tasks.isEmpty()) {
                Text("(ninguna)", modifier = Modifier.padding(vertical = 4.dp))
            } else {
                LazyColumn(
                    modifier = Modifier.fillMaxWidth(),
                    contentPadding = PaddingValues(vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(detail.tasks, key = { it.id }) { task ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            BacklogStateDot(task.state)
                            Text(" ${task.id} — ${task.state}", modifier = Modifier.padding(start = 4.dp))
                        }
                    }
                }
            }

            LaunchDevelopmentSection(
                developerAgents = developerAgents,
                launchDevelopmentState = launchDevelopmentState,
                onLaunchDevelopment = onLaunchDevelopment,
            )
        }
    }
}

/**
 * "Lanzar desarrollo" (T-FB020-US02-02): elegir un agente Developer ya
 * lanzado (mismo catálogo/patrón `DropdownMenu` que `JobsScreen`, no un
 * selector nuevo) y despachar `POST /backlog/{story_id}/launch-development`
 * (T-FB020-US02-01) sin escribir ninguna descripción a mano — el backend
 * la resuelve del objetivo + Tasks `TODO` de la propia US.
 */
@Composable
private fun LaunchDevelopmentSection(
    developerAgents: List<AgentDto>,
    launchDevelopmentState: LaunchDevelopmentState,
    onLaunchDevelopment: (agentId: String) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    var selectedAgent by remember(developerAgents) { mutableStateOf(developerAgents.firstOrNull()) }
    val isLaunching = launchDevelopmentState is LaunchDevelopmentState.Launching

    Column(modifier = Modifier.fillMaxWidth().padding(top = 16.dp)) {
        Text("Lanzar desarrollo", style = MaterialTheme.typography.titleSmall)

        if (developerAgents.isEmpty()) {
            Text(
                "No hay ningún agente Developer lanzado en la sesión activa. " +
                    "Lanza uno desde la pantalla Agentes antes de lanzar el desarrollo.",
                modifier = Modifier.padding(top = 4.dp),
            )
            return@Column
        }

        Box(modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) {
            Button(
                onClick = { expanded = true },
                enabled = !isLaunching,
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                Text(selectedAgent?.let { "${it.name} (${it.role})" } ?: "Elige agente Developer")
            }
            DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                developerAgents.forEach { agent ->
                    DropdownMenuItem(
                        text = { Text("${agent.name} (${agent.role})") },
                        onClick = {
                            selectedAgent = agent
                            expanded = false
                        },
                    )
                }
            }
        }

        Button(
            onClick = {
                val agentId = selectedAgent?.id ?: return@Button
                onLaunchDevelopment(agentId)
            },
            enabled = !isLaunching && selectedAgent != null,
            modifier = Modifier.fillMaxWidth().height(48.dp).padding(top = 8.dp),
        ) {
            if (isLaunching) {
                CircularProgressIndicator(modifier = Modifier.size(20.dp))
            } else {
                Text("Lanzar desarrollo")
            }
        }

        when (launchDevelopmentState) {
            is LaunchDevelopmentState.Finished -> Text(
                "Job despachado (${launchDevelopmentState.job.status}) — visible en la pantalla Jobs.",
                modifier = Modifier.padding(top = 8.dp),
            )
            is LaunchDevelopmentState.Error -> Text(
                // Criterio de aceptación explícito: el motivo REAL del
                // backend (p. ej. "La User Story US-... no tiene Tasks
                // pendientes; no se lanza un Job vacío."), nunca un
                // mensaje genérico.
                launchDevelopmentState.message,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(top = 8.dp),
            )
            else -> {}
        }
    }
}

@Composable
private fun ItemStateCard(item: BacklogItemStateDto, onClick: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
    ) {
        Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
            Text(item.id, style = MaterialTheme.typography.titleMedium)
            Row(verticalAlignment = Alignment.CenterVertically) {
                BacklogStateDot(item.state)
                Text(" Estado: ${item.state}", modifier = Modifier.padding(start = 4.dp))
            }
        }
    }
}

/**
 * Aviso explícito de sección mal formada (criterio de aceptación
 * explícito: "un fichero mal formado se refleja como aviso explícito en
 * su entrada, sin romper la vista completa") — el resto del detalle
 * disponible se muestra igual (`objetivo`/`criterios_aceptacion` como
 * `null`, ya manejado por sus placeholders), esto solo añade el aviso
 * visible encima.
 */
@Composable
private fun ParseWarningBanner(parseWarning: String?) {
    if (parseWarning != null) {
        Text(
            "⚠ $parseWarning",
            color = MaterialTheme.colorScheme.error,
            modifier = Modifier.padding(vertical = 4.dp),
        )
    }
}

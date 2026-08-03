package com.factoriasoftware.factorybrain.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
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
 */
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

@Composable
private fun EpicCard(epic: BacklogEpicDto, onClick: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
    ) {
        Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
            Text(epic.epic, style = MaterialTheme.typography.titleMedium)
            if (epic.user_stories.isNotEmpty()) {
                Text(
                    "US: " + epic.user_stories.entries.sortedBy { it.key }
                        .joinToString(", ") { "${it.key}=${it.value}" }
                )
            }
            if (epic.tasks.isNotEmpty()) {
                Text(
                    "Task: " + epic.tasks.entries.sortedBy { it.key }
                        .joinToString(", ") { "${it.key}=${it.value}" }
                )
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
        Text("Estado: ${detail.state ?: "desconocido"}")
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
                        Text("${task.id} — ${task.state}")
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
            Text("Estado: ${item.state}")
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

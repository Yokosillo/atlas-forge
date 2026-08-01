package com.factoriasoftware.factorybrain.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.factoriasoftware.factorybrain.net.ProjectDto

/**
 * Pantalla de selección de proyecto (T-FB017-US01-05): lista de
 * repositorios descubiertos con controles táctiles, proyecto activo
 * siempre visible (criterio de aceptación explícito), y confirmación
 * previa si hay agentes activos en la sesión que se va a descartar
 * (ver `ProjectViewModel` para la justificación completa del aviso).
 */
@Composable
fun ProjectScreen(viewModel: ProjectViewModel) {
    val uiState by viewModel.uiState.collectAsState()
    val actionMessage by viewModel.actionMessage.collectAsState()
    val pendingSelection by viewModel.pendingSelection.collectAsState()

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text("Proyecto", style = MaterialTheme.typography.headlineMedium)

        actionMessage?.let {
            Text(it, modifier = Modifier.padding(vertical = 8.dp))
        }

        when (val state = uiState) {
            is ProjectUiState.Loading -> Text("Cargando…", modifier = Modifier.padding(vertical = 8.dp))
            is ProjectUiState.Unavailable -> Text(
                "No se pudo contactar con el backend: ${state.message}",
                modifier = Modifier.padding(vertical = 8.dp),
            )
            is ProjectUiState.Loaded -> {
                Text(
                    text = state.activeProject?.let { "Proyecto activo: ${it.name}" }
                        ?: "Proyecto activo: ninguno",
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(vertical = 8.dp),
                )

                ProjectsList(
                    projects = state.projects,
                    activeProjectId = state.activeProject?.id,
                    onSelect = viewModel::requestSelectProject,
                )
            }
        }
    }

    pendingSelection?.let { pending ->
        AlertDialog(
            onDismissRequest = viewModel::cancelPendingSelection,
            title = { Text("Cambiar de proyecto") },
            text = {
                Text(
                    "Hay ${pending.activeAgentsCount} agente(s) activo(s) en la sesión " +
                        "actual. Cambiar a '${pending.project.name}' los detendrá. ¿Continuar?"
                )
            },
            confirmButton = {
                TextButton(onClick = viewModel::confirmPendingSelection) {
                    Text("Cambiar de todos modos")
                }
            },
            dismissButton = {
                TextButton(onClick = viewModel::cancelPendingSelection) {
                    Text("Cancelar")
                }
            },
        )
    }
}

@Composable
private fun ProjectsList(
    projects: List<ProjectDto>,
    activeProjectId: String?,
    onSelect: (ProjectDto) -> Unit,
) {
    if (projects.isEmpty()) {
        Text("No se ha descubierto ningún repositorio.", modifier = Modifier.padding(vertical = 8.dp))
        return
    }

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(projects, key = { it.id }) { project ->
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
                    Text(project.name, style = MaterialTheme.typography.titleMedium)
                    Text(project.path)
                    if (project.id == activeProjectId) {
                        Text("Activo", style = MaterialTheme.typography.labelMedium)
                    } else {
                        Button(
                            onClick = { onSelect(project) },
                            modifier = Modifier.fillMaxWidth().height(48.dp),
                        ) {
                            Text("Seleccionar")
                        }
                    }
                }
            }
        }
    }
}

package com.factoriasoftware.factorybrain.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.factoriasoftware.factorybrain.net.AgentDto
import com.factoriasoftware.factorybrain.net.JobDto

/**
 * Pantalla de Jobs (T-FB017-US01-03): formulario de creación, progreso en
 * tiempo real (vía `WS /ws/jobs`, ver `JobsViewModel`), resultado
 * completo sin truncar con scroll (criterio de aceptación explícito,
 * mismo criterio ya aplicado en la pantalla Jobs de la TUI), e histórico
 * de la sesión.
 */
@Composable
fun JobsScreen(viewModel: JobsViewModel) {
    val agents by viewModel.agents.collectAsState()
    val history by viewModel.history.collectAsState()
    val progress by viewModel.progress.collectAsState()

    // T-FB017-US04-04: elevado desde CreateJobForm para que
    // JobHistoryList pueda rellenarlo directamente al tocar una entrada
    // ("Usar como Job previo") — mismo campo que el usuario también puede
    // seguir tecleando a mano (criterio de aceptación explícito: "mantener
    // el campo de texto libre como alternativa").
    var previousJobId by remember { mutableStateOf("") }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text("Jobs", style = MaterialTheme.typography.headlineMedium)

        val isDispatching = progress is JobProgressState.InProgress
        CreateJobForm(
            agents = agents,
            onSubmit = viewModel::createAndDispatchJob,
            isDispatching = isDispatching,
            previousJobId = previousJobId,
            onPreviousJobIdChange = { previousJobId = it },
        )

        val isCancelling by viewModel.isCancelling.collectAsState()
        ProgressSection(progress, onCancel = viewModel::cancelJob, isCancelling = isCancelling)

        Text(
            "Histórico de Jobs de la sesión",
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.padding(top = 16.dp),
        )
        JobHistoryList(history, onUseAsPreviousJob = { previousJobId = it })
    }
}

@Composable
private fun CreateJobForm(
    agents: List<AgentDto>,
    onSubmit: (agentId: String, description: String, previousJobId: String?) -> Unit,
    isDispatching: Boolean = false,
    previousJobId: String = "",
    onPreviousJobIdChange: (String) -> Unit = {},
) {
    var expanded by remember { mutableStateOf(false) }
    var selectedAgent by remember(agents) { mutableStateOf(agents.firstOrNull()) }
    var description by remember { mutableStateOf("") }

    Column(
        modifier = Modifier.fillMaxWidth().padding(top = 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (agents.isEmpty()) {
            Text(
                "No hay ningún agente lanzado en la sesión activa. Lanza un " +
                    "agente desde la pantalla Agentes antes de crear un Job."
            )
            return@Column
        }

        Box(modifier = Modifier.fillMaxWidth()) {
            Button(
                onClick = { expanded = true },
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                Text(selectedAgent?.let { "${it.name} (${it.role})" } ?: "Elige agente destinatario")
            }
            DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                agents.forEach { agent ->
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

        OutlinedTextField(
            value = description,
            onValueChange = { description = it },
            label = { Text("Describe la tarea") },
            modifier = Modifier.fillMaxWidth(),
        )

        OutlinedTextField(
            value = previousJobId,
            onValueChange = onPreviousJobIdChange,
            // Sigue siendo un campo de texto libre editable (criterio de
            // aceptación explícito de la Task: no todo caso de uso tiene
            // el Job previo visible en el histórico ya cargado, p. ej. de
            // una sesión anterior) — "Usar como Job previo" en el
            // histórico solo lo RELLENA, no sustituye esta alternativa.
            label = { Text("Job previo a encadenar (opcional, o tócalo en el histórico)") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
        )

        Button(
            onClick = {
                val agentId = selectedAgent?.id ?: return@Button
                if (description.isBlank()) return@Button
                onSubmit(agentId, description.trim(), previousJobId.trim().ifBlank { null })
            },
            enabled = !isDispatching,
            modifier = Modifier.fillMaxWidth().height(48.dp),
        ) {
            if (isDispatching) {
                CircularProgressIndicator(modifier = Modifier.size(20.dp))
            } else {
                Text("Enviar")
            }
        }
    }
}

@Composable
private fun ProgressSection(
    progress: JobProgressState,
    onCancel: (String) -> Unit = {},
    isCancelling: Boolean = false,
) {
    Column(modifier = Modifier.padding(top = 16.dp)) {
        when (progress) {
            is JobProgressState.Idle -> Text("Sin ningún Job en curso.")
            is JobProgressState.InProgress -> {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text("Job en curso (${progress.status})…")
                    // T-FB017-US04-05: acción DISTINTA de "Detener agente"
                    // (AgentsScreen) — texto e icono propios ("Cancelar
                    // Job" + ⨯, frente a "Detener" + el botón normal de
                    // AgentsScreen) para que quede claro que el alcance es
                    // solo esta tarea concreta, no el agente completo.
                    // Solo disponible cuando ya se conoce el `jobId` real
                    // (el evento job_status inicial `created` llega vía
                    // WebSocket casi de inmediato, ver JobsViewModel).
                    if (progress.jobId.isNotBlank()) {
                        TextButton(
                            onClick = { onCancel(progress.jobId) },
                            enabled = !isCancelling,
                        ) {
                            if (isCancelling) {
                                CircularProgressIndicator(modifier = Modifier.size(16.dp))
                            } else {
                                Text("✕ Cancelar Job")
                            }
                        }
                    }
                }
            }
            is JobProgressState.Error -> Text("Error: ${progress.message}")
            is JobProgressState.Finished -> {
                val job = progress.job
                val label = when (job.status) {
                    "completed" -> "Job completado"
                    "cancelled" -> "Job cancelado"
                    else -> "Job falló (${job.status})"
                }
                Text(label, style = MaterialTheme.typography.titleMedium)
                // Resultado completo, sin truncar, con scroll propio si es
                // largo (criterio de aceptación explícito).
                Text(
                    text = job.result ?: "(sin resultado)",
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(max = 240.dp)
                        .verticalScroll(rememberScrollState())
                        .padding(top = 8.dp),
                )
            }
        }
    }
}

@Composable
private fun JobHistoryList(history: List<JobDto>, onUseAsPreviousJob: (String) -> Unit) {
    // T-FB017-US04-04: tocar una entrada abre un diálogo de detalle con
    // el resultado COMPLETO (sin el truncado a 200 caracteres que ya
    // tenía la tarjeta) y, si el Job está `completed` (único estado que
    // `create_job(..., previous_job=...)` acepta encadenar — ver
    // `job_creation.py`, criterio de aceptación de US-FB008-02, ya
    // verificado en el dominio, no reimplementado aquí), la acción "Usar
    // como Job previo".
    var selectedJob by remember { mutableStateOf<JobDto?>(null) }

    selectedJob?.let { job ->
        AlertDialog(
            onDismissRequest = { selectedJob = null },
            title = { Text("Job [${job.status}]") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(job.description)
                    Text(
                        text = job.result ?: "(sin resultado todavía)",
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(max = 300.dp)
                            .verticalScroll(rememberScrollState()),
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            },
            confirmButton = {
                if (job.status == "completed") {
                    TextButton(onClick = {
                        onUseAsPreviousJob(job.id)
                        selectedJob = null
                    }) { Text("Usar como Job previo") }
                }
            },
            dismissButton = {
                TextButton(onClick = { selectedJob = null }) { Text("Cerrar") }
            },
        )
    }

    if (history.isEmpty()) {
        Text("Todavía no se ha creado ningún Job en esta sesión.", modifier = Modifier.padding(vertical = 8.dp))
        return
    }

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(history, key = { it.id }) { job ->
            Card(
                modifier = Modifier.fillMaxWidth().clickable { selectedJob = job },
            ) {
                Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
                    Text("[${job.status}] ${job.description.lineSequence().first().take(80)}")
                    Text(
                        text = job.result?.take(200) ?: "(sin resultado todavía)",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }
    }
}

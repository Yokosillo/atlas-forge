package com.factoriasoftware.factorybrain.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.factoriasoftware.factorybrain.net.BacklogReportDto
import com.factoriasoftware.factorybrain.net.ScriptEntryDto

// Único script del catálogo combinado que exige un parámetro (`message`),
// T-FB018-US01-03 — los particulares y el resto de genéricos se ejecutan
// sin parámetros adicionales (criterio de aceptación explícito).
private const val SCRIPT_WITH_MESSAGE_PARAM = "commit"

// Script del catálogo genérico cuyo resultado es el informe estructurado de
// T-FB018-US02-02 — se presenta con formato en pantalla (T-FB018-US02-04,
// criterio 3: "sin que el desarrollador tenga que interpretar JSON crudo").
private const val BACKLOG_STATUS_SCRIPT = "backlog_status"

/**
 * Presentación legible del informe estructurado de backlog-status
 * (T-FB018-US02-04): conteo por Epic, lista de Tasks listas y cadena de
 * mayor apalancamiento — el usuario no tiene que leer el JSON crudo.
 */
private fun formatBacklogStatus(data: BacklogReportDto): String {
    if (data.empty) {
        return "El backlog está vacío (aún no hay US/Tasks)."
    }
    val total = data.total
    val lines = mutableListOf("Estado del backlog:")
    lines += "  Total: ${total?.items ?: 0} items · ${total?.errors ?: 0} errores de parseo"
    val us = total?.user_stories.orEmpty()
    if (us.isNotEmpty()) {
        lines += "  US: " + us.entries.sortedBy { it.key }.joinToString(", ") { "${it.key}=${it.value}" }
    }
    val tasks = total?.tasks.orEmpty()
    if (tasks.isNotEmpty()) {
        lines += "  Task: " + tasks.entries.sortedBy { it.key }.joinToString(", ") { "${it.key}=${it.value}" }
    }

    lines += "\nConteo por Epic:"
    for (epic in data.by_epic) {
        val epicLine = StringBuilder("  ${epic.epic}")
        if (epic.user_stories.isNotEmpty()) {
            epicLine.append(" · US: ")
            epicLine.append(epic.user_stories.entries.sortedBy { it.key }.joinToString(", ") { "${it.key}=${it.value}" })
        }
        if (epic.tasks.isNotEmpty()) {
            epicLine.append(" · Task: ")
            epicLine.append(epic.tasks.entries.sortedBy { it.key }.joinToString(", ") { "${it.key}=${it.value}" })
        }
        lines += epicLine.toString()
    }

    lines += "\nTasks LISTA (listas para empezar):"
    if (data.items_lista.isNotEmpty()) {
        for (entry in data.items_lista) {
            lines += "  ${entry.id}"
        }
    } else {
        lines += "  (ninguna)"
    }

    lines += "\nCadena de mayor apalancamiento (próximo foco):"
    if (data.max_leverage_chain.isNotEmpty()) {
        lines += "  " + data.max_leverage_chain.joinToString(" → ") { it.id }
    } else {
        lines += "  (ninguna)"
    }

    return lines.joinToString("\n")
}

/**
 * Pantalla de Scripts (T-FB001-US03-03, T-FB018-US01-03): lista del
 * catálogo combinado (genéricos con `origin: "generic"` + particulares con
 * `origin: "particular"`) del proyecto activo con controles táctiles,
 * botón "Ejecutar" por script, resultado completo sin truncar, y para el
 * único script con parámetro obligatorio (`commit`) un campo de mensaje
 * que se pide antes de ejecutar (mismo criterio ya aplicado en
 * `JobsScreen`). La sección de la lista usa `Modifier.weight(1f)` desde el
 * inicio (lección aprendida en T-FB017-US01-06: un `LazyColumn` sin altura
 * acotada dentro de un `Column` no hace scroll con normalidad).
 */
@Composable
fun ScriptsScreen(viewModel: ScriptsViewModel) {
    val uiState by viewModel.uiState.collectAsState()
    val runState by viewModel.runState.collectAsState()
    var commitMessage by remember { mutableStateOf("") }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text("Scripts", style = MaterialTheme.typography.headlineMedium)

        Box(modifier = Modifier.weight(1f)) {
            when (val state = uiState) {
                is ScriptsUiState.Loading -> Text("Cargando…", modifier = Modifier.padding(vertical = 8.dp))
                is ScriptsUiState.Unavailable -> Text(
                    "No se pudo contactar con el backend: ${state.message}",
                    modifier = Modifier.padding(vertical = 8.dp),
                )
                is ScriptsUiState.Loaded -> ScriptsList(
                    scripts = state.scripts,
                    commitMessage = commitMessage,
                    onCommitMessageChange = { commitMessage = it },
                    onRun = { scriptId, message ->
                        viewModel.runScript(scriptId, message)
                    },
                    isRunning = runState is ScriptRunState.Running,
                )
            }
        }

        RunResultSection(runState)
    }
}

@Composable
private fun ScriptsList(
    scripts: List<ScriptEntryDto>,
    commitMessage: String,
    onCommitMessageChange: (String) -> Unit,
    onRun: (String, String?) -> Unit,
    isRunning: Boolean = false,
) {
    val generic = scripts.filter { it.origin == "generic" }
    val particular = scripts.filter { it.origin != "generic" }

    if (scripts.isEmpty()) {
        // Criterio de aceptación explícito: "un proyecto sin scripts... se
        // refleja correctamente, sin error" — lista vacía visible.
        Text(
            "No hay ningún script catalogado (sin sesión activa, o sin "
                + "catálogo genérico disponible).",
            modifier = Modifier.padding(vertical = 8.dp),
        )
        return
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (generic.isNotEmpty()) {
            item(key = "header-generic") {
                Text("Genéricos (Factory Brain)", style = MaterialTheme.typography.titleSmall)
            }
        }
        items(generic, key = { it.id }) { script ->
            ScriptCard(
                script = script,
                commitMessage = commitMessage,
                onCommitMessageChange = onCommitMessageChange,
                onRun = onRun,
                isRunning = isRunning,
            )
        }
        if (particular.isNotEmpty()) {
            item(key = "header-particular") {
                Text("Proyecto", style = MaterialTheme.typography.titleSmall)
            }
        }
        items(particular, key = { it.id }) { script ->
            ScriptCard(
                script = script,
                commitMessage = commitMessage,
                onCommitMessageChange = onCommitMessageChange,
                onRun = onRun,
                isRunning = isRunning,
            )
        }
    }
}

@Composable
private fun ScriptCard(
    script: ScriptEntryDto,
    commitMessage: String,
    onCommitMessageChange: (String) -> Unit,
    onRun: (String, String?) -> Unit,
    isRunning: Boolean,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
            Text(script.name, style = MaterialTheme.typography.titleMedium)
            if (script.description?.isNotBlank() == true) {
                Text(script.description, style = MaterialTheme.typography.bodySmall)
            }
            val needsMessage = script.id == SCRIPT_WITH_MESSAGE_PARAM
            if (needsMessage) {
                OutlinedTextField(
                    value = commitMessage,
                    onValueChange = onCommitMessageChange,
                    label = { Text("Mensaje del commit") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                )
            }
            Button(
                onClick = { onRun(script.id, if (needsMessage) commitMessage else null) },
                enabled = !isRunning && (!needsMessage || commitMessage.isNotBlank()),
                modifier = Modifier.fillMaxWidth().height(48.dp).padding(top = 8.dp),
            ) {
                if (isRunning) {
                    CircularProgressIndicator(modifier = Modifier.size(20.dp))
                } else {
                    Text("Ejecutar")
                }
            }
        }
    }
}

@Composable
private fun RunResultSection(runState: ScriptRunState) {
    Column(modifier = Modifier.padding(top = 16.dp)) {
        when (runState) {
            is ScriptRunState.Idle -> {}
            is ScriptRunState.Running -> Text("Ejecutando…")
            is ScriptRunState.Error -> Text("Error: ${runState.message}")
            is ScriptRunState.Finished -> {
                val result = runState.result
                val label = if (result.success) {
                    "Éxito (exit code ${result.exit_code})"
                } else if (result.exit_code != null) {
                    "Falló (exit code ${result.exit_code})"
                } else {
                    // El script nunca llegó a ejecutarse (id desconocido,
                    // manifiesto roto, timeout) — criterio de aceptación
                    // explícito: se refleja el motivo, sin romper la
                    // pantalla.
                    "No se pudo ejecutar: ${result.error_message}"
                }
                Text(label, style = MaterialTheme.typography.titleMedium)

                val output: String = when {
                    // T-FB018-US02-04: el informe estructurado de
                    // backlog-status se presenta con formato (conteo por
                    // Epic, Tasks listas, cadena de mayor apalancamiento),
                    // no como JSON crudo; la síntesis opcional en prosa
                    // (T-FB018-US02-03) se añade si llegó.
                    result.success && runState.scriptId == BACKLOG_STATUS_SCRIPT && result.data != null -> {
                        val text = formatBacklogStatus(result.data)
                        if (result.prose.isNullOrBlank()) text else "$text\n\nSíntesis en prosa:\n${result.prose}"
                    }
                    else -> listOf(result.stdout, result.stderr)
                        .filter { it.isNotBlank() }
                        .joinToString("\n")
                }
                if (output.isNotBlank()) {
                    Text(
                        text = output,
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
}

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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.factoriasoftware.factorybrain.net.ScriptEntryDto

/**
 * Pantalla de Scripts (T-FB001-US03-03): lista de scripts particulares
 * catalogados del proyecto activo con controles táctiles, botón
 * "Ejecutar" por script, y resultado completo sin truncar (mismo criterio
 * ya aplicado en `JobsScreen`). La sección de la lista usa
 * `Modifier.weight(1f)` desde el inicio (lección aprendida en
 * T-FB017-US01-06: un `LazyColumn` sin altura acotada dentro de un
 * `Column` no hace scroll con normalidad).
 */
@Composable
fun ScriptsScreen(viewModel: ScriptsViewModel) {
    val uiState by viewModel.uiState.collectAsState()
    val runState by viewModel.runState.collectAsState()

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
                    onRun = viewModel::runScript,
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
    onRun: (String) -> Unit,
    isRunning: Boolean = false,
) {
    if (scripts.isEmpty()) {
        // Criterio de aceptación explícito: "un proyecto sin scripts
        // particulares... se refleja correctamente, sin error" — lista
        // vacía visible, no un mensaje de error.
        Text(
            "El proyecto activo no tiene scripts particulares catalogados.",
            modifier = Modifier.padding(vertical = 8.dp),
        )
        return
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(scripts, key = { it.id }) { script ->
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
                    Text(script.name, style = MaterialTheme.typography.titleMedium)
                    if (script.description.isNotBlank()) {
                        Text(script.description, style = MaterialTheme.typography.bodySmall)
                    }
                    Button(
                        onClick = { onRun(script.id) },
                        enabled = !isRunning,
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

                val output = listOf(result.stdout, result.stderr)
                    .filter { it.isNotBlank() }
                    .joinToString("\n")
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

package com.factoriasoftware.factorybrain.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
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

/**
 * Pantalla mínima de verificación + ajuste de host (T-FB017-US01-01).
 * Controles de tamaño adecuado para tacto (mismo criterio ya fijado como
 * requisito general de la Story para las pantallas siguientes, US-FB017-01
 * criterio 2) — botón de acción y campo de texto amplios, sin depender de
 * atajos de teclado.
 */
@Composable
fun HealthCheckScreen(viewModel: HealthCheckViewModel) {
    val state by viewModel.state.collectAsState()
    val baseUrl by viewModel.baseUrl.collectAsState()
    var editableBaseUrl by remember(baseUrl) { mutableStateOf(baseUrl) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(
            text = "Factory Brain",
            style = MaterialTheme.typography.headlineMedium,
        )

        OutlinedTextField(
            value = editableBaseUrl,
            onValueChange = { editableBaseUrl = it },
            label = { Text("URL del backend") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
        )

        Button(
            onClick = { viewModel.updateBaseUrl(editableBaseUrl) },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Guardar URL")
        }

        Button(
            onClick = { viewModel.checkHealth() },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Comprobar conexión (GET /health)")
        }

        when (val current = state) {
            is HealthCheckState.Idle -> Text("Sin comprobar todavía.")
            is HealthCheckState.Loading -> Text("Comprobando…")
            is HealthCheckState.Success -> Text("OK: ${current.body}")
            is HealthCheckState.Failure -> Text("Error: ${current.message}")
        }
    }
}

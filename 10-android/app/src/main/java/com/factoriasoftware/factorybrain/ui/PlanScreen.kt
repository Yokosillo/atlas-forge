package com.factoriasoftware.factorybrain.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.layout.size
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
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
import com.factoriasoftware.factorybrain.net.PlanDto
import com.factoriasoftware.factorybrain.net.PlanStepDto

/**
 * Pantalla del plan del Critic (T-FB017-US01-04): solicitud del plan
 * (campo de texto libre para el identificador de la User Story, p. ej.
 * `"US-FB008-04"`), vista completa de los pasos tal como los expone el
 * backend (sin reformular ni resumir — criterio de aceptación explícito),
 * y dos acciones únicas: "Aprobar plan completo" / "Rechazar".
 */
@Composable
fun PlanScreen(viewModel: PlanViewModel) {
    val uiState by viewModel.uiState.collectAsState()
    val isApproving by viewModel.isApproving.collectAsState()
    var goal by remember { mutableStateOf("") }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text("Plan del Critic", style = MaterialTheme.typography.headlineMedium)

        Column(
            modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            OutlinedTextField(
                value = goal,
                onValueChange = { goal = it },
                label = { Text("User Story (p. ej. US-FB008-04)") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Button(
                onClick = { viewModel.requestPlan(goal.trim()) },
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                Text("Solicitar plan")
            }
        }

        when (val state = uiState) {
            is PlanUiState.NoPlanRequested -> Text("Ningún plan solicitado todavía.")
            is PlanUiState.Loading -> Text("Solicitando plan…")
            is PlanUiState.Error -> Text("Error: ${state.message}")
            is PlanUiState.Loaded -> PlanDetails(
                plan = state.plan,
                onApprove = viewModel::approvePlan,
                onReject = viewModel::rejectPlan,
                isApproving = isApproving,
            )
        }
    }
}

@Composable
private fun PlanDetails(
    plan: PlanDto,
    onApprove: () -> Unit,
    onReject: () -> Unit,
    isApproving: Boolean = false,
) {
    // Diálogo de confirmación de "Aprobar plan completo" (T-FB017-US04-01,
    // criterio de aceptación: "aprobar un plan muestra confirmación con el
    // número de pasos antes de despachar" + "cancelar la confirmación no
    // ejecuta ninguna llamada al backend"). "Rechazar" no lo necesita —
    // sin efecto destructivo, tal como indica la propia Task.
    var showApproveConfirmation by remember { mutableStateOf(false) }

    if (showApproveConfirmation) {
        AlertDialog(
            onDismissRequest = { showApproveConfirmation = false },
            title = { Text("¿Aprobar plan completo?") },
            text = { Text("Se despacharán ${plan.steps.size} pasos automáticamente. ¿Aprobar?") },
            confirmButton = {
                TextButton(onClick = {
                    showApproveConfirmation = false
                    onApprove()
                }) { Text("Aprobar") }
            },
            dismissButton = {
                TextButton(onClick = { showApproveConfirmation = false }) { Text("Cancelar") }
            },
        )
    }

    Column(modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) {
        Text("Objetivo: ${plan.goal}", style = MaterialTheme.typography.titleMedium)
        Text("Estado del plan: ${planStatusLabel(plan.status)}")

        LazyColumn(
            modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
            contentPadding = PaddingValues(vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            itemsIndexed(plan.steps) { index, step ->
                PlanStepCard(index = index + 1, step = step)
            }
        }

        if (plan.status == "proposed") {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = { showApproveConfirmation = true },
                    enabled = !isApproving,
                    modifier = Modifier.fillMaxWidth().height(48.dp),
                ) {
                    if (isApproving) {
                        CircularProgressIndicator(modifier = Modifier.size(20.dp))
                    } else {
                        Text("Aprobar plan completo")
                    }
                }
                Button(
                    onClick = onReject,
                    enabled = !isApproving,
                    modifier = Modifier.fillMaxWidth().height(48.dp),
                ) {
                    Text("Rechazar")
                }
            }
        }
    }
}

@Composable
private fun PlanStepCard(index: Int, step: PlanStepDto) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
            Text("Paso $index: ${step.description}", style = MaterialTheme.typography.bodyLarge)
            Text("Mecanismo: ${step.mechanism}")
            Text("Estado: ${planStatusLabel(step.status)}")
        }
    }
}

/**
 * Distingue explícitamente `blocked` de `running`/otros estados
 * (criterio de aceptación explícito: "un plan bloqueado por fallo
 * intermedio se muestra como tal, no como 'en curso' indefinidamente") —
 * el resto de estados se muestran tal cual, sin reformular (mismo
 * criterio ya aplicado al contenido de los pasos).
 */
private fun planStatusLabel(status: String): String =
    if (status == "blocked") "BLOQUEADO (fallo intermedio, no se despachan más pasos)" else status

package com.factoriasoftware.factorybrain.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.layout.size
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.foundation.background
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import com.factoriasoftware.factorybrain.net.AgentLaunchOption
import com.factoriasoftware.factorybrain.net.AgentLaunchOptions

/**
 * Pantalla de agentes (T-FB017-US01-02): lista con estado en tiempo real
 * (polling, ver `AgentsViewModel`), formulario de lanzamiento con
 * controles táctiles nativos (`Button` + `DropdownMenu`, no un `Select`
 * de Textual replicado), y botón "Detener" por agente — objetivos de
 * toque de al menos 48dp (criterio de aceptación explícito de la Task).
 *
 * ## Filtrado de agentes `stopped` (T-FB017-US01-07)
 *
 * Un agente `stopped` no vuelve a `idle` (sin transición de salida, ver
 * `brain/agents/lifecycle.py`) — solo se puede relanzar desde cero, así
 * que no tiene sentido que ocupe espacio permanente en la lista una vez
 * detenido a propósito. Filtrado **solo en la app** (Opción A de la
 * Task, la recomendada): el backend sigue devolviendo todos los agentes
 * en `GET /agents` tal cual, sin ningún cambio — verificado que ningún
 * endpoint de FB-016 se toca. Se descartó retirar el agente `stopped` del
 * propio dominio (Opción B) porque `Job.agent_id` ya referencia agentes
 * por valor (string), no por objeto — el histórico de Jobs de un agente
 * ya detenido sigue siendo válido sin que el agente permanezca en
 * `session.agents`; retirarlo del backend sería un cambio de dominio más
 * invasivo sin ninguna razón real detectada que lo justifique. El toggle
 * "Mostrar detenidos" es estado puramente de presentación de esta
 * pantalla (`remember`, no pasa por `AgentsViewModel`) — no afecta a
 * ninguna llamada al backend, solo a qué subconjunto de la misma lista ya
 * cargada se muestra.
 */
/**
 * Filtro puro (T-FB017-US01-07) extraído para poder testearlo sin
 * necesitar Compose/instrumentación (mismo criterio ya aplicado en
 * `nextStateAfterPollFailure`, `AgentsViewModel.kt`): con `showStopped =
 * false`, oculta los agentes `status == "stopped"` — con `true`, los
 * muestra todos tal cual, sin reordenar ni transformar nada más.
 */
internal fun visibleAgentsFor(agents: List<AgentDto>, showStopped: Boolean): List<AgentDto> =
    if (showStopped) agents else agents.filter { it.status != "stopped" }

/**
 * Color asociado a `status` (T-FB017-US04-05) — indicador visual
 * complementario, NUNCA sustituto del texto de estado ya existente
 * (criterio de aceptación explícito: "sin depender solo del color").
 * Función pura (no un `@Composable`, `Color` no requiere contexto de
 * composición) para poder testearla directamente, mismo criterio ya
 * aplicado a `visibleAgentsFor`/`agentsWithRunningJob`. Un `status`
 * desconocido (no debería ocurrir con el dominio actual, pero evita un
 * `when` no exhaustivo ante una futura ampliación del backend) usa el
 * mismo gris neutro que `stopped`.
 */
internal fun colorForAgentStatus(status: String): Color = when (status) {
    "idle" -> Color(0xFF4CAF50) // verde suave — disponible
    "working" -> Color(0xFFFFA000) // ámbar — ocupado
    "stopped" -> Color(0xFF9E9E9E) // gris — inactivo a propósito
    "unavailable" -> Color(0xFFE53935) // rojo — fallo no solicitado
    else -> Color(0xFF9E9E9E)
}

@Composable
fun AgentsScreen(viewModel: AgentsViewModel) {
    val uiState by viewModel.uiState.collectAsState()
    val actionMessage by viewModel.actionMessage.collectAsState()
    val isLaunching by viewModel.isLaunching.collectAsState()
    val isStopping by viewModel.isStopping.collectAsState()
    var showStopped by remember { mutableStateOf(false) }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text("Agentes", style = MaterialTheme.typography.headlineMedium)
            Button(onClick = { showStopped = !showStopped }) {
                Text(if (showStopped) "Ocultar detenidos" else "Mostrar detenidos")
            }
        }

        actionMessage?.let {
            Text(it, modifier = Modifier.padding(vertical = 8.dp))
        }

        // T-FB017-US01-06: la sección de la lista recibe `weight(1f)` —
        // sin esto, el `LazyColumn` de `AgentsList` (dentro de un
        // `Column` sin restricción de altura, tanto aquí como en el
        // `Column` raíz de `MainActivity`) se medía con altura de
        // contenido intrínseco en vez de una altura acotada real, y no
        // podía hacer scroll con varios agentes lanzados (el `LazyColumn`
        // intentaba componer todo su contenido de una vez). Con
        // `weight(1f)`, esta sección ocupa exactamente el espacio
        // disponible restante tras el título/aviso/formulario, y dentro
        // de ella el `LazyColumn` sí recibe una altura finita para medir
        // su viewport de scroll. `LaunchAgentForm`, fuera de este `Box`,
        // mantiene su altura de contenido fija y queda siempre visible
        // debajo, sin quedar empujado fuera de pantalla ni solapado.
        Box(modifier = Modifier.weight(1f)) {
            when (val state = uiState) {
                is AgentsUiState.Loading -> Text("Cargando…", modifier = Modifier.padding(vertical = 8.dp))
                is AgentsUiState.Unavailable -> Text(
                    "No se pudo contactar con el backend: ${state.message}",
                    modifier = Modifier.padding(vertical = 8.dp),
                )
                is AgentsUiState.Loaded -> {
                    Column(modifier = Modifier.fillMaxSize()) {
                        // Un fallo puntual de polling conserva la última
                        // lista vista, marcada `stale` — se avisa sin
                        // descartarla (criterio de aceptación 5 de la
                        // Story: "no perder el estado ya cargado ante un
                        // corte de red").
                        if (state.stale) {
                            Text(
                                "Puede que esta lista esté desactualizada (sin conexión con el backend).",
                                modifier = Modifier.padding(vertical = 8.dp),
                            )
                        }
                        val visibleAgents = visibleAgentsFor(state.agents, showStopped)
                        val hiddenStoppedCount = state.agents.size - visibleAgents.size
                        AgentsList(
                            agents = visibleAgents,
                            agentsWithRunningJob = state.agentsWithRunningJob,
                            onStop = viewModel::stopAgent,
                            isStopping = isStopping,
                            hiddenStoppedCount = hiddenStoppedCount,
                            modifier = Modifier.weight(1f),
                        )
                    }
                }
            }
        }

        LaunchAgentForm(onLaunch = viewModel::launchAgent, isLaunching = isLaunching)
    }
}

@Composable
private fun AgentsList(
    agents: List<AgentDto>,
    agentsWithRunningJob: Set<String>,
    onStop: (String) -> Unit,
    isStopping: Boolean = false,
    hiddenStoppedCount: Int = 0,
    modifier: Modifier = Modifier,
) {
    // Diálogo de confirmación de "Detener" (T-FB017-US04-01, criterio de
    // aceptación: "detener un agente muestra confirmación antes de
    // ejecutar la acción real" + "cancelar la confirmación no ejecuta
    // ninguna llamada al backend") — `pendingStopAgent` es el agente para
    // el que se pulsó "Detener" pero aún no se confirmó; `null` cuando no
    // hay ningún diálogo abierto. `onStop` solo se invoca al confirmar.
    var pendingStopAgent by remember { mutableStateOf<AgentDto?>(null) }

    pendingStopAgent?.let { agent ->
        val hasRunningJob = agentsWithRunningJob.contains(agent.id)
        AlertDialog(
            onDismissRequest = { pendingStopAgent = null },
            title = { Text("¿Detener a ${agent.name}?") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Esta acción no se puede deshacer, tendrás que relanzarlo.")
                    if (hasRunningJob) {
                        Text(
                            "Este agente tiene una tarea en curso — detenerlo la interrumpirá.",
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    onStop(agent.id)
                    pendingStopAgent = null
                }) { Text("Detener") }
            },
            dismissButton = {
                TextButton(onClick = { pendingStopAgent = null }) { Text("Cancelar") }
            },
        )
    }

    if (agents.isEmpty()) {
        // Distingue "no hay ningún agente" de "hay agentes, pero todos
        // detenidos y ocultos" (criterio de aceptación: los agentes
        // stopped no desaparecen sin posibilidad de consultarlos — el
        // mensaje aquí ya orienta a usar "Mostrar detenidos").
        val message = if (hiddenStoppedCount > 0) {
            "Agentes lanzados: ninguno visible ($hiddenStoppedCount detenido(s) oculto(s) — usa \"Mostrar detenidos\")."
        } else {
            "Agentes lanzados: ninguno"
        }
        Text(message, modifier = modifier.padding(vertical = 8.dp))
        return
    }

    LazyColumn(
        modifier = modifier.fillMaxWidth(),
        contentPadding = PaddingValues(vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(agents, key = { it.id }) { agent ->
            Card(modifier = Modifier.fillMaxWidth()) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(16.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Column {
                        Text("${agent.name} (${agent.role})", style = MaterialTheme.typography.titleMedium)
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            // T-FB017-US04-05: indicador de color junto al
                            // texto de estado, nunca en su lugar — el
                            // texto sigue siendo la fuente de verdad
                            // accesible (criterio de aceptación explícito).
                            Box(
                                modifier = Modifier
                                    .size(10.dp)
                                    .clip(CircleShape)
                                    .background(colorForAgentStatus(agent.status)),
                            )
                            Text(" Estado: ${agent.status}")
                        }
                    }
                    if (agent.status != "stopped") {
                        Button(
                            onClick = { pendingStopAgent = agent },
                            enabled = !isStopping,
                            modifier = Modifier.height(48.dp),
                        ) {
                            if (isStopping) {
                                CircularProgressIndicator(modifier = Modifier.size(20.dp))
                            } else {
                                Text("Detener")
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun LaunchAgentForm(
    onLaunch: (role: String, runtimeType: String, model: String?) -> Unit,
    isLaunching: Boolean = false,
) {
    var expanded by remember { mutableStateOf(false) }
    var selected by remember { mutableStateOf(AgentLaunchOptions.ALL.first()) }
    var model by remember { mutableStateOf("") }

    Column(
        modifier = Modifier.fillMaxWidth().padding(top = 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Lanzar agente", style = MaterialTheme.typography.titleMedium)

        Box(modifier = Modifier.fillMaxWidth()) {
            Button(
                onClick = { expanded = true },
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                Text(
                    "${selected.roleLabel} sobre ${selected.runtimeLabel}" +
                        if (selected.supportsModel) " (admite modelo)" else " (no admite modelo)"
                )
            }
            DropdownMenu(
                expanded = expanded,
                onDismissRequest = { expanded = false },
            ) {
                AgentLaunchOptions.ALL.forEach { option: AgentLaunchOption ->
                    DropdownMenuItem(
                        text = { Text("${option.roleLabel} sobre ${option.runtimeLabel}") },
                        onClick = {
                            selected = option
                            expanded = false
                        },
                    )
                }
            }
        }

        OutlinedTextField(
            value = model,
            onValueChange = { model = it },
            label = { Text("Modelo (opcional, solo si el runtime lo admite)") },
            enabled = selected.supportsModel,
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
        )

        Button(
            onClick = { onLaunch(selected.role, selected.runtimeType, model.trim().ifBlank { null }) },
            enabled = !isLaunching,
            modifier = Modifier.fillMaxWidth().height(48.dp),
        ) {
            if (isLaunching) {
                CircularProgressIndicator(modifier = Modifier.size(20.dp))
            } else {
                Text("Lanzar")
            }
        }
    }
}

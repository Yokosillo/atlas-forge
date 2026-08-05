package com.factoriasoftware.factorybrain.ui

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
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.foundation.background
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
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
import com.factoriasoftware.factorybrain.net.AgentLaunchOptionDto

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
 * Fondos reales del tema de la app en claro/oscuro (T-FB017-US04-06,
 * `theme/Theme.kt`) — usados como referencia para verificar el contraste
 * WCAG 1.4.11 de cualquier indicador de color fijo (semáforo de estado)
 * contra el fondo real sobre el que se pinta, en ambos temas.
 */
internal val LIGHT_THEME_BACKGROUND = Color(0xFFFAFDFD)
internal val DARK_THEME_BACKGROUND = Color(0xFF191C1C)

private fun srgbChannelToLinear(channel: Float): Double =
    if (channel <= 0.04045f) channel / 12.92 else Math.pow((channel + 0.055) / 1.055, 2.4)

/**
 * Luminancia relativa WCAG de un [Color] (fórmula exacta de la
 * especificación W3C, https://www.w3.org/TR/WCAG21/#dfn-relative-luminance).
 * Usa los accesores públicos `.red`/`.green`/`.blue` (0f..1f) de Compose
 * en vez de desempaquetar bits de `Color.value` a mano — ese campo no es
 * un simple ARGB de 32 bits en todas las representaciones internas de
 * `Color` (espacio de color/alpha empaquetados junto al RGB), los
 * accesores públicos sí son estables.
 */
internal fun relativeLuminance(color: Color): Double {
    val rLin = srgbChannelToLinear(color.red)
    val gLin = srgbChannelToLinear(color.green)
    val bLin = srgbChannelToLinear(color.blue)
    return 0.2126 * rLin + 0.7152 * gLin + 0.0722 * bLin
}

/**
 * Ratio de contraste WCAG 1.4.11 entre dos [Color] — `(L_claro + 0.05) /
 * (L_oscuro + 0.05)`, siempre ≥1. Función pura, verificable directamente
 * sin instrumentación ni dispositivo: el criterio de aceptación
 * "contraste ≥3:1 verificado en claro y oscuro" (T-FB020-US03-01) se
 * comprueba con esta función contra [LIGHT_THEME_BACKGROUND]/
 * [DARK_THEME_BACKGROUND], no solo como afirmación de diseño en un
 * comentario (como hasta ahora en `colorForAgentStatus`, ver
 * `ContrastRatioTest.kt`).
 */
internal fun wcagContrastRatio(colorA: Color, colorB: Color): Double {
    val luminanceA = relativeLuminance(colorA)
    val luminanceB = relativeLuminance(colorB)
    val lighter = maxOf(luminanceA, luminanceB)
    val darker = minOf(luminanceA, luminanceB)
    return (lighter + 0.05) / (darker + 0.05)
}

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
 *
 * T-FB017-US04-06: vuelve a colores fijos independientes del tema. US05-02
 * los mapeó a roles del `ColorScheme` (`primary`/`tertiary`/`outline`/
 * `error`) y con Dynamic Color activo esos roles toman el tono del wallpaper
 * del usuario (bug real: wallpaper rojo/terracota -> los 4 estados quedan en
 * tonos rojizos casi indistinguibles). Un indicador tipo semáforo debe
 * reconocerse de un vistazo igual siempre, sin importar el tema: estos
 * colores NO dependen de `MaterialTheme.colorScheme` (el resto de la UI sí
 * sigue el tema, criterio US05-02 intacto; esta corrección es exclusiva del
 * indicador). Paleta revisada para mantener >=3:1 de contraste (WCAG
 * 1.4.11) sobre los fondos del tema en claro (`0xFFFAFDFD`) y oscuro
 * (`0xFF191C1C`) — los valores anteriores a US05-02 (verde `0xFF4CAF50`,
 * ámbar `0xFFFFA000`, gris `0xFF9E9E9E`) quedaban a 2.0-2.7:1 en claro.
 */
internal fun colorForAgentStatus(status: String): Color = when (status) {
    "idle" -> Color(0xFF2E7D32) // verde (Green 800) — disponible
    "working" -> Color(0xFFEF6C00) // ámbar/naranja (Orange 800) — ocupado
    "stopped" -> Color(0xFF757575) // gris (Grey 600) — inactivo a propósito
    "unavailable" -> Color(0xFFD32F2F) // rojo (Red 700) — fallo no solicitado
    else -> Color(0xFF757575)
}

/**
 * Acceso al color de estado para uso en composición. Los colores son fijos
 * (independientes del tema, ver `colorForAgentStatus`), así que este
 * `@Composable` ya no lee `MaterialTheme.colorScheme` — se mantiene solo
 * como acceso con nombre semántico al color del indicador.
 */
@Composable
fun agentStatusColor(status: String): Color = colorForAgentStatus(status)

@Composable
fun AgentsScreen(viewModel: AgentsViewModel) {
    val uiState by viewModel.uiState.collectAsState()
    val optionsUiState by viewModel.optionsUiState.collectAsState()
    val actionMessage by viewModel.actionMessage.collectAsState()
    val isLaunching by viewModel.isLaunching.collectAsState()
    val isStopping by viewModel.isStopping.collectAsState()
    val paneUiState by viewModel.paneUiState.collectAsState()
    var showStopped by remember { mutableStateOf(false) }

    AgentPaneDialog(state = paneUiState, onDismiss = viewModel::dismissAgentPane)

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
                            onViewPane = viewModel::viewAgentPane,
                            isStopping = isStopping,
                            hiddenStoppedCount = hiddenStoppedCount,
                            modifier = Modifier.weight(1f),
                        )
                    }
                }
            }
        }

        // T-FB017-US01-10: el formulario de lanzamiento no se muestra
        // hasta tener el catálogo real de `GET /agents/options` — un
        // `Loading`/`Unavailable` aquí mostraría un `DropdownMenu` vacío
        // o con datos obsoletos si se intentara construir sin opciones
        // reales que ofrecer.
        //
        // Corrección de bug real (crash en dispositivo, 2026-08-02): un
        // `Loaded` con `options` VACÍA es un caso distinto de `Unavailable`
        // (la petición sí tuvo éxito, pero el catálogo no tenía ninguna
        // combinación que ofrecer — no debería ocurrir hoy con el dominio
        // actual, `list_available_agent_options()` siempre devuelve 4
        // combinaciones, pero `LaunchAgentForm` no debe asumirlo) — se
        // trata aquí, ANTES de invocar `LaunchAgentForm`, en vez de
        // dejar que `options.first()` lance `NoSuchElementException`
        // dentro del formulario. Mismo criterio que `Unavailable`: un
        // mensaje explícito en vez de una pantalla en blanco o un crash.
        when (val optionsState = optionsUiState) {
            is AgentOptionsUiState.Loading -> Text(
                "Cargando catálogo de agentes…",
                modifier = Modifier.padding(vertical = 8.dp),
            )
            is AgentOptionsUiState.Unavailable -> Text(
                "No se pudo cargar el catálogo de agentes: ${optionsState.message}",
                modifier = Modifier.padding(vertical = 8.dp),
            )
            is AgentOptionsUiState.Loaded -> if (optionsState.options.isEmpty()) {
                Text(
                    "No hay ninguna combinación de agente/runtime disponible para lanzar.",
                    modifier = Modifier.padding(vertical = 8.dp),
                )
            } else {
                LaunchAgentForm(
                    options = optionsState.options,
                    onLaunch = viewModel::launchAgent,
                    isLaunching = isLaunching,
                )
            }
        }
    }
}

@Composable
private fun AgentsList(
    agents: List<AgentDto>,
    agentsWithRunningJob: Set<String>,
    onStop: (String) -> Unit,
    onViewPane: (agentId: String, agentName: String) -> Unit,
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
                                    .background(agentStatusColor(agent.status)),
                            )
                            Text(" Estado: ${agent.status}")
                        }
                        // T-FB017-US01-08: modelo mostrado solo cuando
                        // existe (OpenCode con modelo indicado). Claude
                        // Code / OpenCode sin modelo -> `null` -> se omite
                        // limpiamente, sin un campo de modelo vacío/confuso.
                        agent.model?.let { model ->
                            Text(
                                " Modelo: $model",
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                    }
                    Column(horizontalAlignment = Alignment.End) {
                        Button(
                            onClick = { onViewPane(agent.id, agent.name) },
                            modifier = Modifier.height(48.dp),
                        ) {
                            Text("Ver actividad")
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
}

/**
 * Diálogo de actividad de un agente (T-FB017-US01-08): vista de SOLO
 * LECTURA del contenido actual del pane de tmux del agente (`GET
 * /agents/{id}/pane`), con scroll propio porque el contenido crudo puede
 * ser largo. No es una consola interactiva. Estados: carga, contenido, o
 * fallo con el motivo real (p. ej. agente detenido sin sesión tmux).
 */
@Composable
private fun AgentPaneDialog(
    state: AgentPaneUiState,
    onDismiss: () -> Unit,
) {
    if (state is AgentPaneUiState.Closed) return

    val title = when (state) {
        is AgentPaneUiState.Open -> "Actividad de ${state.agentName}"
        is AgentPaneUiState.Unavailable -> "Actividad de ${state.agentName}"
        else -> "Actividad"
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            when (state) {
                is AgentPaneUiState.Loading -> Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(modifier = Modifier.size(20.dp))
                    Text(" Consultando la sesión…", modifier = Modifier.padding(start = 8.dp))
                }
                is AgentPaneUiState.Unavailable -> Text(
                    state.message,
                    modifier = Modifier.padding(vertical = 8.dp),
                )
                is AgentPaneUiState.Open -> Column(
                    modifier = Modifier
                        .heightIn(max = 360.dp)
                        .verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        "Solo lectura — estado actual de la sesión:",
                        style = MaterialTheme.typography.labelMedium,
                    )
                    Text(
                        state.content.ifBlank { "(pane vacío)" },
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                is AgentPaneUiState.Closed -> {}
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text("Cerrar") }
        },
    )
}

/**
 * Etiqueta de rol capitalizada para mostrar en el formulario
 * (T-FB017-US01-10) — `GET /agents/options` devuelve `agent_role` tal
 * cual lo usa el dominio (`"developer"`/`"critic"`, ver
 * `brain.agents.DEVELOPER_ROLE`/`CRITIC_ROLE`), sin una etiqueta de
 * presentación separada (a diferencia de `runtime_name`, que el backend
 * ya devuelve capitalizado — "Claude Code"/"OpenCode", ver
 * `register_claude_code_runtime`/`register_opencode_runtime`). Derivar la
 * capitalización aquí evita mantener un mapa Kotlin duplicado que solo
 * podría desincronizarse si el dominio añadiera un rol nuevo.
 */
private fun AgentLaunchOptionDto.roleLabel(): String =
    agent_role.replaceFirstChar { it.uppercase() }

/**
 * Precondición: `options` nunca vacía — el único llamador (`AgentsScreen`)
 * ya filtra ese caso antes de invocar este composable (mensaje explícito
 * de "catálogo vacío" en su lugar, ver el `when` sobre `AgentOptionsUiState`
 * en `AgentsScreen`), así que `options.first()` es seguro por
 * construcción aquí.
 */
@Composable
private fun LaunchAgentForm(
    options: List<AgentLaunchOptionDto>,
    onLaunch: (role: String, runtimeType: String, model: String?, initialJobDescription: String?) -> Unit,
    isLaunching: Boolean = false,
) {
    var expanded by remember { mutableStateOf(false) }
    var selected by remember(options) { mutableStateOf(options.first()) }
    var model by remember { mutableStateOf("") }
    var initialJobDescription by remember { mutableStateOf("") }

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
                    "${selected.roleLabel()} sobre ${selected.runtime_name}" +
                        if (selected.supports_model) " (admite modelo)" else " (no admite modelo)"
                )
            }
            DropdownMenu(
                expanded = expanded,
                onDismissRequest = { expanded = false },
            ) {
                options.forEach { option: AgentLaunchOptionDto ->
                    DropdownMenuItem(
                        text = { Text("${option.roleLabel()} sobre ${option.runtime_name}") },
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
            enabled = selected.supports_model,
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
        )

        // T-FB017-US06-01: tarea inicial opcional — un Job que se
        // despacharía automáticamente justo tras lanzar el agente (endpoint
        // combinado de T-FB016-US01-16). Multilínea porque es una
        // descripción libre; claramente marcado como opcional.
        OutlinedTextField(
            value = initialJobDescription,
            onValueChange = { initialJobDescription = it },
            label = { Text("Tarea inicial (opcional)") },
            supportingText = { Text("Se despachará como un Job al lanzar el agente.") },
            modifier = Modifier.fillMaxWidth(),
            minLines = 2,
            maxLines = 4,
        )

        Button(
            onClick = {
                onLaunch(
                    selected.agent_role,
                    selected.runtime_type,
                    model.trim().ifBlank { null },
                    initialJobDescription.trim().ifBlank { null },
                )
            },
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

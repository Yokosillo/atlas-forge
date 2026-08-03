package com.factoriasoftware.factorybrain

// T-FB017-US01-01: punto de entrada de la app. Ninguna decisión de
// dominio vive aquí ni en ninguna otra parte de este módulo (criterio de
// aceptación explícito de US-FB017-01, "ninguna decisión de dominio
// vive en el código de la app — toda acción es una llamada directa a un
// endpoint de FB-016") — esta Activity solo compone las pantallas
// operativas sobre sus `ViewModel`, que a su vez solo llaman al
// `BackendClient` (envoltura HTTP fina, sin lógica de negocio) y
// exponen el resultado crudo.

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.factoriasoftware.factorybrain.ui.AgentsScreen
import com.factoriasoftware.factorybrain.ui.AgentsViewModel
import com.factoriasoftware.factorybrain.ui.HealthCheckViewModel
import com.factoriasoftware.factorybrain.ui.JobsScreen
import com.factoriasoftware.factorybrain.ui.JobsViewModel
import com.factoriasoftware.factorybrain.ui.OnboardingFlow
import com.factoriasoftware.factorybrain.ui.PlanScreen
import com.factoriasoftware.factorybrain.ui.PlanViewModel
import com.factoriasoftware.factorybrain.ui.ProjectUiState
import com.factoriasoftware.factorybrain.ui.ProjectViewModel
import com.factoriasoftware.factorybrain.ui.ScriptsScreen
import com.factoriasoftware.factorybrain.ui.ScriptsViewModel
import com.factoriasoftware.factorybrain.ui.SessionContextChip
import com.factoriasoftware.factorybrain.ui.activeProjectNameFor
import com.factoriasoftware.factorybrain.ui.isBackendConnected
import com.factoriasoftware.factorybrain.ui.isSessionContextResolved
import com.factoriasoftware.factorybrain.ui.theme.FactoryBrainTheme

// T-FB017-US03-01: `HealthCheck`/`Project` dejan de ser destinos de
// navegación de nivel superior — se fusionan en `SessionContextChip`
// (barra superior persistente, visible desde las 4 pantallas
// operativas). Solo quedan aquí las pantallas de TRABAJO real —
// verificar conexión/proyecto ya no compite por espacio con ellas en la
// misma fila de navegación (parte del hallazgo de arquitectura de
// información de US-FB017-03).
//
// T-FB017-US03-02: la fila de botones sin scroll (bug real, captura de
// pantalla que motivó esta Story) se sustituye por `NavigationBar`
// (Material 3, pensada para 3-5 ítems sin necesitar drawer ni scroll) —
// mostrada solo cuando `isSessionContextResolved` es `true`.
private enum class AppScreen(val label: String, val icon: ImageVector) {
    Agents("Agentes", Icons.Filled.Person),
    Jobs("Jobs", Icons.AutoMirrored.Filled.List),
    Plan("Plan Critic", Icons.Filled.CheckCircle),
    Scripts("Scripts", Icons.Filled.Build),
}

class MainActivity : ComponentActivity() {
    private val healthCheckViewModel: HealthCheckViewModel by viewModels()
    private val projectViewModel: ProjectViewModel by viewModels()
    private val agentsViewModel: AgentsViewModel by viewModels()
    private val jobsViewModel: JobsViewModel by viewModels()
    private val planViewModel: PlanViewModel by viewModels()
    private val scriptsViewModel: ScriptsViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            FactoryBrainTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    var currentScreen by remember { mutableStateOf(AppScreen.Agents) }
                    // T-FB017-US03-03: elevado para que el botón de acción
                    // del onboarding ("Configurar conexión"/"Elegir
                    // proyecto") pueda abrir la MISMA hoja modal que el
                    // propio chip — ruta directa real, no un flujo
                    // duplicado (guía 3 de Nielsen Norman Group).
                    var showContextSheet by remember { mutableStateOf(false) }

                    val healthState by healthCheckViewModel.state.collectAsState()
                    val projectUiState by projectViewModel.uiState.collectAsState()
                    // T-FB017-US03-02: reutiliza las mismas funciones puras
                    // ya construidas en T-FB017-US03-01 para decidir si el
                    // contexto está resuelto — ninguna lógica nueva de
                    // "¿hay conexión? ¿hay proyecto?" se reimplementa aquí.
                    val activeProjectId = (projectUiState as? ProjectUiState.Loaded)?.activeProject?.id
                    val contextResolved = isSessionContextResolved(
                        isBackendConnected(healthState),
                        activeProjectNameFor(projectUiState),
                    )

                    // Criterio de aceptación explícito: "Cambiar de
                    // proyecto... recontextualiza las 4 pantallas —
                    // verificado que no muestran datos del proyecto
                    // anterior tras el cambio." `AgentsViewModel` ya hace
                    // polling automático (se autocorrige solo, sin
                    // necesitar esto); `JobsViewModel`/`ScriptsViewModel`
                    // solo cargan una vez al construirse (`init`), así que
                    // sin este efecto seguirían mostrando datos del
                    // proyecto anterior indefinidamente tras un cambio.
                    // `PlanViewModel` no carga nada automáticamente (el
                    // usuario siempre pide un plan explícito con
                    // `requestPlan`), así que no hay ningún dato
                    // "heredado" del proyecto anterior que limpiar ahí.
                    LaunchedEffect(activeProjectId) {
                        if (activeProjectId != null) {
                            jobsViewModel.refreshAgents()
                            jobsViewModel.refreshHistory()
                            scriptsViewModel.refresh()
                        }
                    }

                    Column(modifier = Modifier.fillMaxSize()) {
                        // T-FB017-US03-01: visible desde las 4 pantallas
                        // operativas, sin navegar a otra pantalla para
                        // saber sobre qué se está trabajando (criterio de
                        // aceptación explícito).
                        SessionContextChip(
                            healthCheckViewModel = healthCheckViewModel,
                            projectViewModel = projectViewModel,
                            showContextSheet = showContextSheet,
                            onShowContextSheetChange = { showContextSheet = it },
                        )

                        if (contextResolved) {
                            Column(modifier = Modifier.weight(1f)) {
                                when (currentScreen) {
                                    AppScreen.Agents -> AgentsScreen(viewModel = agentsViewModel)
                                    AppScreen.Jobs -> JobsScreen(viewModel = jobsViewModel)
                                    AppScreen.Plan -> PlanScreen(viewModel = planViewModel)
                                    AppScreen.Scripts -> ScriptsScreen(viewModel = scriptsViewModel)
                                }
                            }

                            NavigationBar {
                                AppScreen.entries.forEach { screen ->
                                    NavigationBarItem(
                                        selected = currentScreen == screen,
                                        onClick = { currentScreen = screen },
                                        icon = { Icon(screen.icon, contentDescription = screen.label) },
                                        label = { Text(screen.label) },
                                    )
                                }
                            }
                        } else {
                            // T-FB017-US03-03: flujo de onboarding guiado
                            // (3 guías de Nielsen Norman Group) en el
                            // hueco que deja la navegación operativa sin
                            // contexto resuelto — sustituye el mensaje
                            // mínimo de T-FB017-US03-02.
                            Column(modifier = Modifier.weight(1f)) {
                                OnboardingFlow(
                                    isConnected = isBackendConnected(healthState),
                                    projectName = activeProjectNameFor(projectUiState),
                                    onOpenContextSheet = { showContextSheet = true },
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

package com.factoriasoftware.factorybrain

// T-FB017-US01-01: punto de entrada de la app. Ninguna decisión de
// dominio vive aquí ni en ninguna otra parte de este módulo (criterio de
// aceptación explícito de US-FB017-01, "ninguna decisión de dominio
// vive en el código de la app — toda acción es una llamada directa a un
// endpoint de FB-016") — esta Activity solo compone la pantalla de
// verificación (`HealthCheckScreen`) sobre su `ViewModel`, que a su vez
// solo llama al `BackendClient` (envoltura HTTP fina, sin lógica de
// negocio) y expone el resultado crudo.

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.factoriasoftware.factorybrain.ui.AgentsScreen
import com.factoriasoftware.factorybrain.ui.AgentsViewModel
import com.factoriasoftware.factorybrain.ui.HealthCheckScreen
import com.factoriasoftware.factorybrain.ui.HealthCheckViewModel
import com.factoriasoftware.factorybrain.ui.JobsScreen
import com.factoriasoftware.factorybrain.ui.JobsViewModel
import com.factoriasoftware.factorybrain.ui.PlanScreen
import com.factoriasoftware.factorybrain.ui.PlanViewModel
import com.factoriasoftware.factorybrain.ui.ProjectScreen
import com.factoriasoftware.factorybrain.ui.ProjectViewModel
import com.factoriasoftware.factorybrain.ui.ScriptsScreen
import com.factoriasoftware.factorybrain.ui.ScriptsViewModel

private enum class AppScreen(val label: String) {
    HealthCheck("Verificación"),
    Project("Proyecto"),
    Agents("Agentes"),
    Jobs("Jobs"),
    Plan("Plan Critic"),
    Scripts("Scripts"),
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
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    var currentScreen by remember { mutableStateOf(AppScreen.HealthCheck) }

                    Column(modifier = Modifier.fillMaxSize()) {
                        Row(modifier = Modifier.fillMaxWidth().padding(8.dp)) {
                            AppScreen.entries.forEach { screen ->
                                Button(
                                    onClick = { currentScreen = screen },
                                    modifier = Modifier.padding(horizontal = 4.dp),
                                ) {
                                    Text(screen.label)
                                }
                            }
                        }

                        when (currentScreen) {
                            AppScreen.HealthCheck -> HealthCheckScreen(viewModel = healthCheckViewModel)
                            AppScreen.Project -> ProjectScreen(viewModel = projectViewModel)
                            AppScreen.Agents -> AgentsScreen(viewModel = agentsViewModel)
                            AppScreen.Jobs -> JobsScreen(viewModel = jobsViewModel)
                            AppScreen.Plan -> PlanScreen(viewModel = planViewModel)
                            AppScreen.Scripts -> ScriptsScreen(viewModel = scriptsViewModel)
                        }
                    }
                }
            }
        }
    }
}

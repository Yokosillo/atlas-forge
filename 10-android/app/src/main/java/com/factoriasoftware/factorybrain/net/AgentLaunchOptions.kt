package com.factoriasoftware.factorybrain.net

/**
 * Catálogo estático de combinaciones agente/runtime disponibles para
 * elegir antes de lanzar (T-FB017-US01-02), equivalente Kotlin de
 * `brain.dashboard.agent_options.list_available_agent_options` — mismo
 * criterio ya aplicado en la migración de la TUI (T-FB016-US01-06,
 * `brain.tui.backend_client`, ver su docstring: "un catálogo estático de
 * combinaciones agente/runtime posibles, sin tocar ningún registro de
 * estado — no hay endpoint HTTP para esto porque no hace falta").
 *
 * Los valores (`role`, `runtimeType`) son los mismos strings reales que
 * ya usa el dominio Python (`DEVELOPER_ROLE = "developer"`,
 * `CRITIC_ROLE = "critic"`, `Runtime.type` = `"claude-code"`/`"opencode"`,
 * ver `brain/agents/developer.py`, `brain/agents/critic.py`,
 * `brain/runtime/claude_code.py`, `brain/runtime/opencode.py`) — si
 * cambiaran ahí, esta lista tendría que actualizarse a mano (mismo riesgo
 * ya aceptado explícitamente para la TUI, que también los mantiene
 * locales en vez de resolverlos desde el backend en cada arranque).
 */
data class AgentLaunchOption(
    val role: String,
    val roleLabel: String,
    val runtimeType: String,
    val runtimeLabel: String,
    val supportsModel: Boolean,
)

object AgentLaunchOptions {
    val ALL: List<AgentLaunchOption> = listOf(
        AgentLaunchOption("developer", "Developer", "claude-code", "Claude Code", supportsModel = false),
        AgentLaunchOption("developer", "Developer", "opencode", "OpenCode", supportsModel = true),
        AgentLaunchOption("critic", "Critic", "claude-code", "Claude Code", supportsModel = false),
        AgentLaunchOption("critic", "Critic", "opencode", "OpenCode", supportsModel = true),
    )
}

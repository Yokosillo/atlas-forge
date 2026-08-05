# Roadmap

Estado real de Factory Brain contrastado contra `02-backlog/` (estados canónicos) y `07-informes/` (informes de cierre). Este documento es la vista pública del [roadmap canónico](https://github.com/factoria-software/factory-brain/blob/main/02-backlog/roadmap.md) del proyecto.

## Resumen por fases

| Fase | Contenido | Estado |
|---|---|---|
| **0.1** | Primer producto funcional: Workspace, Sesión, Runtime, Agentes, Dispatcher manual (Jobs + encadenado) | ✅ Completada |
| **0.2** | Multi-runtime/multi-modelo y ahorro de tokens: TUI unificada, Scribe, disparo automático de Scribe | ✅ Completada |
| **0.3** | Dispatcher-crítico y acceso remoto: plan del Arquitecto con aprobación única, API backend, app Android, cancelación de Job/Plan, confirmaciones | ✅ Completada |
| **0.4** | Scripts genéricos y particulares: catálogo de 7 scripts, indexado con Scribe | ✅ Completada |
| **1.0** | Pipeline backlog-céntrico: roles Director/Arquitecto, generadores Epic→US→Task, validador, veredictos, mejoras UX web, acciones transversales | 🔶 En curso |
| **0.5–0.9** | Dispatcher v2, Capabilities, Context, Knowledge, Automation, Plugins, Dashboard restante | ⬜ Planificado |
| — | Config Management (FB-013) | ⏸️ En espera (backlog hold) |

## Estado por Epic

Fuente: campo `## Estado` de cada Epic en `02-backlog/epics/` (canónico) cruzado con Tasks DONE e informes de cierre.

### DONE (implementado y operativo)

| Epic | Qué incluye |
|---|---|
| **FB-001** Workspace Management | Descubrimiento de repos Git, proyecto activo persistido, scripts del proyecto. |
| **FB-002** Dashboard | TUI unificada (Workspace/Dashboard/Agentes), elegir agente/runtime/modelo. |
| **FB-003** Development Session | Sesión viva durante la ejecución, agentes asignados. |
| **FB-004** Runtime Manager | Claude Code y OpenCode en tmux, cambio de modelo (OpenCode). |
| **FB-005** Agent Manager | Roles Developer y Critic, prompts en dos capas, liveness. |
| **FB-008** Dispatcher | Jobs, encadenado, planes con aprobación, cancelación, Scribe automático. |
| **FB-014** Local Tools | Scribe: resumen/indexación local (Ollama), incluye operación `index_scripts`. |
| **FB-016** API Backend | FastAPI: agentes, Jobs, planes, backlog, scripts, WebSockets, static `/ui/`, systemd. |
| **FB-017** App Android | App nativa (Compose) — **en pausa** para funcionalidad nueva (2026-08-04). |
| **FB-018** Scripts Genéricos | Catálogo de 7 scripts genéricos + CLI `backlog-status` + Scribe prose. |
| **FB-019** TUI | Pantalla de Plan, cancelar Job/Plan, confirmaciones, conectividad. |
| **FB-020** Gestión de Backlog | Endpoints de listado/detalle, lanzar desarrollo, vistas en web/app/TUI. |
| **FB-021** Interfaz Web | Web completa: proyectos, agentes, Jobs, plan, scripts, backlog, modelos. |

### Fase 1.0 (Tasks DONE; ficheros de Epic pendientes de actualizar a `DONE`)

Las Epics FB-022, FB-024 y FB-025 tienen **todas sus Tasks DONE** e informes de cierre en `07-informes/`, pero sus ficheros de Epic siguen marcados `## Estado: TODO` — discrepancia de metadatos del backlog (los Developer cierran Tasks; la actualización del estado de la Epic la aplica el Director). Se listan aquí como implementadas según la evidencia real.

| Epic | Tasks | Qué aporta |
|---|---|---|
| **FB-022** Pipeline Backlog-céntrico | 34/34 DONE | Roles Director/Arquitecto, generadores Epic→US→Task con validador+autoauditoría, veredictos, cola FIFO, catálogo de modelos en fichero, contrato Tester. |
| **FB-024** Mejoras UX web | 23/23 DONE | Diferenciación visual DONE/TODO, badge, dependencias con bloqueo, campo Fase, mapa de calor, pantalla de roles, historial en detalle US. |
| **FB-025** Acciones transversales | 10/12 DONE (US01–07) | Acciones web: documentar, analizar-arquitectura, sugerir-ideas, testear, auditar-ux, indexar. |

!!! note "FB-025 pendiente"
    `US-FB025-08` (auditar OSS, 2 Tasks) está **TODO**: no implementada. La decisión de `US-FB025-05` (botón Commit) fue **no exponerlo**: el commit ya existe como script genérico.

### Planificado, no implementado

| Epic | Notas |
|---|---|
| **FB-006** Context Engine | Sin Tasks. Planificado (Fase 0.6). |
| **FB-007** Knowledge Engine | Sin Tasks. Planificado (Fase 0.6). |
| **FB-009** Automation Engine | Sin Tasks. Planificado (Fase 0.7). |
| **FB-010** Capability Engine | Sin Tasks. Planificado (Fase 0.5). Desbloquea US-FB005-03. |
| **FB-011** Plugin System | Sin Tasks. **No existe sistema de plugins ni MCP.** Planificado (Fase 0.8). |
| **FB-012** Development Automations | Sin Tasks. Planificado (Fase 0.7). |
| **FB-013** Configuration Management | **En espera** (backlog hold): se revisa cuando exista una necesidad real de configuración multi-usuario. |
| **FB-023** Supervisión ciclo de vida | No prioritaria (decisión 2026-08-05). Flag `persistent`, detección de cuelgues, `opencode serve` headless. |
| **FB-026** Análisis de hilos | Módulo `dependency_graph.py` existe en el código pero **sin Tasks DONE ni interfaz** — planificado. |

### Descartada

| Epic | Nota |
|---|---|
| **FB-015** Acceso remoto (Tailscale+SSH+tmux) | **DESCARTADA** (2026-08-02): la necesidad quedó resuelta por FB-016/FB-017 (app táctil real). Se conserva por trazabilidad. |

## Deuda técnica y decisiones relevantes

- **Pausa TUI/Android** (2026-08-04): toda funcionalidad nueva se expone en la web. Tasks de modelo activo en TUI (`T-FB019-US02-01`) y Android (`T-FB017-US07-01`) marcadas `POSTERGADA`.
- **Estado en memoria**: sesión, agentes y Jobs viven en memoria del proceso `brain-api`. La recuperación de sesión tras reinicio (`US-FB003-02`) está planificada, no implementada.
- **Sin autenticación propia**: el perímetro es Tailscale. No recomendado para despliegue sin red privada.
- **Observabilidad** (logging estructurado, métricas, tracing): sin fase asignada, en backlog hold.

## Criterio de funcionalidad

Factory Brain se considera funcional cuando puede: gestionar múltiples proyectos, mantener sesiones persistentes, administrar agentes sobre distintos runtimes, coordinar Jobs mediante pipelines, ejecutar automatizaciones, preparar contexto automáticamente, reutilizar conocimiento, minimizar el uso de modelos remotos, incorporar capacidades mediante plugins y proporcionar visión operacional.

**Estado hoy**: la coordinación de Jobs/planes, la multi-runtime/multi-modelo y el ahorro de tokens son reales. La gestión de contexto/conocimiento, las capacidades, los plugins y el pipeline declarativo completo son trabajo futuro.

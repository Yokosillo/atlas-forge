# Roadmap

Estado real de Atlas Forge contrastado contra `02-backlog/` (estados canónicos) y `07-informes/` (informes de cierre). Este documento es la vista pública del [roadmap canónico](https://github.com/factoria-software/atlas-forge/blob/main/02-backlog/roadmap.md) del proyecto.

## Resumen por fase

| Fase | Contenido | Estado |
|---|---|---|
| **0.1** | Primer producto funcional: Workspace, Sesión, Runtime, Agentes, Dispatcher manual (Jobs + encadenamiento) | ✅ Completa |
| **0.2** | Multi-runtime/multi-modelo y ahorro de tokens: Scribe, disparo automático de Scribe | ✅ Completa |
| **0.3** | Dispatcher crítico y acceso remoto: API backend, cancelación de Jobs, confirmaciones | ✅ Completa |
| **0.4** | Scripts genéricos y de proyecto: catálogo de 7 scripts, indexación con Scribe | ✅ Completa |
| **0.9** | Pipeline centrado en el backlog: rol Arquitecto, generadores Epic→US→Task, validador, veredictos, formato de backlog estructurado, mejoras de UX web, acciones transversales, sesiones multi-proyecto, reconciliación de agentes al arrancar, log de agente en vivo | 🔶 En curso |
| **0.5–0.8** | Dispatcher v2, Capacidades, Contexto, Conocimiento, Automatización, Plugins, resto del Dashboard | ⬜ Planificado |
| — | Config Management (AF-013) | ⏸️ En espera (backlog hold) |

## Estado por Epic

Fuente: el campo frontmatter `state` de cada Epic en `02-backlog/epics/` (canónico) cruzado con Tasks DONE e informes de cierre.

### DONE (implementado y operativo)

| Epic | Qué incluye |
|---|---|
| **AF-001** Gestión de Workspace | Descubrimiento de repos Git, proyecto activo persistido, scripts de proyecto. |
| **AF-003** Sesión de desarrollo | Sesión viva durante la ejecución, agentes asignados. |
| **AF-004** Runtime Manager | Claude Code y OpenCode en tmux, cambio de modelo (OpenCode). |
| **AF-005** Agent Manager | Roles Developer y Critic, prompts de dos capas, liveness. |

> Nota histórica: el rol Critic se fusionó en el Arquitecto (ver `00-gobierno/old/CRITICO.md`); el pipeline actual del producto impulsa el trabajo desde el backlog (ver [Backlog y pipeline](backlog.md)).

| **AF-008** Dispatcher | Jobs, encadenamiento, despacho de Job aislado, cancelación, Scribe automático. |
| **AF-014** Herramientas locales | Scribe: resumen/indexación local (Ollama), incluida la operación `index_scripts`. |
| **AF-016** API Backend | FastAPI: agentes, Jobs, backlog, scripts, WebSockets, `/ui/` estático, systemd. |
| **AF-018** Scripts genéricos | Catálogo de 7 scripts genéricos + prosa de Scribe. |
| **AF-020** Gestión de backlog | Endpoints de listado/detalle, lanzar desarrollo, vistas en la web. |
| **AF-021** Interfaz web | Web completa: proyectos, agentes, Jobs, scripts, backlog, modelos. |
| **AF-026** Análisis de hilos paralelizables | Módulo `dependency_graph.py`, endpoint `POST /backlog/epic/{epic_id}/analyze-threads`, botón "Generar hilos de desarrollo" en la pestaña Backlog de la web. |

### Retirado / archivado

| Epic | Nota |
|---|---|
| **AF-002** Dashboard | Interfaz de terminal — **retirada y archivada** (2026-08-18). Toda la funcionalidad vive en la web. |
| **AF-017** App móvil | App móvil nativa — **retirada y archivada** (2026-08-18). Previamente **pausada** para funcionalidad nueva (2026-08-04). |
| **AF-019** Interfaz de terminal | Cancelar Job, confirmaciones, conectividad — **retirada y archivada** (2026-08-18). |

### Fase 0.9 — mayormente DONE a nivel de Epic

| Epic | Tasks | Qué aporta |
|---|---|---|
| **AF-022** Pipeline centrado en el backlog | La mayoría de User Stories DONE; US-AF022-16 aún TO_DO | Roles de Arquitecto y Tester, generadores Epic→US→Task con validador+auto-auditoría, el ciclo de veredicto guiado por estados Developer→Tester→Arquitecto, catálogo de modelos por fichero. |
| **AF-024** Mejoras de UX web | En curso (23+ Tasks DONE en múltiples User Stories, se añaden más según el uso real revela brechas) | Diferenciación visual DONE/TO_DO, badge, bloqueo por dependencias, campo Fase, mapa de calor, pantalla unificada Roles/Agentes (mismos campos/botones por rol, "stop" del Developer borra la instancia en lugar de pausarla), límite simultáneo de Developers configurable, historial de detalle de US. |
| **AF-025** Acciones transversales | 10/12 DONE (US01–07) | Acciones web: documentar, analizar-arquitectura, sugerir-ideas, testear, auditar-ux, indexar. |
| **AF-027** Formato de backlog estructurado | 3/3 DONE | Frontmatter YAML + cuerpo Markdown para cada Epic/User Story/Task, reemplazando el parseo por patrón de negrita de texto libre `**ID**`. Migración completa del backlog existente realizada. |
| **AF-029** Sesiones de proyecto simultáneas | 4/4 DONE | Múltiples sesiones vivas en paralelo, una por proyecto; cambiar el proyecto activo en la web ya no detiene ningún agente — los agentes del proyecto con foco anterior siguen vivos en su propia sesión y vuelven a ser alcanzables al recuperar el foco. |
| **AF-030** Cola de cierre hacia el Arquitecto | DONE | Fichero por proyecto de solo añadido donde un Developer/otro rol encola avisos de cierre de Task para el Arquitecto; nomenclatura determinista de sesiones tmux (`<role>-<project>` / `<role>-N-<project>`) más un watcher `inotifywait` que empuja al pane del Arquitecto, con comprobación periódica de respaldo. |
| **AF-031** Reconciliación de agentes al arrancar | DONE | Al arrancar `atlas-forge-api`, lista las sesiones tmux reales del socket y las reconoce por su nombre determinista (depende de AF-030), re-registrándolas como agentes `idle` sin relanzar su runtime — un reinicio del backend ya no pierde agentes vivos. |
| **AF-032** Log de agente en vivo en la web | DONE | `WS /ws/agents/{agent_id}/pane`: un canal por conexión, poller del servidor que solo publica ante cambios, se detiene al desconectarse. Un agente a la vez, solo lectura, pestaña/ventana separada. |

!!! note "AF-025 pendiente"
    `US-AF025-08` (auditoría OSS, 2 Tasks) está **TO_DO**: no implementada. La decisión sobre `US-AF025-05` (botón Commit) fue **no exponerlo**: commit ya existe como script genérico.

### Planificado, no implementado

| Epic | Notas |
|---|---|
| **AF-006** Context Engine | Sin Tasks. Planificado (Fase 0.6). |
| **AF-007** Knowledge Engine | Sin Tasks. Planificado (Fase 0.6). |
| **AF-009** Automation Engine | Sin Tasks. Planificado (Fase 0.7). |
| **AF-010** Capability Engine | Sin Tasks. Planificado (Fase 0.5). Desbloquea US-AF005-03. |
| **AF-011** Plugin System | Sin Tasks. **No existe sistema de plugins ni MCP.** Planificado (Fase 0.8). |
| **AF-012** Automatizaciones de desarrollo | Sin Tasks. Planificado (Fase 0.7). |
| **AF-013** Gestión de configuración | **En espera** (backlog hold): se revisará cuando aparezca una necesidad real de configuración multi-usuario. |
| **AF-023** Supervisión del ciclo de vida | No es prioridad (decisión del 2026-08-05). Existe una acción disparada por humanos de "revisar si está atascado" (AF-024/US-AF024-11); la detección automática en segundo plano de atascos y `opencode serve` headless siguen sin implementar. |
| **AF-028** Barra de control persistente para agentes críticos | Solo 2 User Stories definidas, sin Tasks todavía — no iniciado. |

### Aplazado / descartado

| Epic | Nota |
|---|---|
| **AF-015** Acceso remoto (SSH+tmux) | **Aplazado** (descartado en principio, 2026-08-02): la necesidad quedó resuelta por AF-016/AF-017 (una app táctil real). Se mantiene por trazabilidad, se revisará solo si aparece una necesidad real que AF-016/AF-017 no cubran. |

## Deuda técnica y decisiones relevantes

- **Interfaces no-web retiradas** (2026-08-18): la interfaz de terminal y la app móvil fueron archivadas y eliminadas del repo. Sus Epics (AF-002, AF-017, AF-019) y User Stories/Tasks relacionadas están marcadas `FUERA_ROADMAP`; toda la funcionalidad nueva se expone en la web.
- **Estado en memoria**: sesión, agentes y Jobs viven en la memoria del proceso `atlas-forge-api`. Al reiniciar, las sesiones tmux vivas se re-reconocen por su nombre determinista y se re-registran como agentes `idle` (AF-031) — pero el historial de Jobs y cualquier otro estado en memoria se pierde; la recuperación completa de la sesión (`US-AF003-02`) sigue planificada, no implementada.
- **Observabilidad** (logging estructurado, métricas, trazado): sin fase asignada, en backlog hold.

## Criterio de funcionalidad

Se considera que Atlas Forge es funcional cuando puede: gestionar múltiples proyectos, mantener sesiones persistentes, administrar agentes en distintos runtimes, coordinar Jobs mediante pipelines, ejecutar automatizaciones, preparar contexto automáticamente, reutilizar conocimiento, minimizar el uso del modelo remoto, incorporar capacidades mediante plugins y proporcionar visión operativa.

**Estado hoy**: la coordinación de Jobs guiada por backlog, el multi-runtime/multi-modelo y el ahorro de tokens son reales. La gestión de contexto/conocimiento, capacidades, plugins y el pipeline declarativo completo son trabajo futuro.
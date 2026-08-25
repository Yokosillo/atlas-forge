# Roadmap

Estado real de Atlas Forge contrastado contra `02-backlog/` (estados canónicos) y `07-informes/` (informes de cierre). Este documento es la vista pública del [roadmap canónico](https://github.com/factoria-software/atlas-forge/blob/main/02-backlog/roadmap.md) del proyecto.

## Esquema de versiones

El esquema de versiones vive en `.atlas-forge/version.yml`: cada User Story declara a qué versión pertenece (`version:` en su frontmatter). La versión abierta actual es **0.9**; las versiones futuras planificadas son **0.9.1** y **0.9.2**.

## Estado de la versión 0.9

La versión 0.9 es el **pipeline centrado en el backlog**: el backlog es el panel de control central del producto y todo el trabajo se despliega desde él (Epic → User Story → Task → Implementar) con botones, no escribiendo Markdown a mano ni conversando con cada agente por separado.

### Implementado en 0.9

| Área | Qué incluye |
|---|---|
| **Pipeline backlog-céntrico** (AF-022) | Roles de Arquitecto y Tester, generadores Epic→US→Task con validador determinista + auto-auditoría, ciclo guiado por estados Developer→Tester→Arquitecto, retrabajo de Task al mismo Developer tras un `FALLO` del Tester. |
| **Formato estructurado del backlog** (AF-027) | Frontmatter YAML + cuerpo Markdown para cada Epic/User Story/Task; `state` de Task y User Story como vocabulario canónico. |
| **Máquinas de estado unificadas** (AF-040) | `core/state_machines.py` como única fuente de verdad de estados y transiciones legales de Task y User Story. |
| **Cola de despacho y visor del pipeline** (AF-042) | Cola de despacho por proyecto (`queued / dispatched / failed / completed`, más `awaiting_tester` derivado), pestaña Pipeline en la web con la cola en tiempo real. |
| **Sesiones de proyecto simultáneas** (AF-029) | Múltiples sesiones vivas en paralelo, una por proyecto; cambiar el proyecto activo no detiene agentes de otros proyectos. |
| **Reconciliación de agentes al arrancar** (AF-031) | Al arrancar `atlas-forge-api`, las sesiones tmux vivas se reconocen por su nombre determinista y se re-registran como agentes `idle` sin relanzar su runtime. |
| **Log de agente en vivo en la web** (AF-032) | `WS /ws/agents/{agent_id}/pane`: un canal por conexión, solo lectura, un agente a la vez. |
| **Reinicio seguro de Atlas Forge** (AF-037) | Detección de backend duplicado al arrancar, `POST /system/restart`, procedimiento de reinicio que no mata el servidor tmux. |
| **Acciones transversales** (AF-025) | Acciones web: documentar, analizar-arquitectura, sugerir-ideas, testear, auditar-ux, auditar-oss, auditar-backlog, verificar-auditoria, testear-ui, indexar. |
| **Catálogo único de scripts y acciones** (AF-034) | `GET /scripts` combina scripts genéricos, scripts de proyecto y acciones transversales en un único catálogo. |
| **Análisis de hilos paralelizables** (AF-026) | Módulo `dependency_graph.py`, endpoint `POST /backlog/epic/{epic_id}/analyze-threads`. |
| **Modelo de versión unificado** (AF-036) | `version` como campo canónico de entrega (en vez de `fase`), vista "Por Versión" en la web, validador del conjunto `{0.9, 0.9.1, 0.9.2}`. |
| **Creación de items desde lenguaje natural** (AF-036) | `POST /backlog/epic/from-description`, `.../from-description-us`, `.../from-description-task` con cola de peticiones al Arquitecto. |

### Base operativa (Epics DONE)

| Epic | Qué incluye |
|---|---|
| **AF-001** Gestión de Workspace | Descubrimiento de repos Git, proyecto activo persistido, scripts de proyecto. |
| **AF-002** Panel de control y supervisión | Interfaz web como única interfaz: proyectos, agentes, Jobs, backlog. |
| **AF-014** Herramientas locales | Scribe: resumen/indexación local (Ollama), incluida la operación `index_scripts`. |
| **AF-016** API Backend | FastAPI: agentes, Jobs, backlog, scripts, WebSockets, `/ui/` estático, systemd. |
| **AF-018** Scripts genéricos | Catálogo de 7 scripts genéricos + prosa de Scribe. |
| **AF-020** Gestión de backlog | Endpoints de listado/detalle, lanzar desarrollo, vistas en la web. |
| **AF-021** Interfaz web | Web completa: proyectos, agentes, Jobs, scripts, backlog, modelos. |
| **AF-025** Acciones transversales | 10 acciones de proyecto (ver arriba). |
| **AF-026** Análisis de hilos paralelizables | Ver arriba. |
| **AF-029** Sesiones de proyecto simultáneas | Ver arriba. |
| **AF-032** Log de agente en vivo | Ver arriba. |
| **AF-037** Reinicio seguro | Ver arriba. |
| **AF-040** Máquinas de estado unificadas | Ver arriba. |

### Epics con trabajo DONE pendiente de promoción formal

| Epic | Nota |
|---|---|
| **AF-022** Pipeline backlog-céntrico | Casi todas las User Stories DONE; el pipeline completo está operativo. |
| **AF-024** Mejoras UX+Producto de la web | La mayoría de User Stories DONE; se añaden mejoras según el uso real. |
| **AF-030** Cola de cierre hacia el Arquitecto | Implementada (cola append-only + watcher). |
| **AF-031** Reconciliación de agentes al arrancar | Implementada. |

## Planificado, no implementado

### 0.9.1

| Epic | Notas |
|---|---|
| **AF-044** Auditor operativo | Auditoría dirigida por ámbito o pregunta, persistencia de hallazgos, historial. |
| **AF-045** Rol investigador | Nuevo rol para investigación bajo demanda, integrado en la web. |
| **AF-046** Documentador integrado en el pipeline | Mecanismo de trabajos persistentes → cola → agente consumidor, con el Documentador como primer consumidor. |
| **AF-047** Modo de comunicación y control de agentes | Estudio y decisión de tmux vs `opencode serve`/CLI para el control de agentes. |
| **AF-048** Rendimiento de respuesta del backlog | Caché del `BacklogGraph` por proyecto con invalidación por `mtime`; parser YAML más rápido. |

### 0.9.2 y posteriores

| Epic | Notas |
|---|---|
| **AF-006** Context Engine | Preparación de contexto relevante por Job. Sin Tasks. |
| **AF-007** Knowledge Engine | Reutilización de conocimiento del proyecto. Sin Tasks. |
| **AF-008** Dispatcher v2 | Pipeline con dependencias declarativas, reintentos, coordinación multi-agente automática y resolución de capacidades. |
| **AF-009** Automation Engine | Automatización de operaciones repetitivas. Sin Tasks. |
| **AF-010** Capability Engine | Catálogo de capacidades del sistema. Sin Tasks. |
| **AF-011** Plugin System | Sin Tasks. **No existe sistema de plugins ni MCP.** |
| **AF-012** Development Automations | Automatizaciones de desarrollo. Sin Tasks. |
| **AF-013** Gestión de configuración | En espera (backlog hold): solo se retoma con una necesidad real de configuración multi-usuario. |
| **AF-023** Supervisión del ciclo de vida | Detección automática de agentes atascados y recuperación; escalado autónomo configurable. |
| **AF-028** Barra de control persistente de agentes críticos | Barra del Arquitecto existente; ampliación a otros agentes sin desgranar. |
| **AF-033** Coste real de desarrollo por Task | Medición de coste por Task. |
| **AF-035** Creación de un proyecto nuevo | Crear un proyecto desde cero (no solo seleccionar). |
| **AF-038** Documentación e informes en la web | Vista de documentación e informes en la web. |
| **AF-039** Integración con sistemas externos | Integración con herramientas externas de gestión de trabajo. |
| **AF-041** Observabilidad y telemetría | Logging estructurado, métricas, analítica. |
| **AF-042** Visor del pipeline | El resto del alcance (correlación agentes↔Jobs, orden de la cola y por qué). |
| **AF-043** Paralelismo Developer/Tester y retrabajo | Test-planting del Tester, retrabajo prioritario y eventos de telemetría (retrabajo básico ya operativo). |
| **AF-050** Diseño previo al desarrollo | Planificación y arquitectura previas al desarrollo. Sin desgranar. |

## Fuera del roadmap

| Epic | Nota |
|---|---|
| **AF-015** Acceso remoto (SSH+tmux) | Descartado: la web cubre el acceso desde cualquier dispositivo. |
| **AF-017** App móvil nativa | Retirado: la web es la única interfaz. |
| **AF-019** Interfaz de terminal (TUI) | Retirado: la web es la única interfaz. |
| **AF-049** Unificar el modelo de versión | Deprecado: su alcance se completó dentro de 0.9 (vista y campo `version`). |

## Criterio de funcionalidad

Se considera que Atlas Forge es funcional cuando puede: gestionar múltiples proyectos, mantener sesiones persistentes, administrar agentes en distintos runtimes, coordinar Jobs mediante pipelines, ejecutar automatizaciones, preparar contexto automáticamente, reutilizar conocimiento, minimizar el uso del modelo remoto, incorporar capacidades mediante plugins y proporcionar visión operativa.

**Estado actual (0.9):** el pipeline de backlog guiado por estados (Developer→Tester→Arquitecto) con retrabajo, el multi-runtime/multi-modelo (Claude Code, OpenCode, Codex), el ahorro de tokens con Scribe y la web como única interfaz son reales y operativos. La gestión de contexto/conocimiento, capacidades, plugins, telemetría y el pipeline declarativo completo son trabajo futuro.

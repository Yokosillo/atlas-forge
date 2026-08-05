# Desarrollo

Guía para nuevos desarrolladores que quieran compilar, probar, depurar y ampliar Factory Brain.

## Cómo compilar / instalar

```bash
cd 04-src
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

No hay paso de compilación: es un paquete Python puro. El `-e` enlaza el paquete al código fuente (cambios en `04-src/src` se reflejan al instante). Los entrypoints `brain` y `brain-api` quedan disponibles en el `.venv/bin/`.

## Cómo ejecutar tests

```bash
cd 04-src
pytest                      # suite completa
pytest tests/test_job_dispatch.py -v   # un módulo concreto
pytest tests/test_scribe.py -k index   # filtrar por nombre
```

- Config de pytest en `pyproject.toml`: `testpaths = ["tests"]`, `asyncio_mode = "auto"`.
- Los tests usan `TestClient` en memoria (httpx) y sockets tmux propios; no requieren un runtime real ni Ollama.
- Conciencia de aislamiento: los registries singletons (`job_history`, `job_cancellation`, `plan_registry`, cola de veredictos…) tienen `_reset_registry_for_tests()`.

## Cómo depurar

- **Backend**: arranca con `brain-api --host 127.0.0.1` para desarrollo local y prueba contra `http://127.0.0.1:8000`. Los errores HTTP llevan el `detail` en español del dominio.
- **Web**: sirve en `/ui/` del mismo backend; abre el inspector del navegador (consola + red).
- **Agentes/rtimes**: `GET /agents/{id}/pane` devuelve el contenido textual del pane tmux del agente. También puedes `tmux -L factory-brain attach` en el host.
- **Informes de cierre**: cada Job de un plan escribe `07-informes/<story_id>/<job_id>.md`; los veredictos rechazados escriben `_rechazo.md`.

## Arquitectura para el desarrollo

- **Dominio** (`brain/`): sin dependencia de interfaz. Los clientes (web, TUI, Android) consumen solo la API (`brain/api/routes.py`).
- **Test de fronteras**: `tests/test_module_boundaries.py` verifica que los clientes no importan dominio directamente salvo excepciones acotadas (catálogo estático de agentes, configuración de disco). **Añade tu cambio sin romper este test.**
- **Registries**: todos in-process, con método `_reset_registry_for_tests()`.

## Cómo añadir un agente (rol)

1. Crea `04-src/src/brain/agents/<rol>.py`:
   - Define `ROL` (string), el prompt base y un `build_<rol>_prompt(project_path)` que concatene `project_governance_instruction(project_path, ROL)`.
   - Define la función de registro (nueva instancia o con reutilización, según el rol).
   - Cierra con `register_role(RoleConfig(role=..., governance_filename=..., prompt=..., prompt_builder=..., register_fn=...))`.
2. Añade el fichero de gobernanza `00-gobierno/<GOVERNANCE>.md` en el proyecto que lo use.
3. Exporta el rol desde `agents/__init__.py`.
4. Añade tests: `test_agent_options_catalog.py` (combinaciones), `test_api_routes_agents.py` (≥6 combos), `test_module_boundaries.py`.

Ejemplo real a seguir: `04-src/src/brain/agents/director.py`.

## Cómo añadir un runtime

1. Crea `04-src/src/brain/runtime/<runtime>.py` con `register_<runtime>_runtime(runtime_id=...) → Runtime` (comando, args, tipo) y `build_prompt_args(prompt) -> list[str]` (cómo se pasa el prompt al CLI).
2. Registra el builder en el registry de `runtime/generic.py` (`_prompt_args_builder_by_type`).
3. Añádelo al catálogo de modelos (`models.yml`) con su `runtime` y a `_SUPPORTED_RUNTIMES` en `models_catalog.py`.
4. Si soporta cambio de modelo en caliente, amplía `agent_model.py` y los endpoints `GET/PUT /agents/{id}/model`.
5. Tests: `tests/test_<runtime>_runtime.py`.

Ejemplo real: `04-src/src/brain/runtime/opencode.py`.

## Cómo añadir una herramienta / acción

Para una **acción transversal** (pestaña Acciones de la web):
1. Añade la acción a `brain/actions/transversal.py` (`ACCIONES_DISPONIBLES` + función `_dispatch_<accion>_action`).
2. La acción puede ser de agente (Job al Arquitecto), determinista (script) o headless (subproceso).
3. Persiste el informe con timestamp en `07-informes/<US>/` sin sobrescribir.
4. Añade el botón en `10-web/app.js` (array `ACCIONES`) y el endpoint ya es único (`POST /project/actions/{action_id}`).
5. Tests: `tests/test_actions_transversal_unit.py`, `tests/test_api_project_actions.py`.

Para un **script genérico**:
1. Añade la entrada a `GENERIC_SCRIPTS` en `brain/workspace/generic_scripts.py`.
2. Implementa su ejecución (determinista, con `ScriptRunResult`).
3. Actualiza el conteo en `tests/test_generic_scripts.py`.
4. Automáticamente aparece en `GET /scripts` y en las tres interfaces.

## Cómo añadir un endpoint

1. Encuentra la capacidad de dominio correspondiente (los endpoints son capas finas).
2. Añade la ruta en `04-src/src/brain/api/routes.py` (devolviendo los objetos ya serializados del dominio; errores como `HTTPException` con `detail` del dominio).
3. Publica eventos WebSocket si el cliente debe ver el progreso (ver `api/events.py`, patrón `jobs_hub`/`plans_hub`).
4. Tests de API en `tests/test_api_routes_*.py` (patrón `TestClient`).

## Convenciones del backlog

- Todo desarrollo parte de una **Task existente** en `02-backlog/`; no implementar funcionalidades sin representación en el backlog.
- Estados cerrados: `TODO | IN_PROGRESS | REVIEW | DONE`. Una Task/US solo es `DONE` cuando cumple todos sus criterios de aceptación.
- Los informes de cierre van a `07-informes/<story_id>/` (ver `write_job_report`).

## Contribución

- **Abre una Issue o discusión** antes de cambios grandes: el backlog (`02-backlog/`) es la fuente canónica y todo trabajo parte de una Task existente.
- **No rompas el aislamiento de módulos**: los clientes solo consumen la API; verifica `tests/test_module_boundaries.py`.
- **Añade tests** con cada cambio y ejecuta la suite completa (`pytest`) antes de pedir revisión.
- **Mantén la documentación al día**: esta documentación (`docs/`) refleja el estado real; no documentes funcionalidades planificadas como si existieran.
- **Estilo**: Python 3.10+, dataclasses inmutables donde proceda, errores de dominio con mensaje explícito en español, `_reset_registry_for_tests()` en cualquier registro in-process nuevo.
- **Modelo de revisión**: el Arquitecto revisa el trabajo del Developer y emite un veredicto estructurado (`APROBADO` / `APROBADO_CON_OBSERVACIONES` / `RECHAZADO`) antes de que las Tasks se marquen `DONE`.

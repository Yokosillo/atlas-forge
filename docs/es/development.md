# Desarrollo

Guía para nuevos desarrolladores que quieren construir, probar, depurar y extender Factory Brain.

## Cómo compilar / instalar

```bash
cd 04-src
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

No hay paso de compilación: es un paquete Python puro. `-e` enlaza el paquete al código fuente (los cambios en `04-src/src` se reflejan al instante). Los entrypoints `brain` y `brain-api` quedan disponibles en `.venv/bin/`.

## Cómo ejecutar los tests

```bash
cd 04-src
pytest                      # suite completa
pytest tests/test_job_dispatch.py -v   # un módulo específico
pytest tests/test_scribe.py -k index   # filtrar por nombre
```

- Config de pytest en `pyproject.toml`: `testpaths = ["tests"]`, `asyncio_mode = "auto"`.
- Los tests usan un `TestClient` en memoria (httpx) y sus propios sockets de tmux; no requieren un runtime real ni Ollama.
- Conciencia de aislamiento: los registries singleton (`job_history`, `job_cancellation`, cola de veredictos…) tienen `_reset_registry_for_tests()`.

## Cómo depurar

- **Backend**: arranca con `brain-api --host 127.0.0.1` para desarrollo local y prueba contra `http://127.0.0.1:8000`. Los errores HTTP llevan el `detail` del dominio.
- **Web**: servida en `/ui/` del mismo backend; abre el inspector del navegador (consola + red).
- **Agentes/runtimes**: `GET /agents/{id}/pane` devuelve el contenido textual del pane de tmux del agente. También puedes `tmux -L factory-brain attach` en el host.
- **Informes de cierre**: cada Job escribe `07-informes/<story_id>/<job_id>.md`; los veredictos rechazados escriben `_rechazo.md`.

## Arquitectura para desarrollo

- **Dominio** (`brain/`): sin dependencia de interfaz. Los clientes (la web) consumen solo la API (`brain/api/routes.py`).
- **Test de frontera**: `tests/test_module_boundaries.py` verifica que los clientes no importan el dominio directamente salvo excepciones acotadas (catálogo estático de agentes, configuración de disco). **Haz tu cambio sin romper este test.**
- **Registries**: todos en proceso, con un método `_reset_registry_for_tests()`.

## Cómo añadir un agente (rol)

1. Crea `04-src/src/brain/agents/<role>.py`:
   - Define `ROL` (string), el prompt base y un `build_<role>_prompt(project_path)` que concatena `project_governance_instruction(project_path, ROL)`.
   - Define la función de registro (instancia nueva o con reuso, según el rol).
   - Termina con `register_role(RoleConfig(role=..., governance_filename=..., prompt=..., prompt_builder=..., register_fn=...))`.
2. Añade el fichero de gobernanza `00-gobierno/<GOVERNANCE>.md` en el proyecto que lo usa.
3. Exporta el rol desde `agents/__init__.py`.
4. Añade tests: `test_agent_options_catalog.py` (combinaciones), `test_api_routes_agents.py` (≥6 combos), `test_module_boundaries.py`.

Ejemplo real a seguir: `04-src/src/brain/agents/tester.py`.

## Cómo añadir un runtime

1. Crea `04-src/src/brain/runtime/<runtime>.py` con `register_<runtime>_runtime(runtime_id=...) → Runtime` (comando, args, tipo) y `build_prompt_args(prompt) -> list[str]` (cómo se pasa el prompt a la CLI).
2. Registra el constructor en el registry `runtime/generic.py` (`_prompt_args_builder_by_type`).
3. Añádelo al catálogo de modelos (`models.yml`) con su `runtime` y a `_SUPPORTED_RUNTIMES` en `models_catalog.py`.
4. Si soporta cambio de modelo en caliente, extiende `agent_model.py` y los endpoints `GET/PUT /agents/{id}/model`.
5. Tests: `tests/test_<runtime>_runtime.py`.

Ejemplo real: `04-src/src/brain/runtime/opencode.py`.

## Cómo añadir una herramienta / acción

Para una **acción transversal** (pestaña Acciones de la web):
1. Añade la acción a `brain/actions/transversal.py` (`ACCIONES_DISPONIBLES` + una función `_dispatch_<action>_action`).
2. La acción puede ser basada en agente (Job al Arquitecto), determinista (script) o headless (subprocess).
3. Persiste el informe con marca de tiempo en `07-informes/<US>/` sin sobrescribir.
4. Añade el botón en `10-web/app.js` (array `ACCIONES`); el endpoint ya es único (`POST /project/actions/{action_id}`).
5. Tests: `tests/test_actions_transversal_unit.py`, `tests/test_api_project_actions.py`.

Para un **script genérico**:
1. Añade la entrada a `GENERIC_SCRIPTS` en `brain/workspace/generic_scripts.py`.
2. Implementa su ejecución (determinista, con `ScriptRunResult`).
3. Actualiza el conteo en `tests/test_generic_scripts.py`.
4. Aparece automáticamente en `GET /scripts` y en las tres interfaces.

## Cómo añadir un endpoint

1. Encuentra la capacidad de dominio correspondiente (los endpoints son capas finas).
2. Añade la ruta en `04-src/src/brain/api/routes.py` (devolviendo los objetos ya serializados del dominio; errores como `HTTPException` con el `detail` del dominio).
3. Publica eventos WebSocket si el cliente debe ver el progreso (ver `api/events.py`, patrón `jobs_hub`).
4. Tests de API en `tests/test_api_routes_*.py` (patrón `TestClient`).

## Convenciones de backlog

- Todo el desarrollo arranca de una **Task existente** en `02-backlog/`; no implementes funcionalidad sin representación en el backlog.
- Estados cerrados: `TO_DO | EN_DESARROLLO | IN_PROGRESS | REVIEW | DONE | POSTERGADA` (Task), más `NO_TASKS`/`EN_DISEÑO` para User Stories. Una Task/US solo es `DONE` cuando cumple todos sus criterios de aceptación.
- Los informes de cierre van a `07-informes/<story_id>/` (ver `write_job_report`).

## Contribución

- **Abre un Issue o discussion** antes de cambios grandes: el backlog (`02-backlog/`) es la fuente canónica y todo el trabajo arranca de una Task existente.
- **No rompas el aislamiento de módulos**: los clientes solo consumen la API; verifica `tests/test_module_boundaries.py`.
- **Añade tests** con cada cambio y ejecuta la suite completa (`pytest`) antes de pedir revisión.
- **Mantén la documentación actualizada**: esta documentación (`docs/`) refleja el estado real; no documentes funcionalidad planificada como si existiera.
- **Estilo**: Python 3.10+, dataclasses inmutables cuando proceda, errores de dominio con mensaje explícito, `_reset_registry_for_tests()` en cualquier registry en proceso nuevo.
- **Modelo de revisión**: el Arquitecto revisa el trabajo del Developer y emite un veredicto estructurado (`APROBADO` / `APROBADO_CON_OBSERVACIONES` / `RECHAZADO`) antes de que las Tasks se marquen `DONE`.
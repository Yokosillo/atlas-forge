# Development

Guide for new developers who want to build, test, debug and extend Factory Brain.

## How to build / install

```bash
cd 04-src
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

There is no build step: it is a pure Python package. `-e` links the package to the source code (changes in `04-src/src` are reflected instantly). The `brain` and `brain-api` entrypoints become available in `.venv/bin/`.

## How to run tests

```bash
cd 04-src
pytest                      # full suite
pytest tests/test_job_dispatch.py -v   # a specific module
pytest tests/test_scribe.py -k index   # filter by name
```

- pytest config in `pyproject.toml`: `testpaths = ["tests"]`, `asyncio_mode = "auto"`.
- Tests use an in-memory `TestClient` (httpx) and their own tmux sockets; they do not require a real runtime or Ollama.
- Isolation awareness: the singleton registries (`job_history`, `job_cancellation`, `plan_registry`, verdict queue…) have `_reset_registry_for_tests()`.

## How to debug

- **Backend**: start with `brain-api --host 127.0.0.1` for local development and test against `http://127.0.0.1:8000`. HTTP errors carry the domain `detail`.
- **Web**: served at `/ui/` of the same backend; open the browser inspector (console + network).
- **Agents/runtimes**: `GET /agents/{id}/pane` returns the textual content of the agent's tmux pane. You can also `tmux -L factory-brain attach` on the host.
- **Closing reports**: each Job of a plan writes `07-informes/<story_id>/<job_id>.md`; rejected verdicts write `_rechazo.md`.

## Architecture for development

- **Domain** (`brain/`): no interface dependency. Clients (web, TUI, Android) consume only the API (`brain/api/routes.py`).
- **Boundary test**: `tests/test_module_boundaries.py` verifies that clients do not import the domain directly except for bounded exceptions (static agent catalog, disk configuration). **Add your change without breaking this test.**
- **Registries**: all in-process, with a `_reset_registry_for_tests()` method.

## How to add an agent (role)

1. Create `04-src/src/brain/agents/<role>.py`:
   - Define `ROL` (string), the base prompt and a `build_<role>_prompt(project_path)` that concatenates `project_governance_instruction(project_path, ROL)`.
   - Define the registration function (new instance or with reuse, depending on the role).
   - Finish with `register_role(RoleConfig(role=..., governance_filename=..., prompt=..., prompt_builder=..., register_fn=...))`.
2. Add the governance file `00-gobierno/<GOVERNANCE>.md` in the project that uses it.
3. Export the role from `agents/__init__.py`.
4. Add tests: `test_agent_options_catalog.py` (combinations), `test_api_routes_agents.py` (≥6 combos), `test_module_boundaries.py`.

Real example to follow: `04-src/src/brain/agents/director.py`.

## How to add a runtime

1. Create `04-src/src/brain/runtime/<runtime>.py` with `register_<runtime>_runtime(runtime_id=...) → Runtime` (command, args, type) and `build_prompt_args(prompt) -> list[str]` (how the prompt is passed to the CLI).
2. Register the builder in the `runtime/generic.py` registry (`_prompt_args_builder_by_type`).
3. Add it to the model catalog (`models.yml`) with its `runtime` and to `_SUPPORTED_RUNTIMES` in `models_catalog.py`.
4. If it supports hot model switching, extend `agent_model.py` and the `GET/PUT /agents/{id}/model` endpoints.
5. Tests: `tests/test_<runtime>_runtime.py`.

Real example: `04-src/src/brain/runtime/opencode.py`.

## How to add a tool / action

For a **cross-cutting action** (web Actions tab):
1. Add the action to `brain/actions/transversal.py` (`ACCIONES_DISPONIBLES` + a `_dispatch_<action>_action` function).
2. The action can be agent-based (Job to the Architect), deterministic (script) or headless (subprocess).
3. Persist the report with a timestamp in `07-informes/<US>/` without overwriting.
4. Add the button in `10-web/app.js` (array `ACCIONES`); the endpoint is already unique (`POST /project/actions/{action_id}`).
5. Tests: `tests/test_actions_transversal_unit.py`, `tests/test_api_project_actions.py`.

For a **generic script**:
1. Add the entry to `GENERIC_SCRIPTS` in `brain/workspace/generic_scripts.py`.
2. Implement its execution (deterministic, with `ScriptRunResult`).
3. Update the count in `tests/test_generic_scripts.py`.
4. It automatically appears in `GET /scripts` and in the three interfaces.

## How to add an endpoint

1. Find the corresponding domain capability (endpoints are thin layers).
2. Add the route in `04-src/src/brain/api/routes.py` (returning the domain's already-serialized objects; errors as `HTTPException` with the domain `detail`).
3. Publish WebSocket events if the client must see progress (see `api/events.py`, `jobs_hub`/`plans_hub` pattern).
4. API tests in `tests/test_api_routes_*.py` (`TestClient` pattern).

## Backlog conventions

- All development starts from an **existing Task** in `02-backlog/`; do not implement functionality without backlog representation.
- Closed states: `TODO | IN_PROGRESS | REVIEW | DONE`. A Task/US is only `DONE` when it meets all its acceptance criteria.
- Closing reports go to `07-informes/<story_id>/` (see `write_job_report`).

## Contribution

- **Open an Issue or discussion** before big changes: the backlog (`02-backlog/`) is the canonical source and all work starts from an existing Task.
- **Do not break module isolation**: clients only consume the API; verify `tests/test_module_boundaries.py`.
- **Add tests** with every change and run the full suite (`pytest`) before asking for review.
- **Keep the documentation up to date**: this documentation (`docs/`) reflects the real state; do not document planned functionality as if it existed.
- **Style**: Python 3.10+, immutable dataclasses where appropriate, domain errors with an explicit message, `_reset_registry_for_tests()` on any new in-process registry.
- **Review model**: the Architect reviews the Developer's work and issues a structured verdict (`APROBADO` / `APROBADO_CON_OBSERVACIONES` / `RECHAZADO`) before the Tasks are marked `DONE`.

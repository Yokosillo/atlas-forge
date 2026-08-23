# Validación determinista de Atlas Forge

## Propósito

Separar las comprobaciones mecánicas, repetibles y objetivas de las decisiones que requieren un agente.

## Regla

Si una condición puede comprobarse de forma determinista, debe comprobarse con código antes de pedir al LLM que la interprete.

## Validaciones de backlog

Existen dos familias independientes.

### 1. Formato

`04-src/scripts/validate_backlog.py`

Utiliza `validate_backlog_file_v2` de `atlas_forge/backlog/validator_v2.py`.

Modos:

- por defecto: ficheros staged del commit;
- `--batch <directorio>`: lote arbitrario en modo lectura.

El validador no modifica ni mueve ficheros.

### 2. Coherencia de estados

`04-src/scripts/promote_states.py --check` / `--apply`

El estado de un padre es una **función determinista** del estado de sus hijos (AF-040: `derive_user_story_state` en `04-src/src/atlas_forge/core/state_machines.py` es la única fuente de verdad). La regla de derivación es la única fuente de verdad de la coherencia:

**User Story**

1. Con **0 Tasks** → `NO_TASKS`.
2. Con **≥1 Task** → el estado de su Task **menos avanzada**, según el orden de progreso `READY` < `TO_DEVELOP` < `IN_PROGRESS` < `IN_REVIEW` < `DONE`. Si la menos avanzada está `DONE` (todas lo están) → `IN_REVIEW` (validación final del Arquitecto pendiente; nunca `DONE` automático).

**Epic**

1. Con **0 User Stories** → `READY`.
2. Con **≥1 User Story** → `DONE` si todas están `DONE` (una US en `IN_REVIEW` NO cuenta como `DONE`); si no, al estado de su User Story **más retrasada**, con `NO_TASKS`/`TO_PLAN`/`READY` → `READY`.

`--check` detecta drift (estado en disco que no coincide con la derivación).

`--apply` consolida en **ambos sentidos** en una sola pasada idempotente: promueve (Task → `IN_REVIEW` para la US cuando todos los hijos están `DONE`; Epic → `DONE`) y reabre (padre `DONE` o adelantado con un hijo que deja de estarlo → estado más retrasado). La regla es simétrica: nunca puede quedar desactualizada por ningún sentido. Nota: hoy `--apply` promueve la US a `IN_REVIEW` (nunca a `DONE` — el `DONE` de la US exige el veredicto del Arquitecto); el resto del mecanismo es idéntico.

**Estados transitorios propiedad del pipeline** (no derivables de los hijos; los fija el pipeline explícitamente y la consolidación los respeta): `TO_PLAN` de User Story (solo válido con 0 Tasks, mientras el Arquitecto aterriza las Tasks) y `IN_REVIEW` de User Story (solo válido con todas sus Tasks `DONE`, durante el veredicto del Arquitecto). `OUT_OF_SCOPE` es exclusivo de User Story (antes `OUT_OF_SCOPE`).

La detección se reutiliza en las lecturas del backlog para evitar presentar al usuario una jerarquía falsamente cerrada.

## Drift fuera del pipeline

Los estados de Task y User Story los gobierna el pipeline. Si un cambio de estado de Tasks se produce **fuera** del pipeline (p. ej. edición manual de un fichero), la User Story debe actualizarse igualmente, tanto avanzando como retrasándose, según la regla de derivación anterior — tanto por la consolidación (`--apply`) como en las lecturas del backlog.

## Pre-commit

El hook local ejecuta ambos controles:

1. reconciliación de estados;
2. validación de formato.

Un fallo bloquea el commit.

El hook se instala mediante:

```bash
bash 04-src/scripts/install_git_hooks.sh
```

La instalación local debe mantenerse sincronizada con el repositorio.

## Importante

Estos procedimientos describen el mecanismo técnico actual. Si en el futuro existe CI remoto, no se debe interpretar que el hook local desaparece automáticamente. CI y pre-commit pueden ser controles complementarios.

## Validación de documentación y backlog

El Tester puede verificar formato y contenido cuando una Task modifica documentación o backlog.

El Arquitecto es responsable de que el backlog generado pase el validador determinista.

## Evidencia

Una validación útil debe indicar:

- qué se comprobó;
- comando o mecanismo utilizado;
- resultado;
- alcance de la comprobación;
- limitaciones.

"No hay errores" sin explicar qué se ejecutó no constituye evidencia suficiente.

## Fuente de verdad

Este documento describe las reglas de validación. Los nombres exactos de scripts y módulos deben contrastarse con el repositorio si han cambiado.

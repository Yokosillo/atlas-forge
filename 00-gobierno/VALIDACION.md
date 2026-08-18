# Validación determinista de Factory Brain

## Propósito

Separar las comprobaciones mecánicas, repetibles y objetivas de las decisiones que requieren un agente.

## Regla

Si una condición puede comprobarse de forma determinista, debe comprobarse con código antes de pedir al LLM que la interprete.

## Validaciones de backlog

Existen dos familias independientes.

### 1. Formato

`04-src/scripts/validate_backlog.py`

Utiliza `validate_backlog_file_v2` de `brain/backlog/validator_v2.py`.

Modos:

- por defecto: ficheros staged del commit;
- `--batch <directorio>`: lote arbitrario en modo lectura.

El validador no modifica ni mueve ficheros.

### 2. Coherencia de estados

`04-src/scripts/promote_states.py --check`

Reglas:

1. User Story → `DONE` si tiene ≥1 Task y todas las Tasks están `DONE`.
2. Epic → `DONE` si tiene ≥1 User Story y todas las User Stories están `DONE`.

`--check` detecta drift.

`--apply` aplica promociones deterministas.

Las operaciones deben ser idempotentes.

## Drift inverso

Si una User Story o Epic está `DONE` pero un hijo directo deja de estar `DONE`, la consolidación determinista lo corrige: el padre se reabre automáticamente al estado del hijo **más retrasado**, según el orden de progreso `TODO` < `EN_DESARROLLO` < `REVIEW` < `DONE`. Un hijo `POSTERGADA` reabre el padre a `TODO`. El padre solo recibe estados válidos de su propio tipo (p. ej. una User Story nunca se marca `POSTERGADA`; un hijo `SIN_TAREAS`/`EN_DISEÑO` reabre una Epic a `TODO`).

La regla es simétrica a la promoción: un padre con todos sus hijos `DONE` se promueve a `DONE`; un padre `DONE` con un hijo que deja de estarlo se reabre. Ambas direcciones las aplica `promote_states.py --apply` en una sola pasada idempotente.

La detección se reutiliza en las lecturas del backlog para evitar presentar al usuario una jerarquía falsamente cerrada.

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

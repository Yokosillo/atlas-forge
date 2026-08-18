# Migración de gobierno v1 → v2

## Sustituciones directas

| Actual | Acción |
|---|---|
| `METODOLOGIA.md` | Sustituir por `METODOLOGIA.md` + extraer contenido a `PIPELINE.md`, `BACKLOG.md`, `VALIDACION.md` y `PROTOCOLO_REORIENTACION.md` |
| `ARQUITECTO.md` | Sustituir por `ARQUITECTO.md`; dependencias técnicas pasan a `DISPATCHER.md`, `PRUEBAS.md`, `VALIDACION.md` |
| `DEVELOPER.md` | Sustituir por `DEVELOPER.md`; pruebas a `PRUEBAS.md`, seguridad a `SEGURIDAD.md`, pipeline a `PIPELINE.md` |
| `TESTER.md` | Sustituir por `TESTER.md`; estrategia de pruebas común a `PRUEBAS.md` |
| `OPERACION.md` | Sustituir por `OPERACION.md`; sigue siendo documento para humanos |
| `UX.md` | Sustituir por `UX.md` |
| `AUDITOR-OSS.md` | Sustituir por `AUDITOR-OSS.md` |
| `DOCUMENTADOR.md` | Sustituir por `DOCUMENTADOR.md` |

## Nuevos

- `00-INDICE.md`
- `PIPELINE.md`
- `BACKLOG.md`
- `VALIDACION.md`
- `PRUEBAS.md`
- `DISPATCHER.md`
- `ROLES.md`
- `SEGURIDAD.md`
- `PROTOCOLO_REORIENTACION.md`

## Qué se elimina del contexto global

Los siguientes datos no deben permanecer en `METODOLOGIA.md`:

- nombres de funciones Python;
- comandos de pre-commit;
- cifras de ficheros existentes;
- fechas de incidentes;
- estado puntual del repositorio;
- detalles de systemd/tmux;
- nombres de implementación que puedan cambiar.

## Correcciones de contradicciones

### Estados Task

La documentación antigua mezclaba `EN_DESARROLLO` e `IN_PROGRESS`.

V2 define `EN_DESARROLLO` como semántica de desarrollo.

Si el código aún acepta `IN_PROGRESS`, debe considerarse compatibilidad pendiente de convergencia, no un segundo estado conceptual.

### Pruebas Web

La documentación antigua mezclaba Playwright y Puppeteer.

V2 separa herramienta de objetivo:

> el requisito es navegador real y evidencia observable.

Antes de ampliar la suite, el agente debe identificar cuál es la suite mantenida actualmente. No se crean dos suites paralelas por defecto.

### Critic

Se elimina como rol independiente. El Arquitecto concentra planificación y veredicto.

### Informes por Task

Se consolida el modelo de un informe por User Story con secciones por Task.

### Cola Architect

`architect_queue.jsonl` queda explícitamente definida como Developer→Arquitecto. El despacho Arquitecto→Developer utiliza `dispatch_queue`.

### Marcadores antiguos

`### STORY_DONE ###` no debe tratarse como contrato general del pipeline. El mecanismo formal de Job utiliza `___FACTORY_BRAIN_JOB_DONE___`; el cierre asíncrono de Task utiliza la cola de Arquitecto.

## Orden de instalación

1. Sustituir los ficheros existentes por V2.
2. Añadir los nuevos.
3. Revisar `AGENTS.md` para que apunte a `00-gobierno/00-INDICE.md`.
4. Revisar `02-backlog/README.md` para alinear estados con `BACKLOG.md`.
5. Verificar que `validator_v2.py` y el código del Dispatcher aceptan la semántica acordada.
6. Si aún existe `IN_PROGRESS`, crear una Task de convergencia antes de eliminarlo del código.
7. Revisar los prompts/runtime que cargan gobierno y reducirlos al contexto específico de cada rol.
8. Ejecutar la suite de pruebas del gobierno y del backlog.

## Orden de lectura recomendado

```text
00-INDICE
   ↓
METODOLOGIA
   ↓
ROLES
   ↓
PIPELINE
   ↓
BACKLOG
   ↓
VALIDACION
   ↓
PRUEBAS
   ↓
documento específico del rol
```

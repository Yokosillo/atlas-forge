# Gobierno del backlog

## Jerarquía oficial

```text
Roadmap
  ↓
Epic
  ↓
User Story
  ↓
Task
```

No existen Capabilities, Features, Iniciativas u otros niveles persistentes entre esos elementos.

Las agrupaciones técnicas pueden utilizarse durante el análisis, pero no se guardan como niveles adicionales del backlog.

## Epic

Una Epic representa una capacidad importante del producto.

Debe declarar, cuando proceda:

- objetivo;
- alcance v1 mínimo;
- diferido a v2;
- dependencias;
- criterios de aceptación;
- estado.

Las User Stories deben cubrir el alcance v1 antes del trabajo diferido.

## User Story

Representa un incremento funcional observable y verificable de forma independiente.

Debe expresar:

- necesidad;
- valor;
- criterios de aceptación;
- prioridad;
- dependencias;
- estado.

### Prueba de independencia

Una pieza de trabajo es candidata a User Story si, al terminarla, alguien puede comprobar una capacidad nueva sin necesitar otro trabajo simultáneo.

Si solo:

- se modifica código interno;
- se prepara un esquema;
- se añade una validación interna;
- se refactoriza;
- se prepara un dato;

entonces normalmente es Task.

## Task

Es la unidad mínima de implementación.

Debe incluir:

- identificador;
- título;
- objetivo;
- descripción;
- criterios de aceptación;
- prioridad;
- dependencias;
- estado.

Una Task no debe convertirse en una User Story solo porque requiera mucho trabajo técnico.

## Estados

### User Story

`SIN_TAREAS`, `EN_DISEÑO`, `TODO`, `EN_DESARROLLO`, `REVIEW`, `DONE`.

### Task

`TODO`, `EN_DESARROLLO`, `REVIEW`, `DONE`, `POSTERGADA`.

Si existe `IN_PROGRESS` en validadores o ficheros antiguos, no debe introducirse como semántica paralela. La convergencia del formato debe resolverse mediante una Task de mantenimiento si el código todavía lo requiere.

## Dependencias

Las dependencias se expresan mediante identificadores de backlog.

Una Task no debe ser despachada si una dependencia obligatoria no está `DONE`.

No se inventan dependencias para ordenar artificialmente el trabajo.

## Formato

El esquema estructural vigente del backlog es el definido por `02-backlog/README.md` y validado por `validate_backlog_file_v2`.

El Arquitecto debe utilizar el validador determinista antes de presentar una propuesta de backlog.

## Principios de trazabilidad

Toda Task debe poder remontarse a:

```text
Epic → User Story → Task
```

Toda implementación debe poder remontarse a la Task.

Toda verificación debe poder remontarse a los criterios de aceptación.

## Regla de no ampliación

Si un Developer encuentra una necesidad que no pertenece a la Task:

1. no la implementa;
2. la documenta como hallazgo;
3. la devuelve al Arquitecto;
4. el Arquitecto decide si crea o modifica backlog.

## Cierre de backlog

El estado del padre no se utiliza como autoridad aislada. Debe ser coherente con los hijos y se comprueba mediante los mecanismos de `VALIDACION.md`.

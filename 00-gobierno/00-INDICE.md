# Gobierno de Factory Brain

Este directorio define el modelo de gobierno, operación y comportamiento de los agentes de Factory Brain.

## Regla de lectura

No todos los agentes deben cargar todos los documentos.

Cada agente recibe el contexto común y, después, únicamente los documentos propios de su función.

## Mapa de documentos

| Documento | Propósito | Audiencia |
|---|---|---|
| `METODOLOGIA.md` | Invariantes y modelo conceptual | Todos los agentes |
| `PIPELINE.md` | Flujo operativo y estados | Dispatcher, Arquitecto, Developer, Tester |
| `BACKLOG.md` | Modelo y reglas del backlog | Arquitecto, Developer, Tester |
| `VALIDACION.md` | Validaciones deterministas y reconciliación | Arquitecto, Tester, Developer |
| `PRUEBAS.md` | Estrategia global de pruebas y evidencia | Todos los roles técnicos |
| `DISPATCHER.md` | Implementación operativa del despacho | Arquitecto, operación |
| `ROLES.md` | Matriz de responsabilidades | Todos los agentes |
| `SEGURIDAD.md` | Secretos, comunicación entre agentes y límites operativos | Todos los agentes |
| `PROTOCOLO_REORIENTACION.md` | Cambios de dirección de producto | Arquitecto, usuario |
| `OPERACION.md` | Operación humana de brain-api | Operador humano |
| `ARQUITECTO.md` | Gobierno específico del Arquitecto | Arquitecto |
| `DEVELOPER.md` | Gobierno específico del Developer | Developer |
| `TESTER.md` | Gobierno específico del Tester | Tester |
| `UX.md` | Diseño de flujos Web nuevos | UX |
| `AUDITOR-OSS.md` | Auditoría pública y UX de producto existente | Auditor-OSS |
| `DOCUMENTADOR.md` | Documentación pública y GitHub | Documentador |

## Grafo de dependencias

```text
                         METODOLOGIA
                              |
             +----------------+----------------+
             |                |                |
          ROLES            PIPELINE          BACKLOG
             |                |                |
             |          +-----+-----+          |
             |          |     |     |          |
             |       DISPATCHER  VALIDACION    |
             |                |       |         |
             +----------------+-------+---------+
                              |
                           PRUEBAS
                              |
        +---------------------+----------------------+
        |            |            |        |        |
   ARQUITECTO    DEVELOPER     TESTER     UX   AUDITOR-OSS
        |            |            |        |        |
        +------------+------------+--------+--------+
                              |
                       DOCUMENTADOR
                              |
                         OPERACION
```

## Regla de autoridad

Cuando dos documentos entren en conflicto:

1. Una decisión explícita y reciente del usuario prevalece sobre cualquier documento.
2. Los invariantes de `METODOLOGIA.md` prevalecen sobre detalles operativos.
3. Los contratos de `PIPELINE.md`, `BACKLOG.md`, `VALIDACION.md` y `PRUEBAS.md` prevalecen sobre explicaciones de rol.
4. Un documento de rol solo puede especializar, nunca contradecir, las reglas comunes.
5. Los hechos de implementación pertenecen a documentación técnica o estado actual; no se convierten automáticamente en reglas de gobierno.

Si aparece una contradicción real, no se resuelve improvisando. Se detiene la decisión afectada, se identifica la fuente de verdad y se actualiza el documento correspondiente.

## Carga recomendada por rol

### Arquitecto

`METODOLOGIA.md` + `ROLES.md` + `PIPELINE.md` + `BACKLOG.md` + `VALIDACION.md` + `PRUEBAS.md` + `DISPATCHER.md` + `ARQUITECTO.md`

### Developer

`METODOLOGIA.md` + `ROLES.md` + `PIPELINE.md` + `BACKLOG.md` + `PRUEBAS.md` + `SEGURIDAD.md` + `DEVELOPER.md`

### Tester

`METODOLOGIA.md` + `PIPELINE.md` + `BACKLOG.md` + `PRUEBAS.md` + `TESTER.md`

### UX

`METODOLOGIA.md` + `ROLES.md` + `PIPELINE.md` + `UX.md`

### Auditor-OSS

`METODOLOGIA.md` + `ROLES.md` + `PRUEBAS.md` + `AUDITOR-OSS.md`

### Documentador

`METODOLOGIA.md` + `ROLES.md` + `BACKLOG.md` + `DOCUMENTADOR.md`

### Operador humano

`OPERACION.md` + la documentación técnica del despliegue.

## Documentos que no deben cargarse como instrucciones globales

Informes de `07-informes/`, estado puntual del sistema, resultados de ejecuciones y detalles históricos no forman parte del contexto global permanente. Se incorporan únicamente cuando el trabajo concreto los necesita.

# Estrategia de pruebas y evidencia

## Objetivo

Las pruebas de Atlas Forge deben demostrar comportamiento, no solo existencia de código.

La pregunta fundamental es:

> ¿Qué evidencia reproducible demuestra que cada criterio de aceptación se cumple y que los casos de fallo relevantes no rompen el sistema?

## Pirámide de pruebas

La estrategia recomendada es:

```text
                 Pruebas E2E / navegador real
                         ▲
                    Integración
                         ▲
                    API / servicio
                         ▲
                  Unidad / dominio
                         ▲
              Validaciones deterministas
```

No todo cambio necesita todos los niveles. La selección debe responder al riesgo y al criterio de aceptación.

## Nivel 0 — Validaciones deterministas

Para backlog, esquemas, estados y contratos mecánicos:

- validadores;
- reconciliación;
- parseadores;
- comprobaciones de formato;
- idempotencia.

Son preferibles a un LLM porque producen resultados reproducibles.

## Nivel 1 — Unitarias

Prueban una unidad aislada.

Deben:

- tener una condición observable;
- aislar dependencias externas cuando el objetivo sea la unidad;
- evitar asserts demasiado débiles;
- cubrir casos normales y bordes relevantes.

Un test no es válido solo porque tenga el nombre correcto. Debe leer y ejercer la lógica que pretende verificar.

## Nivel 2 — Integración

Comprueban la interacción entre módulos reales:

- API + dominio;
- dispatcher + cola;
- persistencia + lógica;
- rutas + servicios;
- estados + backlog.

Cuando el criterio depende de una interacción, un test puramente unitario puede ser insuficiente.

## Nivel 3 — Web y navegador real

Cualquier cambio en `10-web/` que afecte a comportamiento observable debe tener verificación de navegador real.

El mecanismo de referencia actual es Chromium automatizado. El repositorio puede conservar una suite existente basada en otra librería; antes de añadir tests, el agente debe comprobar cuál es la suite canónica real y ampliarla en lugar de crear scripts desechables.

El objetivo no es comprobar que una función JavaScript devuelve lo esperado. Es comprobar que:

1. se sirve la página real;
2. el navegador ejecuta el JavaScript real;
3. el usuario realiza el flujo;
4. el backend responde;
5. el DOM muestra el resultado prometido.

Cuando el estado requerido no puede alcanzarse de forma segura contra el backend real, puede interceptarse la respuesta de red en el navegador para simular únicamente el estado de datos. No se debe sustituir la lógica de negocio del frontend.

## Tests de regresión

Todo bug relevante que haya llegado a una corrección debería dejar una prueba de regresión cuando sea técnicamente razonable.

La prueba debe reproducir el fallo original y fallar si reaparece.

## Casos negativos

Los criterios positivos no bastan.

Cuando sea relevante, deben comprobarse:

- entrada inválida;
- recurso inexistente;
- dependencia no satisfecha;
- estado concurrente;
- timeout;
- error de backend;
- permisos;
- datos vacíos;
- datos duplicados;
- recurso que desaparece durante la operación.

## Carreras y concurrencia

Para UI y Dispatcher son especialmente importantes:

- usuario pulsa mientras polling actualiza;
- dos agentes compiten por el mismo recurso;
- un agente cambia de idle a working durante una decisión;
- una Task cambia de estado mientras se calcula el siguiente despacho;
- backend reinicia mientras la UI está abierta.

Los tests deben comprobar el resultado observable de la carrera, no solo ejecutar dos funciones en paralelo.

## Cobertura de criterios

Cada criterio de aceptación debe tener una relación explícita:

```text
Criterio → evidencia → test o verificación manual
```

Estados posibles:

- `PASA`
- `FALLA`
- `NO VERIFICABLE`

`NO VERIFICABLE` no equivale a `PASA`.

## No duplicación

El Tester no debe repetir mecánicamente una suite completa que el Developer ya ejecutó si no aporta nueva evidencia.

Debe buscar:

- huecos;
- evidencia alternativa;
- casos de borde;
- integración real;
- pruebas que puedan haber sido demasiado débiles.

## Calidad de un test

Un buen test debe:

1. fallar si el comportamiento requerido desaparece;
2. pasar por la ruta real que se quiere proteger;
3. verificar el valor exacto exigido por el criterio;
4. evitar mocks que sustituyan precisamente la lógica bajo prueba;
5. ser repetible;
6. dejar claro qué riesgo protege.

Ejemplo de test débil:

```text
assert len(result) >= 4
```

si el criterio exige exactamente cuatro elementos.

Ejemplo correcto:

```text
assert len(result) == 4
```

cuando esa exactitud forma parte del contrato.

## Evidencia de ejecución

El informe debe registrar:

- comando;
- suite/test concreto;
- resultado;
- duración si es relevante;
- entorno cuando pueda afectar;
- cualquier limitación.

No se debe afirmar que una prueba pasó sin haberla ejecutado.

## Pruebas generadas por Tester

El Tester puede crear tests adicionales para huecos reales.

No debe:

- modificar código de producto;
- modificar backlog;
- crear una batería arbitraria sin relación con criterios.

Los tests que queden en el repositorio pasan a formar parte de la defensa permanente del producto.

## Gate de cierre

Una Task no puede considerarse verificada si:

- falla un criterio;
- un criterio relevante no es verificable;
- el test citado no existe;
- el test no ejerce el código que dice proteger;
- una prueba web requerida no se ha ejecutado en navegador real.

El Arquitecto puede añadir una revisión de conjunto sobre la User Story.

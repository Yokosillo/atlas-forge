# Rol: Diseñador UX + Producto Web

## Objetivo

Diseñar flujos nuevos o rediseños grandes de `10-web/` antes de crear Tasks de implementación.

No audita pantallas existentes. Esa función corresponde a `AUDITOR-OSS.md`.

## Marco

Factory Brain proporciona visibilidad y control sobre una factoría de software.

No es un IDE.

No debe empujar la Web hacia edición de código.

La interfaz debe mostrar el estado real y no obligar al usuario a adivinarlo.

## Encargo

El rol recibe un flujo o pantalla concreto.

No decide por sí mismo qué área rediseñar.

## Especificación obligatoria

Debe cubrir:

1. estados;
2. transiciones;
3. acciones disponibles;
4. acciones deshabilitadas y motivo visible;
5. carreras;
6. datos vacíos;
7. listas largas;
8. competición entre instancias;
9. errores de backend;
10. fuera de alcance;
11. alternativas consideradas;
12. verificación contra backend real.

## Diseño antes de código

No se debe dejar al Developer la decisión de:

- qué botón aparece en cada estado;
- qué pasa después de un error;
- qué ocurre durante polling;
- qué ocurre si dos acciones compiten;
- qué información se conserva al recargar.

Esas decisiones deben quedar especificadas antes de la Task.

## Verificación backend

Antes de diseñar un flujo dependiente de una capacidad del backend:

- localizar el endpoint;
- verificar su contrato;
- distinguir lo existente de lo que requiere backend nuevo.

No asumir que un endpoint existe porque sería conveniente.

## Entregable

```text
# Especificación de UX — <pantalla/flujo> (<fecha>)

## Encargo recibido

## Estados

## Transiciones

## Casos borde

## Fuera de alcance de este diseño

## Alternativas descartadas

## Verificación contra backend real
```

## Restricciones

No tocar código.

No crear backlog.

No auditar pantallas existentes.

Si el encargo es ambiguo, pedir aclaración en lugar de ampliar alcance.

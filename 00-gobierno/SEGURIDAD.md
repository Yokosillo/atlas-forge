# Seguridad y límites operativos

## Secretos

Las credenciales reales deben vivir fuera del código funcional:

- `.env` en la raíz del producto cuando corresponda;
- fuera de Git;
- permisos restrictivos, por ejemplo `0600`.

Nunca:

- imprimir secretos;
- incluir claves en informes;
- poner tokens en backlog;
- copiar credenciales en Jobs;
- registrar valores sensibles en logs.

## Principio de mínimo privilegio

Un agente debe utilizar solo los permisos necesarios para su rol.

El Documentador puede consultar GitHub y realizar cambios explícitamente permitidos, pero no modificar permisos, branch protection, colaboradores o webhooks.

## Operaciones destructivas

Ningún agente debe:

- forzar push;
- borrar branches o tags remotos;
- publicar Releases sin petición explícita en esa invocación;
- activar workflows de GitHub Actions sin confirmación humana;
- realizar cambios destructivos como supuesto efecto secundario de una mejora.

## Comunicación con otros agentes

Cuando el mecanismo de transporte teclea texto directamente en un pane de shell/tmux, las instrucciones deben evitar caracteres con semántica de shell cuando no sean necesarios:

- backticks;
- sustitución `$()`;
- variables `$VAR`;
- pipes;
- `;`;
- `&&`.

La prioridad es transmitir una instrucción inequívoca, no preservar formato Markdown.

## Menús interactivos

Los agentes ejecutados sin supervisión no deben abrir menús interactivos para esperar una decisión humana.

Si pueden resolver una ambigüedad de implementación de bajo impacto, deben decidir y documentarla.

Si la decisión afecta arquitectura, alcance o producto, deben detenerse y utilizar el protocolo de parada.

## Web

Las pruebas Web deben usar el backend real cuando el objetivo sea validar integración. Las interceptaciones de red solo pueden sustituir datos de estado cuando ejecutar ese estado real sea inseguro; nunca deben sustituir la lógica bajo prueba.

## Auditoría

Los agentes deben distinguir entre:

- evidencia observada;
- inferencia;
- estado declarado por documentación;
- estado verificado en código/runtime.

Nunca presentar una inferencia como hecho observado.

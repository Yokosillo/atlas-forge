"""Construcción de la descripción del Job de Tester de UI
(T-FB022-US15-04, US-FB022-15) — amplía el contrato de entrada del
Tester de `tester_input.py` (US-FB022-12) con la instrucción de navegar
la web real (Puppeteer, `00-gobierno/TESTER.md`) para los criterios de
aceptación de la User Story ya cerrada.

Reutiliza `read_acceptance_criteria`/`_format_acceptance_criteria` de
`tester_input.py` en vez de duplicar el parseo de criterios — mismo
formato ya usado por el Tester de código, para que el Tester reciba una
estructura consistente sea cual sea el tipo de Job."""

from __future__ import annotations

from pathlib import Path

from brain.dispatcher.tester_input import (
    _format_acceptance_criteria,
    read_acceptance_criteria,
)


def build_ui_tester_job_description(
    story_id: str,
    reports_root: Path | None = None,
    tasks_dir: Path | None = None,
) -> str:
    """Construye la descripción del Job de Tester de UI para `story_id`
    ya cerrada con veredicto aprobado.

    A diferencia de `build_tester_job_description` (Tester de código,
    diff + huecos de cobertura pytest), este Job no depende de que haya
    cambios sin commitear (`git diff HEAD` fallaría igual si el trabajo
    ya se commiteó, algo habitual en este repo) — el criterio de qué
    probar viene directamente de los criterios de aceptación declarados
    en las Tasks de la Story, igual que hace el Arquitecto al pedir el
    veredicto."""
    acceptance_criteria = read_acceptance_criteria(story_id, tasks_dir)
    acceptance_text = _format_acceptance_criteria(acceptance_criteria)

    return (
        f"Eres el Tester de UI de Factory Brain. La User Story "
        f"'{story_id}' acaba de cerrarse con veredicto aprobado del "
        f"Arquitecto, y su alcance toca `10-web/` — verifica la interfaz "
        f"web real navegando de verdad (Puppeteer), no solo leyendo "
        f"código.\n"
        f"\n"
        f"## Criterios de aceptación de las Tasks de esta User Story\n"
        f"{acceptance_text}\n"
        f"\n"
        f"## Instrucciones\n"
        f"\n"
        f"1. Arranca un backend aislado (mismo mecanismo ya establecido "
        f"en `10-web/tests/harness.js`, `withBackend`) — nunca contra el "
        f"proceso de producción real.\n"
        f"2. Para cada criterio de aceptación anterior que describa una "
        f"pantalla/flujo de `10-web/`, navega el flujo real con "
        f"Puppeteer (clics, estado del DOM, valores) y confirma que "
        f"ocurre lo que el criterio promete.\n"
        f"3. Amplía la suite reutilizable de `10-web/tests/` con un test "
        f"persistente por cada flujo verificado — nunca un script de un "
        f"solo uso que se descarte tras esta verificación "
        f"(`00-gobierno/TESTER.md`).\n"
        f"4. Ejecuta la suite completa (`node 10-web/tests/run.js`) y "
        f"confirma que no hay regresiones en los tests ya existentes.\n"
        f"5. Al terminar, redacta tu informe estructurado con estas "
        f"secciones:\n"
        f"   - Flujos probados: uno por criterio de aceptación de UI, "
        f"con el resultado real (pasa/falla) y evidencia concreta.\n"
        f"   - Tests añadidos: qué test nuevo cubre cada flujo y en qué "
        f"fichero.\n"
        f"   - Resultado de la suite completa: pasa/falla, número de "
        f"tests."
    )

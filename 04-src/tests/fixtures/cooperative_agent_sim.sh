#!/bin/bash
# Simula un runtime cooperativo (como Claude Code/OpenCode instruido) para
# los tests de dispatch_job: lee la instrucción completa desde stdin (tal
# como se la teclearía el mecanismo de auto-reporte en tmux), localiza la
# ruta del fichero de reporte pedido (busca el patrón "escribe tu resultado
# completo en el fichero '<path>'" que dispatch_job incluye siempre), y
# simula "trabajar" un poco antes de escribir su resultado + marcador de
# fin, exactamente como se le pediría a un agente real.
#
# Este script NUNCA invoca binarios reales de Claude Code/OpenCode — es
# un doble de prueba determinista y controlado.
#
# Comportamiento configurable vía variables de entorno:
#   SIM_DELAY: segundos de espera antes de reportar (por defecto 0.3).
#   SIM_FAIL=1: reporta que no pudo completar la instrucción.
#   SIM_ROLE=critic: simula el rol Critic (T-AF008-US02-01) — si detecta
#     el bloque "Resultado del Job anterior" en la instrucción recibida
#     (embebido por create_job al encadenar Jobs), incluye en su propio
#     reporte una referencia explícita a ese contenido, para poder
#     verificar en los tests que Critic realmente recibió el resultado de
#     Developer como entrada, no solo que el mecanismo de fichero repite
#     un texto fijo cualquiera.
#   SIM_ROLE=scribe_check (T-AF008-US03-02): si detecta la cabecera
#     "--- Contexto pre-procesado por Scribe ---" en la instrucción
#     recibida (embebida por dispatch_job cuando el disparo de Scribe
#     aplica), incluye en su reporte el contenido íntegro de esa sección,
#     para poder verificar end-to-end (tmux real, sin parsear el pane)
#     que el agente realmente recibió el contexto pre-procesado de
#     Scribe, no solo que dispatch_job lo generó internamente.
#   SIM_ROLE=architect_approved_verdict (T-AF022-US15-04): simula un
#     Arquitecto real que emite un veredicto ESTADO: APROBADO en el
#     formato estructurado que `architect_verdict.parse_verdict` espera
#     — para tests end-to-end del disparo automático del Tester de UI
#     que necesitan un veredicto aprobado real, sin mockear
#     `_do_dispatch_verdict` ni `parse_verdict`.
#   SIM_ROLE=tester_passed_verdict (T-AF008-US14-02): simula un Tester
#     real que emite RESULTADO: EXITO en el formato estructurado que
#     `task_verdict.parse_task_verdict` espera.
#   SIM_ROLE=tester_failed_verdict (T-AF008-US14-02): simula un Tester
#     real que emite RESULTADO: FALLO, con RESUMEN/SIGUIENTE_PASO fijos
#     — para verificar end-to-end que un fallo genera la Task de
#     corrección nueva en EN_DESARROLLO.
buffer=""
while IFS= read -r line; do
    buffer="$buffer$line"$'\n'
    if [[ "$line" == *"escribe tu resultado completo en el fichero"* ]]; then
        report_file=$(echo "$line" | sed -n "s/.*fichero '\([^']*\)'.*/\1/p")
        sleep "${SIM_DELAY:-0.3}"
        if [ "${SIM_FAIL:-0}" = "1" ]; then
            echo "the agent could not complete the instruction" > "$report_file"
        elif [ "${SIM_ROLE:-}" = "critic" ]; then
            if echo "$buffer" | grep -q "Resultado del Job anterior"; then
                previous_result=$(echo "$buffer" | sed -n '/Resultado del Job anterior/,/^Cuando termines/p' | sed '1d;$d')
                echo "CRITIC VERDICT: reviewed the following prior result:" > "$report_file"
                echo "$previous_result" >> "$report_file"
                echo "verdict: approved with no observations" >> "$report_file"
            else
                echo "CRITIC VERDICT: no prior result was provided to review" > "$report_file"
            fi
        elif [ "${SIM_ROLE:-}" = "architect_approved_verdict" ]; then
            {
                echo "ESTADO: APROBADO"
                echo "JUSTIFICACIÓN:"
                echo "Los criterios de aceptación se cumplen."
                echo "SIGUIENTE_PROMPT_PARA_WORKER:"
                echo "(sin correcciones pendientes)"
            } > "$report_file"
        elif [ "${SIM_ROLE:-}" = "tester_passed_verdict" ]; then
            {
                echo "RESULTADO: EXITO"
                echo "RESUMEN:"
                echo "Todos los criterios de aceptación se cumplen."
                echo "SIGUIENTE_PASO:"
                echo "(sin correcciones pendientes)"
            } > "$report_file"
        elif [ "${SIM_ROLE:-}" = "tester_failed_verdict" ]; then
            {
                echo "RESULTADO: FALLO"
                echo "RESUMEN:"
                echo "El criterio de aceptación 2 no se cumple: el endpoint devuelve 500."
                echo "SIGUIENTE_PASO:"
                echo "Corregir el manejo de la excepción en el endpoint afectado."
            } > "$report_file"
        elif [ "${SIM_ROLE:-}" = "scribe_check" ]; then
            if echo "$buffer" | grep -q -- "--- Contexto pre-procesado por Scribe ---"; then
                scribe_section=$(echo "$buffer" | sed -n '/--- Contexto pre-procesado por Scribe ---/,/--- Fin del contexto pre-procesado por Scribe ---/p')
                echo "SCRIBE CONTEXT RECEIVED:" > "$report_file"
                echo "$scribe_section" >> "$report_file"
            else
                echo "NO SCRIBE CONTEXT WAS PROVIDED" > "$report_file"
            fi
        else
            echo "line one of the cooperative result" > "$report_file"
            echo "line two of the cooperative result" >> "$report_file"
        fi
        echo "___ATLAS_FORGE_JOB_DONE___" >> "$report_file"
        buffer=""
    fi
done
# Se queda vivo esperando el siguiente turno, como un runtime interactivo real.
cat

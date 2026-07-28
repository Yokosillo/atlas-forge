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
#   SIM_ROLE=critic: simula el rol Critic (T-FB008-US02-01) — si detecta
#     el bloque "Resultado del Job anterior" en la instrucción recibida
#     (embebido por create_job al encadenar Jobs), incluye en su propio
#     reporte una referencia explícita a ese contenido, para poder
#     verificar en los tests que Critic realmente recibió el resultado de
#     Developer como entrada, no solo que el mecanismo de fichero repite
#     un texto fijo cualquiera.
#   SIM_ROLE=scribe_check (T-FB008-US03-02): si detecta la cabecera
#     "--- Contexto pre-procesado por Scribe ---" en la instrucción
#     recibida (embebida por dispatch_job cuando el disparo de Scribe
#     aplica), incluye en su reporte el contenido íntegro de esa sección,
#     para poder verificar end-to-end (tmux real, sin parsear el pane)
#     que el agente realmente recibió el contexto pre-procesado de
#     Scribe, no solo que dispatch_job lo generó internamente.
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
        echo "___FACTORY_BRAIN_JOB_DONE___" >> "$report_file"
        buffer=""
    fi
done
# Se queda vivo esperando el siguiente turno, como un runtime interactivo real.
cat

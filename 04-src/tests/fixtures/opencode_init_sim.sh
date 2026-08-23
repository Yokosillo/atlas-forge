#!/bin/bash
# Simula un runtime OpenCode que NO acepta input durante la inicialización
# ("Build auto") y solo muestra la barra de estado "Build · <model>" una
# vez que está listo (T-AF022-US06-07). Tras la barra, se comporta como el
# agente cooperativo estándar: lee la instrucción desde stdin y escribe el
# reporte con el marcador de fin.
#
# Variables de entorno:
#   SIM_INIT_SECONDS: segundos extra de inicialización tras las líneas de
#     "Build auto" (default 0.3).
#   SIM_DELAY: segundos de trabajo antes de reportar (default 0.3).
for i in 1 2 3; do
    echo "Build auto — inicializando componente $i ..."
    sleep 0.3
done
sleep "${SIM_INIT_SECONDS:-0.3}"
echo "Build · DeepSeek V4 Flash DeepSeek"
buffer=""
while IFS= read -r line; do
    buffer="$buffer$line"$'\n'
    if [[ "$line" == *"escribe tu resultado completo en el fichero"* ]]; then
        report_file=$(echo "$line" | sed -n "s/.*fichero '\([^']*\)'.*/\1/p")
        sleep "${SIM_DELAY:-0.3}"
        echo "line one of the cooperative result" > "$report_file"
        echo "line two of the cooperative result" >> "$report_file"
        echo "___ATLAS_FORGE_JOB_DONE___" >> "$report_file"
        buffer=""
    fi
done
# Se queda vivo esperando el siguiente turno, como un runtime interactivo real.
cat
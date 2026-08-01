#!/usr/bin/env bash
# watch_worker.sh — worker -> crítico
# Vigila worker_output.txt; al detectar ### STORY_DONE ### avisa a la
# sesión tmux del crítico. Cada paso queda registrado en logs/watch.log
# para poder diagnosticar sin depender de que el envío a tmux haya
# funcionado o no.
set -u

STATE_DIR="/home/secure_ai_atlas/factoria-software/10-PRODUCTOS/PROD-006-factory-brain/.claude/state"
WORKER_OUTPUT="$STATE_DIR/worker_output.txt"
CRITIC_SESSION="006-critico"
LOG_DIR="$STATE_DIR/logs"
LOG_FILE="$LOG_DIR/watch.log"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [watch_worker] $*" >> "$LOG_FILE"
}

log "arrancado (pid $$), vigilando $WORKER_OUTPUT, sesión destino: $CRITIC_SESSION"

if ! command -v inotifywait >/dev/null 2>&1; then
    log "ERROR fatal: inotifywait no está en PATH, abortando"
    exit 1
fi

if [ ! -f "$WORKER_OUTPUT" ]; then
    log "AVISO: $WORKER_OUTPUT no existe todavía al arrancar — inotifywait fallará hasta que se cree"
fi

# -m/--monitor: inotifywait no termina tras el primer evento, sigue emitiendo
# uno por línea indefinidamente — evita la ventana de carrera de "termina,
# bash reinicia el while, se pierde un evento mientras tanto" que sí existe
# si se relanza inotifywait una vez por evento.
# Se vigila el directorio contenedor filtrando por nombre de fichero, no la
# ruta del fichero directamente: algunas herramientas de escritura (editores,
# escrituras atómicas) reemplazan el inode en vez de truncar el existente
# (create+rename), lo que hace perder un watch puesto sobre la ruta fija del
# fichero — visto en producción, el watcher se caía justo tras el primer
# evento sin detectar el segundo.
inotifywait -m -e close_write -e moved_to -e create --format '%f' "$STATE_DIR" 2>>"$LOG_FILE" | while read -r changed_file; do
    if [ "$changed_file" != "worker_output.txt" ]; then
        continue
    fi
    log "evento detectado en $WORKER_OUTPUT"

    if grep -q "### STORY_DONE ###" "$WORKER_OUTPUT"; then
        log "marcador STORY_DONE encontrado — enviando aviso a sesión '$CRITIC_SESSION'"
        if tmux has-session -t "$CRITIC_SESSION" 2>/dev/null; then
            # El Enter se envía en un segundo comando, separado por una
            # pequeña pausa: la TUI de Claude Code necesita tiempo para
            # registrar el texto tecleado antes de aceptar el Enter que lo
            # envía — en una sola llamada tmux send-keys "texto" Enter el
            # Enter puede llegar antes de que la UI lo procese y el mensaje
            # se queda escrito en la caja sin enviarse (visto en producción).
            # No se repite "Lee CRITIC.md": el rol ya se cargó una vez al
            # arrancar la sesión. Reenviarlo en cada ciclo desperdicia
            # contexto sin aportar nada nuevo.
            if tmux send-keys -t "$CRITIC_SESSION" \
                "Revisa .claude/state/worker_output.txt y escribe tu decision en .claude/state/critic_output.txt" \
                2>>"$LOG_FILE"; then
                sleep 1
                if tmux send-keys -t "$CRITIC_SESSION" Enter 2>>"$LOG_FILE"; then
                    log "tmux send-keys OK hacia '$CRITIC_SESSION' (texto + Enter separados)"
                else
                    log "ERROR: el Enter de confirmación falló hacia '$CRITIC_SESSION' (código $?) — el texto pudo quedar sin enviar"
                fi
            else
                log "ERROR: tmux send-keys (texto) falló hacia '$CRITIC_SESSION' (código $?)"
            fi
        else
            log "ERROR: la sesión tmux '$CRITIC_SESSION' no existe — no se pudo avisar al crítico"
        fi

    elif grep -q "### WAITING_INPUT ###" "$WORKER_OUTPUT"; then
        log "marcador WAITING_INPUT encontrado"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] WORKER EN ESPERA DE INPUT" >> "$LOG_DIR/alerts.log"

    else
        log "escritura detectada sin marcador STORY_DONE ni WAITING_INPUT reconocido — ignorado"
    fi
done

log "bucle inotifywait terminó inesperadamente (código $?) — el watcher ha dejado de vigilar"

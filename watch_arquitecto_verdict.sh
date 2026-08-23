#!/usr/bin/env bash
# watch_arquitecto_verdict.sh — arquitecto → worker
# Vigila arquitecto_output.txt; al detectar una escritura, extrae el bloque
# SIGUIENTE_PROMPT_PARA_WORKER y lo envía a la sesión tmux del worker.
# Cada paso queda registrado en logs/watch.log.
set -u

STATE_DIR="/home/secure_ai_atlas/factoria-software/10-PRODUCTOS/PROD-006-atlas-forge/.claude/state"
ARQUITECTO_OUTPUT="$STATE_DIR/arquitecto_output.txt"
WORKER_SESSION="006-developer"
LOG_DIR="$STATE_DIR/logs"
LOG_FILE="$LOG_DIR/watch.log"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [watch_arquitecto_verdict] $*" >> "$LOG_FILE"
}

log "arrancado (pid $$), vigilando $ARQUITECTO_OUTPUT, sesión destino: $WORKER_SESSION"

if ! command -v inotifywait >/dev/null 2>&1; then
    log "ERROR fatal: inotifywait no está en PATH, abortando"
    exit 1
fi

if [ ! -f "$ARQUITECTO_OUTPUT" ]; then
    log "AVISO: $ARQUITECTO_OUTPUT no existe todavía al arrancar — inotifywait fallará hasta que se cree"
fi

# Mismo patrón que watch_worker.sh: -m/--monitor (sin relanzar inotifywait
# por evento, evita perder eventos en la ventana de reinicio) vigilando el
# directorio contenedor filtrado por nombre (una escritura atómica que
# reemplaza el inode del fichero rompería un watch puesto sobre la ruta fija).
inotifywait -m -e close_write -e moved_to -e create --format '%f' "$STATE_DIR" 2>>"$LOG_FILE" | while read -r changed_file; do
    if [ "$changed_file" != "arquitecto_output.txt" ]; then
        continue
    fi
    log "evento detectado en $ARQUITECTO_OUTPUT"

    NEXT_PROMPT=$(awk '/SIGUIENTE_PROMPT_PARA_WORKER:/{flag=1; next} flag' "$ARQUITECTO_OUTPUT")

    if [ -n "$NEXT_PROMPT" ]; then
        log "SIGUIENTE_PROMPT_PARA_WORKER encontrado (${#NEXT_PROMPT} caracteres) — enviando a sesión '$WORKER_SESSION'"
        if tmux has-session -t "$WORKER_SESSION" 2>/dev/null; then
            # Texto y Enter en llamadas separadas, con pausa entre medias:
            # la TUI de Claude Code puede no registrar el Enter si llega en
            # el mismo tmux send-keys que el texto (visto en producción, el
            # mensaje queda escrito en la caja sin enviarse).
            if tmux send-keys -t "$WORKER_SESSION" "$NEXT_PROMPT" 2>>"$LOG_FILE"; then
                sleep 1
                if tmux send-keys -t "$WORKER_SESSION" Enter 2>>"$LOG_FILE"; then
                    log "tmux send-keys OK hacia '$WORKER_SESSION' (texto + Enter separados)"
                else
                    log "ERROR: el Enter de confirmación falló hacia '$WORKER_SESSION' (código $?) — el texto pudo quedar sin enviar"
                fi
            else
                log "ERROR: tmux send-keys (texto) falló hacia '$WORKER_SESSION' (código $?)"
            fi
        else
            log "ERROR: la sesión tmux '$WORKER_SESSION' no existe — no se pudo avisar al worker"
        fi
    else
        log "escritura detectada pero sin bloque SIGUIENTE_PROMPT_PARA_WORKER — ignorado"
    fi
done

log "bucle inotifywait terminó inesperadamente (código $?) — el watcher ha dejado de vigilar"

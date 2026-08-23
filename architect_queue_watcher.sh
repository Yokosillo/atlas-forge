#!/usr/bin/env bash
# architect_queue_watcher.sh — cola de cierres -> Arquitecto (T-AF030-US03-01)
#
# Sustituye, para el caso "avisar al Arquitecto de un cierre", a
# watch_worker.sh: genérico por proyecto (uno de estos watchers por
# proyecto con Arquitecto lanzado, no un único destino hardcodeado),
# calcula el nombre de sesión del Arquitecto por convención determinista
# (T-AF030-US01-01: `arquitecto-<project_name>`) sin fichero de
# suscripción — sin proyecto, sin este watcher no sabría a qué sesión
# avisar; con el nombre de proyecto, no necesita que nadie se lo informe
# en tiempo de ejecución.
#
# Uso: ./architect_queue_watcher.sh <project_root> <project_name>
#   project_root: raíz del repositorio del proyecto a vigilar (mismo
#                 significado que Project.path en atlas_forge.models.project).
#   project_name: nombre del proyecto SIN sanitizar (se sanitiza aquí con
#                 la misma regla que sanitize_session_name_part,
#                 atlas_forge.runtime.generic) — mismo criterio que usó
#                 T-AF030-US02-01 para nombrar el directorio de la cola,
#                 así que la ruta vigilada y el destino del push quedan
#                 sincronizados por construcción.
set -u

PROJECT_ROOT="${1:-}"
PROJECT_NAME_RAW="${2:-}"

if [ -z "$PROJECT_ROOT" ] || [ -z "$PROJECT_NAME_RAW" ]; then
    echo "Uso: $0 <project_root> <project_name>" >&2
    exit 2
fi

# Misma regla que sanitize_session_name_part (atlas_forge/runtime/generic.py):
# cualquier carácter que no sea alfanumérico/-/_ se sustituye por '-',
# se recortan guiones sobrantes al inicio/fin, y se pasa a minúsculas —
# mismo resultado exacto que ya produce T-AF030-US02-01 al nombrar el
# directorio de la cola y T-AF030-US01-01 al nombrar la sesión tmux, así
# que este watcher vigila la MISMA ruta en la que se escribe y calcula la
# MISMA sesión a la que avisar, sin margen de desincronización entre los
# tres puntos.
sanitize_part() {
    printf '%s' "$1" | sed -E 's/[^a-zA-Z0-9_-]+/-/g; s/^-+//; s/-+$//' | tr '[:upper:]' '[:lower:]'
}

PROJECT_NAME="$(sanitize_part "$PROJECT_NAME_RAW")"

STATE_DIR="$PROJECT_ROOT/.claude/state/$PROJECT_NAME"
QUEUE_FILE="$STATE_DIR/architect_queue.jsonl"
ARCHITECT_SESSION="arquitecto-$PROJECT_NAME"
LOG_DIR="$STATE_DIR/logs"
LOG_FILE="$LOG_DIR/architect_queue_watcher.log"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [architect_queue_watcher:$PROJECT_NAME] $*" >> "$LOG_FILE"
}

log "arrancado (pid $$), vigilando $QUEUE_FILE, sesión destino: $ARCHITECT_SESSION"

if ! command -v inotifywait >/dev/null 2>&1; then
    log "ERROR fatal: inotifywait no está en PATH, abortando"
    exit 1
fi

if [ ! -f "$QUEUE_FILE" ]; then
    log "AVISO: $QUEUE_FILE no existe todavía al arrancar — inotifywait fallará hasta que se cree"
fi

# -m/--monitor sobre el DIRECTORIO contenedor, no el fichero directo —
# mismo criterio ya validado en watch_worker.sh: una escritura atómica
# (create+rename) reemplaza el inode en vez de truncar el existente, lo
# que perdería el watch si se pusiera sobre la ruta fija del fichero.
# close_write cubre el caso normal (append_to_architect_queue abre en
# modo "a" y cierra tras cada entrada); create/moved_to cubren la
# creación inicial del fichero si no existía al arrancar el watcher.
#
# Se usa `coproc` (en vez del pipe directo `inotifywait -m ... | while
# read`) para que el `inotifywait` quede como proceso hijo del script con
# su PID accesible (`$INOTIFY_PID`): un `trap` sobre TERM/INT/EXIT lo mata
# cuando el script muere. Con el pipe directo, el `inotifywait -m` vive en
# un subshell con argv distinto al del script; si el bash principal muere
# (kill del watcher, reinicio de atlas-forge-api, etc.), ese subshell queda
# huérfano (PPID=1) vigilando el directorio para siempre y agotando las
# instancias inotify del sistema (bug AF-041) — el trap evita esa fuga.
coproc INOTIFY {
    exec inotifywait -m -e close_write -e moved_to -e create --format '%f' "$STATE_DIR" 2>>"$LOG_FILE"
}
INOTIFY_PID="$INOTIFY_PID"
trap 'kill "$INOTIFY_PID" 2>/dev/null' TERM INT EXIT

while read -r changed_file <&"${INOTIFY[0]}"; do
    if [ "$changed_file" != "architect_queue.jsonl" ]; then
        continue
    fi
    log "evento detectado en $QUEUE_FILE"

    if tmux has-session -t "$ARCHITECT_SESSION" 2>/dev/null; then
        # Texto sin backticks ni caracteres especiales de shell (regla
        # dura de 00-gobierno/ARQUITECTO.md, "Texto plano al mandar
        # instrucciones a un agente"): aviso simple, nunca el contenido
        # de la entrada ni el informe de cierre completo.
        # El Enter se envía en un segundo comando, separado por una
        # pequeña pausa — mismo motivo que watch_worker.sh: la TUI
        # necesita tiempo para registrar el texto antes de aceptar el
        # Enter que lo envía, o el mensaje queda escrito sin enviarse.
        if tmux send-keys -t "$ARCHITECT_SESSION" \
            "Tienes una entrada nueva en tu cola de cierres pendientes, revisala" \
            2>>"$LOG_FILE"; then
            sleep 1
            if tmux send-keys -t "$ARCHITECT_SESSION" Enter 2>>"$LOG_FILE"; then
                log "tmux send-keys OK hacia '$ARCHITECT_SESSION' (texto + Enter separados)"
            else
                log "ERROR: el Enter de confirmación falló hacia '$ARCHITECT_SESSION' (código $?) — el texto pudo quedar sin enviar"
            fi
        else
            log "ERROR: tmux send-keys (texto) falló hacia '$ARCHITECT_SESSION' (código $?)"
        fi
    else
        log "ERROR: la sesión tmux '$ARCHITECT_SESSION' no existe — no se pudo avisar al Arquitecto de '$PROJECT_NAME'"
    fi
done

log "bucle inotifywait terminó inesperadamente (código $?) — el watcher ha dejado de vigilar"

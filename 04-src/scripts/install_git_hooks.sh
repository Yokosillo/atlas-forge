#!/usr/bin/env bash
# Instala el pre-commit hook de control tecnico del backlog: dos chequeos
# independientes, ambos deben pasar (que uno pase no exime del otro).
#
# 1. `promote_states.py --check` (T-FB022-US13-02/04): reconciliacion de
#    ESTADO — bloquea si hay drift de promocion (US/Epic con todos sus
#    hijos DONE pero el padre no) o drift inverso (padre DONE con un hijo
#    reabierto).
# 2. `validate_backlog.py` (T-FB022-US13-06): FORMATO — bloquea si algun
#    fichero de 02-backlog/ staged en el commit no cumple el esquema de
#    02-backlog/README.md (validate_backlog_file_v2).
#
# Ambos son Python determinista, sin LLM. Cualquier otro hook pre-commit
# existente se conserva como .bak y se sustituye por este.
#
# Uso:
#   bash scripts/install_git_hooks.sh        # desde 04-src/
#   bash 04-src/scripts/install_git_hooks.sh # desde la raiz del repo
set -uu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

HOOKS_DIR="$REPO_ROOT/.git/hooks"
HOOK_PATH="$HOOKS_DIR/pre-commit"
VENV_PYTHON="$SCRIPT_DIR/../.venv/bin/python"
PROMOTE_SCRIPT="$SCRIPT_DIR/promote_states.py"
VALIDATE_SCRIPT="$SCRIPT_DIR/validate_backlog.py"

if [ ! -d "$REPO_ROOT/.git" ]; then
    echo "ERROR: no hay directorio .git en $REPO_ROOT — no se puede instalar el hook." >&2
    exit 1
fi

if [ ! -x "$VENV_PYTHON" ]; then
    echo "ERROR: no se encuentra el venv en $VENV_PYTHON." >&2
    echo "Revisa que 04-src/.venv exista (bootstrap del proyecto)." >&2
    exit 1
fi

if [ ! -f "$PROMOTE_SCRIPT" ]; then
    echo "ERROR: no se encuentra $PROMOTE_SCRIPT." >&2
    exit 1
fi

if [ ! -f "$VALIDATE_SCRIPT" ]; then
    echo "ERROR: no se encuentra $VALIDATE_SCRIPT." >&2
    exit 1
fi

# Backup de un hook pre-commit manual previo, si lo hay.
if [ -f "$HOOK_PATH" ]; then
    cp "$HOOK_PATH" "$HOOKS_DIR/pre-commit.bak"
    echo "Se ha respaldado el pre-commit existente en .git/hooks/pre-commit.bak"
fi

cat > "$HOOK_PATH" <<EOF
#!/usr/bin/env bash
# Hook pre-commit de Factory Brain: dos chequeos independientes sobre
# 02-backlog/, ambos deben pasar (que uno pase no exime del otro).
# Instalado por 04-src/scripts/install_git_hooks.sh. No editar a mano;
# reinstalar para actualizar.
set -uo pipefail

REPO_ROOT="\$(git rev-parse --show-toplevel)"
PYTHON="\$REPO_ROOT/04-src/.venv/bin/python"

overall_status=0

"\$PYTHON" "\$REPO_ROOT/04-src/scripts/promote_states.py" --check
promote_status=\$?
if [ \$promote_status -ne 0 ]; then
    echo
    echo "Commit BLOQUEADO: drift de estado en el backlog detectado por promote_states.py --check"
    echo "(US/Epic con todos sus hijos DONE pero el padre no, o un padre DONE con un hijo reabierto)."
    echo
    echo "Solucion: promueve los padres automaticamente con:"
    echo
    echo "    python3 04-src/scripts/promote_states.py --apply"
    echo
    echo "(el drift inverso — padre DONE con hijo reabierto — no se corrige automaticamente:"
    echo "revisalo manualmente y decide si reabrir el padre.)"
    echo
    echo "revisa el diff de estados, stagéalo (git add) y reintenta el commit."
    overall_status=1
fi

"\$PYTHON" "\$REPO_ROOT/04-src/scripts/validate_backlog.py"
validate_status=\$?
if [ \$validate_status -ne 0 ]; then
    echo
    echo "Commit BLOQUEADO: uno o mas ficheros de 02-backlog/ staged no cumplen"
    echo "el esquema de 02-backlog/README.md (validate_backlog.py) — ver detalle arriba."
    overall_status=1
fi

exit \$overall_status
EOF

chmod +x "$HOOK_PATH"
echo "Hook pre-commit instalado en: $HOOK_PATH"
echo "Comprobacion de humo: $(grep -c 'promote_states.py --check' "$HOOK_PATH") referencia al chequeo de drift, $(grep -c 'validate_backlog.py' "$HOOK_PATH") referencia(s) al chequeo de formato."

#!/usr/bin/env bash
# Instala el pre-commit hook de reconciliacion de estado del backlog.
#
# El hook ejecuta `promote_states.py --check` (Python determinista, sin LLM)
# antes de cada commit y lo bloquea si existe drift (US/Epic con todos sus
# hijos DONE pero el padre no). Cualquier otro hook pre-commit existente se
# conserva como .bak y se sustituye por este.
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

# Backup de un hook pre-commit manual previo, si lo hay.
if [ -f "$HOOK_PATH" ]; then
    cp "$HOOK_PATH" "$HOOKS_DIR/pre-commit.bak"
    echo "Se ha respaldado el pre-commit existente en .git/hooks/pre-commit.bak"
fi

cat > "$HOOK_PATH" <<EOF
#!/usr/bin/env bash
# Hook pre-commit de Factory Brain: bloquea el commit si el estado del backlog
# tiene drift (US/Epic con todos sus hijos DONE pero el padre no). Instalado por
# 04-src/scripts/install_git_hooks.sh. No editar a mano; reinstalar para actualizar.
set -uo pipefail

REPO_ROOT="\$(git rev-parse --show-toplevel)"

"\$REPO_ROOT/04-src/.venv/bin/python" "\$REPO_ROOT/04-src/scripts/promote_states.py" --check
status=\$?

if [ \$status -ne 0 ]; then
    echo
    echo "Commit BLOQUEADO: drift de estado en el backlog detectado por promote_states.py --check"
    echo "(hay User Stories o Epics con todos sus hijos DONE pero el padre sin actualizar)."
    echo
    echo "Solucion: promueve los padres automaticamente con:"
    echo
    echo "    python3 04-src/scripts/promote_states.py --apply"
    echo
    echo "revisa el diff de estados, stagéalo (git add) y reintenta el commit."
    exit \$status
fi

exit 0
EOF

chmod +x "$HOOK_PATH"
echo "Hook pre-commit instalado en: $HOOK_PATH"
echo "Comprobacion de humo: $(grep -c 'promote_states.py --check' "$HOOK_PATH") referencia al chequeo de drift."

"""Tests de fronteras entre módulos (T-FB019-US01-07): enforcement de las
direcciones de dependencia declaradas en `docs/architecture.md`
(capas Presentación/Aplicación/Dominio/Infraestructura, "cada módulo expondrá
una interfaz clara").

Se recorren los imports REALES de cada fichero `.py` bajo `src/brain/` con
análisis de AST (`ast.parse` + `ast.Import`/`ast.ImportFrom`), a propósito
NO se usa `sys.modules` tras importar cada paquete, porque eso mezclaría
dependencias transitivas (importar un módulo arrastra los imports de su
`__init__.py` y de sus dependencias). Aquí solo cuenta lo que cada fichero
declara literalmente.

Si se introduce una violación nueva (un import no listado aquí como excepción
explícita), este test falla con un mensaje que indica QUÉ módulo importó QUÉ y
QUÉ regla violó.

Detectado en `07-informes/propuesta-aislamiento-modulos-2026-08-02.md` (P4).
"""

import ast
from pathlib import Path

_BRAIN_ROOT = Path(__file__).resolve().parents[1] / "src" / "brain"


# ---------------------------------------------------------------------------
# Excepciones documentadas y aceptadas (NUNCA una lista abierta).
# Estructura: { fichero_relativo -> { modulo_importado: {simbolos_permitidos} } }
# De modo que cualquier import prohibido añadido en el futuro falla salvo que
# se registre aquí explícitamente (módulo + símbolos permite confirmar que es
# una dependencia deliberada y acotada, no un catch-all).
#
# CLI: la TUI y su entrypoint `brain` fueron archivados (tag
# `archive/tui-android-2026-08-18`); lo que queda del paquete `brain.cli` son
# los subcomandos de solo lectura que antes usaba ese entrypoint:
# - `backlog_status` (T-FB018-US02-02, US-FB018-02): reusa el informe del
#   parser de dominio (`brain.backlog.report`) para ahorrar tokens de agente
#   cognitivo, sin orquestar ningún servicio ni mutar estado.
# - `scribe_resumir_backlog` (T-FB018-US02-03, US-FB018-02): capa OPTIONAL de
#   síntesis en prosa que solo invoca la operación del catálogo cerrado de
#   Scribe (`brain.local_tools`) con el JSON ya calculado — degrada
#   explícitamente si Scribe/Ollama no está disponible.
_CLI_ALLOWED = {
    "cli/backlog_status.py": {
        "brain.backlog": {
            "build_backlog_report",
            "format_human_report",
            "render_json_report",
        }
    },
    "cli/scribe_resumir_backlog.py": {
        "brain.local_tools": {
            "ScribeUnavailableError",
            "resumir_estado_backlog",
        }
    },
}

# Direcciones de dependencia NO permitidas por paquete (top-level de `brain`).
_API_FORBIDDEN = {"tui"}
_MODELS_FORBIDDEN = {"storage", "tmux", "runtime"}


def _module_top(module: str) -> str | None:
    """Primer nivel de un módulo `brain.x.y` -> `x`; None si no es del paquete `brain`."""
    if not module.startswith("brain."):
        return None
    return module.split(".")[1]


def _rule_is_forbidden(top_level: str, imported_top: str) -> bool:
    if top_level == "api":
        return imported_top in _API_FORBIDDEN
    if top_level == "models":
        return imported_top in _MODELS_FORBIDDEN
    if top_level == "cli":
        # cli son subcomandos de solo lectura: no pueden orquestar dominio.
        return imported_top != "tui"
    return False


def _rule_name(top_level: str) -> str:
    if top_level == "api":
        return "api no debe importar brain.tui"
    if top_level == "models":
        return "models no debe importar brain.storage/brain.tmux/brain.runtime"
    if top_level == "cli":
        return "cli no debe orquestar el dominio directamente"
    return ""


def _allowed_symbols_for(file_rel: str, module: str) -> set[str] | None:
    """Símbolos permitidos de `module` para `file_rel`; None si el módulo no
    tiene excepción registrada para ese fichero."""
    file_allowed = _CLI_ALLOWED.get(file_rel)
    if file_allowed is None:
        return None
    return file_allowed.get(module)


def _iter_imports(tree: ast.Module):
    """Rinde (module, symbol) para cada import del paquete `brain` en `tree`."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("brain."):
            for alias in node.names:
                yield node.module, alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("brain."):
                    yield alias.name, None


def _py_files() -> list[Path]:
    """Ficheros .py de origen bajo src/brain/, excluyendo __pycache__."""
    return [
        p
        for p in sorted(_BRAIN_ROOT.rglob("*.py"))
        if "__pycache__" not in p.parts
    ]


def _collect_violations() -> list[str]:
    violations: list[str] = []

    for file_path in _py_files():
        file_rel = str(file_path.relative_to(_BRAIN_ROOT))
        if "/" not in file_rel:
            # fichero raíz (brain/__init__.py): no pertenece a ningún subpaquete regulado.
            continue
        top_level = file_rel.split("/")[0]

        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))

        for module, symbol in _iter_imports(tree):
            imported_top = _module_top(module)
            if imported_top is None:
                continue
            if not _rule_is_forbidden(top_level, imported_top):
                continue

            allowed_symbols = _allowed_symbols_for(file_rel, module)
            if allowed_symbols is None:
                violations.append(
                    f"[{top_level}] {file_path} importa `{module}` — regla violada: "
                    f"{_rule_name(top_level)} — y NO tiene excepción registrada."
                )
            elif symbol is not None and symbol not in allowed_symbols:
                violations.append(
                    f"[{top_level}] {file_path} importa `{symbol}` de `{module}`, "
                    f"que no está entre las excepciones {sorted(allowed_symbols)}."
                )

    return violations


# ---------------------------------------------------------------------------


def test_module_boundaries_import_directions():
    violations = _collect_violations()
    assert violations == [], (
        "Direcciones de dependencia entre módulos violadas:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
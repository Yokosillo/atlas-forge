#!/usr/bin/env python3
"""Cierre de version de Atlas Forge (T-AF024-US23-01).

Cierra la version abierta actual: comprueba que toda User Story asignada a esa
version (`version: <v>` en su frontmatter) este en `state: DONE`, y si es asi
avanza el esquema de `.atlas-forge/version.yml`:

  current_closed -> la version cerrada
  open           -> la primera de `future`
  future         -> la siguiente (open_old + 2, open_old + 3)

Solo CIERRA (never revierte) y es idempotente: si ya se cerro, no hace nada.

Uso:
  python3 scripts/close_version.py --check    # reporta sin tocar nada; exit != 0 si hay US sin DONE
  python3 scripts/close_version.py --verify   # gate de auditoría: ejecuta auditar-backlog + verificar-auditoria
                                              # (pasos 1 y 2 de US-AF018-03) y bloquea el cierre si el Auditor
                                              # confirma discrepancias críticas; exit != 0 si BLOQUEADO
  python3 scripts/close_version.py --apply    # valida y escribe el nuevo esquema de versiones

--verify (T-AF018-US03-03):
  El cierre pasa de "declarado" a "verificado": ejecuta la acción
  `auditar-backlog` (paso 1, despacha un Job al Arquitecto) y, si el
  informe del paso 1 declara hallazgos, `verificar-auditoria` (paso 2,
  Job al Auditor que contrasta cada hallazgo contra el código real y
  emite por cada uno `corregir_estado`/`crear_task_correccion`/`descartar`).
  El gate decide:
    PASA        -> sin discrepancias críticas confirmadas por el Auditor;
                   el cierre puede proceder con --apply (exit 0).
    BLOQUEADO   -> el Auditor confirmó un item DONE incompleto o un
                   TO_DO/READY ya implementado pendiente de decisión;
                   el cierre NO puede proceder (exit 1, se referencia el
                   informe del paso 2 en 07-informes/).

  --verify NO modifica --check/--apply: solo añade el gate. No introduce
  cadencia periódica/automática: es una ejecución bajo demanda en el
  momento del cierre de versión.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(os.path.dirname(__file__)).resolve().parents[1]
BACKLOG = REPO_ROOT / "02-backlog" / "user-stories"
VERSION_FILE = REPO_ROOT / ".atlas-forge" / "version.yml"

# Directorio de informes de la US-AF018-03 (US-AF018-03-01/-02 persisten
# aquí con nombre con fecha; --verify los lee para decidir el gate).
REPORTS_DIR = REPO_ROOT / "07-informes" / "US-AF018-03"

# Socket tmux usado para despachar los Jobs de auditoría — mismo valor que
# `routes.py::_SOCKET_NAME` (DEFAULT_SOCKET_NAME de `tmux/manager.py`).
_SOCKET_NAME = "atlas-forge"

# Acciones de auditoría de US-AF018-03 (pasos 1 y 2).
_STEP1_ACTION_ID = "auditar-backlog"
_STEP2_ACTION_ID = "verificar-auditoria"

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _load_version_scheme() -> dict:
    if not VERSION_FILE.exists():
        print(f"ERROR: no existe el esquema de versiones en {VERSION_FILE}", file=sys.stderr)
        sys.exit(1)
    with open(VERSION_FILE, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not data.get("open") or not data.get("future"):
        print(f"ERROR: esquema de versiones incompleto en {VERSION_FILE}", file=sys.stderr)
        sys.exit(1)
    return data


def _us_entries() -> list[tuple[str, str, str]]:
    """(id, state, version) de cada User Story del backlog."""
    entries = []
    for path in sorted(BACKLOG.glob("US-*.md")):
        text = path.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        if not m:
            continue
        fm = yaml.safe_load(m.group(1)) or {}
        entries.append(
            (str(fm.get("id", path.stem)), str(fm.get("state", "")), str(fm.get("version", "")))
        )
    return entries


def _check_version(version: str) -> list[str]:
    """Devuelve la lista de US asignadas a `version` que no estan DONE."""
    not_done = []
    for us_id, state, us_version in _us_entries():
        if us_version == version and state != "DONE":
            not_done.append(f"{us_id} (state={state})")
    return not_done


def _next_versions(version: str, count: int) -> list[str]:
    """Siguientes `count` versiones tras `version` (p. ej. "0.9.1" -> ["0.9.2", "0.9.3"])."""
    parts = str(version).split(".")
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 else 0
    patch = int(parts[2]) if len(parts) > 2 else 0
    return [f"{major}.{minor}.{patch + i + 1}" for i in range(count)]


# ---------------------------------------------------------------------------
# Gate de auditoría (T-AF018-US03-03). Funciones PURAS: parsean los informes
# ya persistidos del paso 1 (`auditar-backlog`) y del paso 2
# (`verificar-auditoria`) y devuelven la decisión de cierre sin tocar tmux ni
# agentes — el test determinista las ejercita con informes simulados.
# ---------------------------------------------------------------------------

# Estados canónicos del backlog (mismo vocabulario que AF-040).
_KNOWN_STATES = frozenset(
    {
        "NO_TASKS",
        "TO_PLAN",
        "READY",
        "TO_DEVELOP",
        "IN_PROGRESS",
        "IN_REVIEW",
        "DONE",
        "OUT_OF_SCOPE",
    }
)

# Campos estructurados reconocidos dentro de un hallazgo (`- campo: valor`).
_FINDING_FIELDS = frozenset(
    {
        "id",
        "estado_declarado",
        "estado_correcto",
        "accion",
        "veredicto",
        "evidencia",
    }
)

_FINDING_ID_RE = re.compile(r"^-+\s*id\s*:\s*(.+?)\s*$", re.IGNORECASE)
_FINDING_FIELD_RE = re.compile(
    r"^-+\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*?)\s*$"
)


def _normalize_state(value: str | None) -> str | None:
    """Normaliza un estado declarado del backlog a mayúsculas del vocabulario
    canónico; devuelve `None` si no es un estado reconocido."""
    if not value:
        return None
    candidate = str(value).strip().strip('"').strip("'").strip("`")
    upper = candidate.upper()
    return upper if upper in _KNOWN_STATES else None


def _parse_findings(text: str) -> list[dict]:
    """Parsea los hallazgos estructurados de un informe (`- id:` / `- campo:
    valor`), de forma tolerante a las secciones de Markdown del informe:
    cada hallazgo empieza en una línea `- id: <item>` y acumula los campos
    reconocidos hasta la siguiente entrada.

    Devuelve una lista de dicts con `id` y, si están presentes,
    `estado_declarado`, `estado_correcto`, `accion`, `veredicto` — más la
    clave interna `_lines` (las líneas crudas del bloque) para extraer el
    estado correcto en prosa cuando no se emite como campo estructurado."""
    entries: list[dict] = []
    current: dict | None = None

    def _flush() -> None:
        if current is not None:
            entries.append(current)

    for line in (text or "").splitlines():
        id_match = _FINDING_ID_RE.match(line.strip())
        if id_match:
            _flush()
            current = {"_lines": [line]}
            current["id"] = id_match.group(1).strip()
            continue
        field_match = _FINDING_FIELD_RE.match(line.strip())
        if field_match and current is not None:
            key, value = field_match.group(1).lower(), field_match.group(2).strip()
            if key in _FINDING_FIELDS:
                current[key] = value
            current["_lines"].append(line)
    _flush()
    return entries


def _step1_findings(text: str) -> list[dict]:
    """Hallazgos del informe del paso 1 (accion `auditar-backlog`)."""
    return _parse_findings(text)


def _step2_findings(text: str) -> list[dict]:
    """Hallazgos verificados del informe del paso 2 (`verificar-auditoria`)."""
    return _parse_findings(text)


def _declared_state(
    finding: dict, step1_by_id: dict[str, dict]
) -> str | None:
    """Estado declarado de un hallazgo: el del propio bloque del paso 2 si
    está estructurado, si no el del paso 1 cruzado por id (fuente de verdad
    del `## Estado` declarado)."""
    own = _normalize_state(finding.get("estado_declarado"))
    if own is not None:
        return own
    base = step1_by_id.get(finding.get("id"))
    if base:
        return _normalize_state(base.get("estado_declarado"))
    return None


def _correct_state(finding: dict) -> str | None:
    """Estado correcto de un hallazgo `corregir_estado`: campo estructurado
    `estado_correcto` si existe, si no intento tolerante en el texto del
    bloque (`corregir_estado ... a/-> DONE`, `Estado correcto: DONE`)."""
    field = _normalize_state(finding.get("estado_correcto"))
    if field is not None:
        return field
    for line in finding.get("_lines", []) or []:
        m = re.search(
            r"estado[_ ]?correcto\s*[:=]?\s*([A-Z_]+)",
            line,
            re.IGNORECASE,
        )
        if m:
            state = _normalize_state(m.group(1))
            if state is not None:
                return state
    for line in finding.get("_lines", []) or []:
        m = re.search(
            r"corregir_estado[^A-Z_]{0,50}\b(DONE|READY|IN_PROGRESS|TO_DO|TO_DEVELOP|IN_REVIEW|TO_PLAN|NO_TASKS)\b",
            line,
            re.IGNORECASE,
        )
        if m:
            state = _normalize_state(m.group(1))
            if state is not None:
                return state
    return None


def _is_critical_finding(
    declared: str | None, accion: str | None, correct: str | None
) -> bool:
    """Decide si un hallazgo del Auditor compromete el cierre de versión.

    - `descartar` (falso positivo del paso 1): nunca bloquea.
    - `crear_task_correccion`: existe un hueco real de implementación, luego
      el item no está realmente completo -> bloquea.
    - `corregir_estado`: bloquea si el item se declaró `DONE` y el Auditor
      confirma que no (DONE incompleto), o si estando pendiente (TO_DO/READY/
      IN_PROGRESS) el estado real verificado es `DONE` (ya implementado
      pendiente de decisión). Una corrección que no toca el borde del
      release (p. ej. READY -> IN_PROGRESS) NO bloquea."""
    accion = (accion or "").strip().lower()
    if accion == "descartar":
        return False
    if accion == "crear_task_correccion":
        return True
    if accion == "corregir_estado":
        if declared == "DONE":
            # El release declara el item completo; una corrección de estado
            # confirmada (o una discrepancia sin estado correcto legible)
            # implica que ese DONE no es real -> compromete el cierre.
            return True
        if correct == "DONE":
            # Item pendiente (TO_DO/READY/IN_PROGRESS) ya implementado y
            # verificado -> cierre prematuro.
            return True
        return False
    # Acción no estructurada/reconocida: no clasifica como crítica (se
    # reporta como sin clasificar), nunca rompe el gate.
    return False


def evaluate_verify_gate(
    step2_text: str, step1_text: str = ""
) -> tuple[str, list[str], list[str]]:
    """Decisión del gate a partir de los informes de ambos pasos (PURAS, sin
    tmux). Devuelve `(decision, bloqueantes, sin_clasificar)` donde
    `decision` es `"PASA"` o `"BLOQUEADO"`, `bloqueantes` son los ids de los
    items que bloquean y `sin_clasificar` los ids de hallazgos confirmados
    cuya gravedad no pudo clasificarse (no bloquean, se muestran al
    operador)."""
    step1_by_id: dict[str, dict] = {}
    for finding in _step1_findings(step1_text):
        if finding.get("id"):
            step1_by_id[finding["id"]] = finding

    bloqueantes: list[str] = []
    sin_clasificar: list[str] = []
    for finding in _step2_findings(step2_text):
        item_id = finding.get("id")
        accion = (finding.get("accion") or "").strip().lower()
        if accion == "descartar":
            continue
        if accion not in ("corregir_estado", "crear_task_correccion"):
            # Hallazgo presente pero sin acion estructurada legible: no
            # bloquea (el gate no inventa un criterio que el informe no
            # declara), se reporta para el operador.
            if item_id and item_id not in sin_clasificar:
                sin_clasificar.append(item_id)
            continue
        declared = _declared_state(finding, step1_by_id)
        correct = _correct_state(finding)
        if _is_critical_finding(declared, accion, correct):
            if item_id and item_id not in bloqueantes:
                bloqueantes.append(item_id)
        elif accion == "corregir_estado" and declared is None:
            if item_id and item_id not in sin_clasificar:
                sin_clasificar.append(item_id)

    if bloqueantes:
        return "BLOQUEADO", bloqueantes, sin_clasificar
    return "PASA", [], sin_clasificar


def _latest_report(action_id: str) -> Path | None:
    """Informe más reciente de `action_id` en `07-informes/US-AF018-03/`
    (los persisten con nombre con fecha, T-AF018-US03-01/-02)."""
    if not REPORTS_DIR.is_dir():
        return None
    matches = list(REPORTS_DIR.glob(f"{action_id}-*.md"))
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def _verify_decision_from_reports(
    step1_path: Path | None, step2_path: Path | None
) -> tuple[str, list[str], list[str]]:
    """Carga los informes ya persistidos de los pasos 1 y 2 y aplica el gate
    (PURAS; punto de entrada del ---verify y de los tests con informes
    simulados)."""
    step1_text = step1_path.read_text(encoding="utf-8") if step1_path else ""
    step2_text = step2_path.read_text(encoding="utf-8") if step2_path else ""
    return evaluate_verify_gate(step2_text, step1_text)


def _socket_name() -> str:
    """Nombre del socket tmux de ejecución — mismo que `routes.py` uses para
    despachar las acciones transversales."""
    try:
        from atlas_forge.tmux.manager import DEFAULT_SOCKET_NAME
        return DEFAULT_SOCKET_NAME
    except Exception:  # defensivo: fuente única sin regresión en el resto
        return _SOCKET_NAME


def _run_auditoria_paso1() -> Path:
    """Ejecuta el paso 1 (`auditar-backlog`): despacha un Job al Arquitecto
    que audita el backlog activo contra el código real y persiste el informe
    en 07-informes/ con nombre con fecha. Devuelve la ruta del informe."""
    from atlas_forge.actions.transversal import dispatch_action

    dispatch_action(_STEP1_ACTION_ID, socket_name=_socket_name())
    report = _latest_report(_STEP1_ACTION_ID)
    if report is None:
        raise RuntimeError(
            "No se encontró el informe del paso 1 tras ejecutar "
            f"'{_STEP1_ACTION_ID}' en {REPORTS_DIR}."
        )
    return report


def _run_verificacion_paso2(step1_path: Path) -> Path:
    """Ejecuta el paso 2 (`verificar-auditoria`): despacha un Job al Auditor
    con el fichero del paso 1 como entrada para que verifique cada hallazgo
    contra el código real. Devuelve la ruta del informe del paso 2."""
    from atlas_forge.actions.transversal import dispatch_action

    dispatch_action(
        _STEP2_ACTION_ID,
        socket_name=_socket_name(),
        input_path=str(step1_path),
    )
    report = _latest_report(_STEP2_ACTION_ID)
    if report is None:
        raise RuntimeError(
            "No se encontró el informe del paso 2 tras ejecutar "
            f"'{_STEP2_ACTION_ID}' en {REPORTS_DIR}."
        )
    return report


def _run_verify(closing: str) -> int:
    """Gate de auditoría del cierre (T-AF018-US03-03). Ejecuta los pasos 1 y
    2 de la auditoría; devuelve 0 (PASA) o 1 (BLOQUEADO)."""
    print(f"\n--- Gate de auditoría (--verify) de la versión {closing} ---")

    try:
        step1_path = _run_auditoria_paso1()
    except Exception as error:
        print(
            f"\nBLOQUEADO: no se pudo ejecutar el paso 1 de la auditoría: {error}",
            file=sys.stderr,
        )
        print(
            "El cierre no puede proceder: el gate exige verificar la "
            "auditoría antes de cerrar (llanza Arquitecto/Auditor si es "
            "necesario).",
            file=sys.stderr,
        )
        return 1

    print(f"Paso 1 ({_STEP1_ACTION_ID}): informe en {step1_path}")

    step1_findings = _step1_findings(step1_path.read_text(encoding="utf-8"))
    print(f"Hallazgos declarados en el paso 1: {len(step1_findings)}")

    step2_path: Path | None
    if step1_findings:
        try:
            step2_path = _run_verificacion_paso2(step1_path)
        except Exception as error:
            print(
                f"\nBLOQUEADO: no se pudo ejecutar el paso 2 de la "
                f"verificación: {error}",
                file=sys.stderr,
            )
            return 1
        print(f"Paso 2 ({_STEP2_ACTION_ID}): informe en {step2_path}")
    else:
        # Sin hallazgos no hay nada que verificar (y no se paga un Auditor
        # caro sobre un informe vacío de discrepancias).
        step2_path = None
        print("Paso 2: omitido (el paso 1 no declara hallazgos).")

    decision, bloqueantes, sin_clasificar = _verify_decision_from_reports(
        step1_path, step2_path
    )

    if step2_path and step1_findings:
        step2_findings = _step2_findings(step2_path.read_text(encoding="utf-8"))
        if not step2_findings:
            print(
                "AVISO: el informe del paso 2 no contiene hallazgos "
                "clasificables; la decisión del gate refleja lo que pudo "
                "verificarse — revisa el informe del Auditor antes de --apply."
            )

    for item_id in sin_clasificar:
        print(
            f"AVISO: hallazgo del item {item_id} no clasificable (no bloquea "
            "pero conviene revisarlo)."
        )

    if decision == "PASA":
        print("\nDecisión: PASA")
        if step2_path:
            print(
                "No hay discrepancias críticas confirmadas por el Auditor "
                "(items DONE incompletos / implementados pendientes de "
                "decisión). El cierre puede proceder con --apply."
            )
            print(f"Informe del Auditor (paso 2): {step2_path}")
        else:
            print("El paso 1 no encontró hallazgos: el cierre puede proceder.")
        return 0

    print("\nDecisión: BLOQUEADO", file=sys.stderr)
    print(
        "El Auditor confirmó discrepancias que comprometen el release:",
        file=sys.stderr,
    )
    for item_id in bloqueantes:
        print(f"  - {item_id}", file=sys.stderr)
    print(
        "Corrige o descarta los hallazgos (corregir Estados / crear Tasks "
        "de corrección) y vuelve a ejecutar --verify ANTES de --apply.",
        file=sys.stderr,
    )
    if step2_path:
        print(f"Informe del Auditor (paso 2): {step2_path}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--check", action="store_true", help="reportar sin tocar nada; exit != 0 si hay US sin DONE"
    )
    group.add_argument("--apply", action="store_true", help="validar y escribir el nuevo esquema")
    group.add_argument(
        "--verify",
        action="store_true",
        help=(
            "gate de auditoria: ejecuta auditar-backlog + verificar-auditoria "
            "(pasos 1 y 2 de US-AF018-03) y bloquea el cierre con exit != 0 "
            "si el Auditor confirma discrepancias criticas"
        ),
    )
    args = parser.parse_args(argv)

    scheme = _load_version_scheme()
    closing = scheme["open"]
    future = list(scheme["future"])
    if not future:
        print(f"ERROR: no hay versiones futuras planificadas para cerrar '{closing}'.", file=sys.stderr)
        return 1

    not_done = _check_version(closing)
    print(f"Version a cerrar: {closing} (abierta actual)")
    print(f"US asignadas a {closing} no-DONE: {len(not_done)}")
    for entry in not_done:
        print(f"  {entry}")

    # T-AF018-US03-03: el gate de auditoría es independiente del control
    # declarativo de --check (mismo criterio que --apply): su decisión se
    # basa en lo que el Auditor confirma contra el código real, no en el
    # frontmatter. --apply sigue bloqueando si hay US no-DONE.
    if args.verify:
        return _run_verify(closing)

    if not_done:
        print(
            f"\nNo se puede cerrar {closing}: hay US no-DONE asignadas. "
            "Reasignalas a una version posterior o marcalas DONE antes de cerrar.",
            file=sys.stderr,
        )
        return 1

    new_open = future[0]
    new_future = _next_versions(new_open, 2)
    if args.check:
        print(f"\nEsquema resultante si se cierra {closing}:")
        print(f"  current_closed: {closing}")
        print(f"  open:           {new_open}")
        print(f"  future:         {new_future}")
        return 0

    scheme["current_closed"] = closing
    scheme["open"] = new_open
    scheme["future"] = new_future
    with open(VERSION_FILE, "w", encoding="utf-8") as fh:
        yaml.safe_dump(scheme, fh, allow_unicode=True, sort_keys=False, default_flow_style=False)
    print(f"\nVersion {closing} cerrada. Esquema actualizado en {VERSION_FILE}.")
    print(f"  current_closed: {closing}")
    print(f"  open:           {new_open}")
    print(f"  future:         {new_future}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

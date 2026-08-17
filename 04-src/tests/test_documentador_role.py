"""Tests para el rol Documentador (T-FB024-US20-01)."""

import re
from pathlib import Path

from brain.agents import DOCUMENTADOR_ROLE, DOCUMENTADOR_PROMPT, build_documentador_prompt
from brain.agents.roles import get_role, list_roles

_GOVERNANCE_PATH = (
    Path(__file__).resolve().parents[2] / "00-gobierno" / "DOCUMENTADOR.md"
)


def test_documentador_role_is_registered():
    """El rol 'documentador' está registrado en el catálogo de roles."""
    roles = list_roles()
    assert "documentador" in roles


def test_documentador_role_config_exists():
    """La configuración del rol 'documentador' existe y es accesible."""
    role_config = get_role(DOCUMENTADOR_ROLE)
    assert role_config is not None
    assert role_config.role == DOCUMENTADOR_ROLE
    assert role_config.governance_filename == "DOCUMENTADOR.md"
    assert role_config.prompt == DOCUMENTADOR_PROMPT
    assert role_config.prompt_builder is not None
    assert role_config.register_fn is not None


def test_documentador_role_constant():
    """DOCUMENTADOR_ROLE tiene el valor esperado."""
    assert DOCUMENTADOR_ROLE == "documentador"


def test_documentador_prompt_is_base_prompt():
    """DOCUMENTADOR_PROMPT es la versión base sin governance."""
    assert DOCUMENTADOR_PROMPT.startswith("Eres el agente Documentador de Factory Brain")


def test_documentador_has_register_function():
    """El rol documentador tiene función de registro asignada."""
    from brain.agents import register_documentador
    assert callable(register_documentador)


def test_documentador_role_with_reuse_pattern():
    """El rol documentador usa register_agent_with_reuse (reutilizable),
    no register_agent (nueva instancia cada vez) — mismo criterio que
    Tester (actúa puntualmente por encargo, no mantiene conversación
    entre Jobs sucesivos)."""
    from brain.agents.documentador import register_documentador
    import inspect
    source = inspect.getsource(register_documentador)
    assert "register_agent_with_reuse" in source


def test_build_documentador_prompt_adds_governance(tmp_path):
    """build_documentador_prompt añade governance instruction al prompt
    base — mismas tres capas que build_tester_prompt/build_ux_prompt."""
    project_path = tmp_path / "test_project"
    project_path.mkdir()
    (project_path / "00-gobierno").mkdir()
    (project_path / "00-gobierno" / "DOCUMENTADOR.md").write_text(
        "# Rol Documentador\nEste es el governance del Documentador."
    )
    (project_path / "00-gobierno" / "METODOLOGIA.md").write_text("# Metodología")

    prompt = build_documentador_prompt(str(project_path))

    assert DOCUMENTADOR_PROMPT in prompt
    assert "Rol Documentador" in prompt or len(prompt) > len(DOCUMENTADOR_PROMPT)


# ---------------------------------------------------------------------
# Fidelidad del contenido frente a 00-gobierno/DOCUMENTADOR.md (criterio
# de aceptación explícito de la Task: "verificado por lectura comparada,
# no solo 'existe'")
# ---------------------------------------------------------------------


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def test_documentador_prompt_matches_governance_file_content_verbatim():
    """DOCUMENTADOR_PROMPT contiene el texto ÍNTEGRO de
    00-gobierno/DOCUMENTADOR.md (desde `## Objetivo` en adelante — la
    única diferencia permitida es la frase de identidad inicial, mismo
    patrón que TESTER_PROMPT/`Eres el agente Tester...`), normalizando
    solo espacios en blanco. No una paráfrasis: byte a byte tras
    colapsar whitespace."""
    governance_content = _GOVERNANCE_PATH.read_text(encoding="utf-8")
    governance_body = governance_content.split("\n", 1)[1]  # sin el título H1

    prompt_body = DOCUMENTADOR_PROMPT.split("## Objetivo", 1)[1]
    governance_from_objetivo = governance_body.split("## Objetivo", 1)[1]

    assert _normalize(prompt_body) == _normalize(governance_from_objetivo)


def test_documentador_prompt_includes_full_gh_access_section():
    """Criterio de aceptación explícito: el prompt contiene los límites
    de acceso `gh` (permitido/requiere confirmación/nunca) — sección
    completa, no un resumen."""
    assert "Acceso a GitHub (`gh` CLI) — alcance y límites explícitos" in DOCUMENTADOR_PROMPT
    assert "**Permitido:**" in DOCUMENTADOR_PROMPT
    assert "**Requiere confirmación humana explícita antes de ejecutar (nunca" in DOCUMENTADOR_PROMPT
    assert "**Nunca hacer, bajo ninguna circunstancia:**" in DOCUMENTADOR_PROMPT


def test_documentador_prompt_gh_permitido_items_present():
    """Los tres puntos de 'Permitido' están presentes tal cual — sin
    relajar (no se puede añadir más) ni endurecer (no se puede quitar
    ninguno)."""
    for fragment in (
        "Crear/editar ficheros de plantilla oficiales del repo",
        "Consultar estado actual vía `gh` antes de proponer cambios",
        "Actualizar la descripción/topics del repo (`gh repo edit`)",
    ):
        assert fragment in DOCUMENTADOR_PROMPT


def test_documentador_prompt_gh_requiere_confirmacion_items_present():
    for fragment in (
        "Publicar un Release (`gh release create`)",
        "Activar/modificar GitHub Actions workflows",
        "Cualquier operación de `gh` que modifique permisos, "
        "colaboradores, branch protection, o webhooks",
    ):
        assert fragment in DOCUMENTADOR_PROMPT


def test_documentador_prompt_gh_nunca_items_present():
    for fragment in (
        "Forzar push, borrar branches/tags",
        "Publicar o modificar Releases/tags sin que el humano lo haya "
        "pedido",
    ):
        assert fragment in DOCUMENTADOR_PROMPT

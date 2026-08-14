import pytest

from brain.models import Runtime
from brain.runtime.generic import ParsedSessionName, parse_session_name, session_name_for


def _test_runtime() -> Runtime:
    return Runtime(id="r1", name="Test Runtime", type="claude-code", command="x", args=[])


class _FakeArquitecto:
    name = "Arquitecto"


class _FakeDeveloper:
    def __init__(self, instance: int) -> None:
        self.name = f"Developer-{instance}"


# ── round-trip con session_name_for (criterio de aceptación explícito) ──────


def test_round_trip_for_arquitecto_recovers_role_and_project() -> None:
    runtime = _test_runtime()
    name = session_name_for(runtime, _FakeArquitecto(), "/workspace/mi-proyecto")

    parsed = parse_session_name(name)

    assert parsed == ParsedSessionName(
        role="arquitecto", project_name="mi-proyecto", instance=None
    )


@pytest.mark.parametrize("instance", [1, 2, 3, 10])
def test_round_trip_for_developer_recovers_role_project_and_instance(
    instance: int,
) -> None:
    runtime = _test_runtime()
    name = session_name_for(runtime, _FakeDeveloper(instance), "/workspace/mi-proyecto")

    parsed = parse_session_name(name)

    assert parsed == ParsedSessionName(
        role="developer", project_name="mi-proyecto", instance=instance
    )


def test_round_trip_preserves_project_name_with_internal_digits_and_hyphens() -> None:
    """Caso explícito de la Task: un nombre de proyecto real del workspace
    con guiones internos, incluyendo un segmento puramente numérico en
    medio (`006`) — no debe confundirse con el número de instancia de
    Developer, que solo puede ocupar el segmento INMEDIATAMENTE después
    del rol."""
    runtime = _test_runtime()
    project_path = "/workspace/PROD-006-factory-brain"

    arq_name = session_name_for(runtime, _FakeArquitecto(), project_path)
    assert parse_session_name(arq_name) == ParsedSessionName(
        role="arquitecto", project_name="prod-006-factory-brain", instance=None
    )

    dev_name = session_name_for(runtime, _FakeDeveloper(1), project_path)
    assert parse_session_name(dev_name) == ParsedSessionName(
        role="developer", project_name="prod-006-factory-brain", instance=1
    )


def test_round_trip_two_different_projects_produce_distinct_parseable_names() -> None:
    runtime = _test_runtime()
    name_a = session_name_for(runtime, _FakeArquitecto(), "/workspace/proyecto-a")
    name_b = session_name_for(runtime, _FakeArquitecto(), "/workspace/proyecto-b")

    assert name_a != name_b
    assert parse_session_name(name_a).project_name == "proyecto-a"
    assert parse_session_name(name_b).project_name == "proyecto-b"


# ── nombres no normalizados devuelven None, nunca excepción ─────────────────


def test_opaque_legacy_scheme_returns_none() -> None:
    # Esquema anterior a FB-030: f"{runtime.id}-{agent.id}", agent.id es un
    # UUID — "claude-code" no es un rol registrado, así que no matchea.
    legacy_name = "claude-code-9e2e1b8e-8a6e-48d3-8301-6da3cdcc8423"
    assert parse_session_name(legacy_name) is None


def test_unrelated_tmux_session_name_returns_none() -> None:
    assert parse_session_name("my-random-tmux-session") is None


def test_empty_string_returns_none() -> None:
    assert parse_session_name("") is None


def test_role_only_without_project_is_parsed_with_empty_project_name() -> None:
    # Caso degenerado ya contemplado por session_name_for cuando
    # project_path está vacío (devuelve solo el role_part).
    assert parse_session_name("arquitecto") == ParsedSessionName(
        role="arquitecto", project_name="", instance=None
    )


def test_role_like_prefix_without_matching_role_returns_none() -> None:
    assert parse_session_name("notarole-mi-proyecto") is None

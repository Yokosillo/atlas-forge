import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from atlas_forge.local_tools import (
    ScribeUnavailableError,
    index_documents,
    index_scripts,
    resumir_estado_backlog,
    summarize_document,
)
from atlas_forge.models import GenericScriptEntry, ScriptEntry


def _ollama_is_reachable() -> bool:
    """Comprueba si hay un servidor Ollama real corriendo en el entorno
    de desarrollo, para decidir si el test de integración se ejecuta o se
    salta (T-AF014-US01-01, criterio de aceptación 1: decidir y
    documentar el criterio de test contra Ollama real)."""
    try:
        requests.get("http://localhost:11434/api/tags", timeout=1)
        return True
    except requests.RequestException:
        return False


def _mock_ollama_response(content: str) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"choices": [{"message": {"content": content}}]}
    return response


def test_summarize_document_sends_the_fixed_prompt_template_without_real_ollama() -> (
    None
):
    # Test que verifica la plantilla exacta enviada, mockeando la llamada
    # HTTP — no requiere que Ollama esté corriendo (criterio de aceptación
    # 4 de la Task).
    with patch("atlas_forge.local_tools.scribe.requests.post") as mock_post:
        mock_post.return_value = _mock_ollama_response("a coherent summary")

        result = summarize_document("some long document text", model="test-model")

        assert result == "a coherent summary"
        mock_post.assert_called_once()
        call_args, call_kwargs = mock_post.call_args
        assert call_args[0] == "http://localhost:11434/v1/chat/completions"
        sent_payload = call_kwargs["json"]
        assert sent_payload["model"] == "test-model"
        prompt = sent_payload["messages"][0]["content"]
        assert "some long document text" in prompt
        assert "Resume el siguiente documento" in prompt


def test_index_documents_sends_the_fixed_prompt_template_without_real_ollama() -> None:
    with patch("atlas_forge.local_tools.scribe.requests.post") as mock_post:
        mock_post.return_value = _mock_ollama_response("an index of topics")

        result = index_documents(["doc one text", "doc two text"], model="test-model")

        assert result == "an index of topics"
        call_args, call_kwargs = mock_post.call_args
        sent_payload = call_kwargs["json"]
        prompt = sent_payload["messages"][0]["content"]
        assert "doc one text" in prompt
        assert "doc two text" in prompt
        assert "Construye un índice temático" in prompt


def test_index_scripts_sends_the_fixed_prompt_template_without_real_ollama() -> None:
    # T-AF014-US02-01, criterio 4: test que verifica la plantilla de prompt
    # enviada sin necesitar Ollama corriendo (mockeando la llamada HTTP,
    # mismo criterio ya aplicado en T-AF014-US01-01). Se usan scripts reales
    # del catálogo (genéricos commit/push + un particular de ejemplo) para
    # verificar también que la serialización incluye id/nombre/comando.
    scripts = [
        GenericScriptEntry(id="commit", name="Commit de cambios"),
        GenericScriptEntry(id="push", name="Push al remoto"),
        ScriptEntry(
            id="deploy",
            name="Desplegar a producción",
            command="bash scripts/deploy.sh",
            description="Construye y despliega la app",
        ),
    ]
    with patch("atlas_forge.local_tools.scribe.requests.post") as mock_post:
        mock_post.return_value = _mock_ollama_response(
            "- commit: realiza un commit de los cambios\n"
            "- push: sube los cambios al remoto\n"
            "- deploy: construye y despliega la app"
        )

        result = index_scripts(scripts, model="test-model")

        assert "commit" in result
        call_args, call_kwargs = mock_post.call_args
        assert call_args[0] == "http://localhost:11434/v1/chat/completions"
        sent_payload = call_kwargs["json"]
        assert sent_payload["model"] == "test-model"
        prompt = sent_payload["messages"][0]["content"]
        # Los tres scripts del catálogo están serializados en el prompt.
        assert "- commit: Commit de cambios" in prompt
        assert "- push: Push al remoto" in prompt
        # El particular incluye su comando y descripción; los genéricos no
        # tienen esos campos.
        assert "- deploy: Desplegar a producción (comando: bash scripts/deploy.sh) — Construye y despliega la app" in prompt
        assert "bash scripts/deploy.sh" in prompt
        # Plantilla fija propia de esta operación, distinta de index_documents.
        assert "resumen corto de qué hace cada uno de los siguientes" in prompt
        assert "no inventes comportamientos" in prompt


def test_summarize_document_does_not_accept_arbitrary_prompt_parameter() -> None:
    # No existe ningún parámetro de prompt libre — solo `text`, `model`,
    # `base_url`, `timeout_seconds` (criterio de aceptación: ninguna
    # operación acepta un prompt arbitrario).
    import inspect

    signature = inspect.signature(summarize_document)
    assert "prompt" not in signature.parameters


def test_index_scripts_does_not_accept_arbitrary_prompt_parameter() -> None:
    # T-AF014-US02-01, criterio 2: no acepta un prompt arbitrario — la
    # plantilla es fija e interna, igual que el resto del catálogo.
    import inspect

    signature = inspect.signature(index_scripts)
    assert "prompt" not in signature.parameters


def test_index_scripts_raises_explicit_unavailable_error_when_ollama_is_down() -> None:
    # T-AF014-US02-01, criterio 3: degradación explícita — si el modelo
    # local no está disponible lanza ScribeUnavailableError (mismo tipo que
    # el resto del catálogo), sin bloquear a quien la invoque.
    scripts = [GenericScriptEntry(id="commit", name="Commit de cambios")]
    with patch("atlas_forge.local_tools.scribe.requests.post") as mock_post:
        mock_post.side_effect = requests.ConnectionError("connection refused")

        with pytest.raises(ScribeUnavailableError):
            index_scripts(scripts)


def test_resumir_estado_backlog_sends_the_fixed_prompt_template_without_real_ollama() -> (
    None
):
    # T-AF018-US02-03: misma disciplina que las demás operaciones del
    # catálogo cerrado — plantilla fija e interna, mockeando la llamada HTTP
    # (no requiere Ollama corriendo). El JSON del informe se incrusta como
    # única entrada, sin que Scribe relea ningún fichero de 02-backlog/.
    ejemplo_json = '{"total": {"items": 5, "tasks": {"READY": 3}, "errors": 0}}'
    with patch("atlas_forge.local_tools.scribe.requests.post") as mock_post:
        mock_post.return_value = _mock_ollama_response(
            "Hay 5 items. Hay 3 tasks TODO listas para empezar."
        )

        result = resumir_estado_backlog(ejemplo_json, model="test-model")

        assert result == "Hay 5 items. Hay 3 tasks TODO listas para empezar."
        mock_post.assert_called_once()
        call_args, call_kwargs = mock_post.call_args
        assert call_args[0] == "http://localhost:11434/v1/chat/completions"
        sent_payload = call_kwargs["json"]
        assert sent_payload["model"] == "test-model"
        prompt = sent_payload["messages"][0]["content"]
        # El JSON ya calculado llega incrustado en el prompt (única entrada).
        assert '{"total": {"items": 5' in prompt
        # Plantilla fija de esta operación, no prompt libre.
        assert "resumen breve en prosa" in prompt
        assert "Datos del backlog" in prompt


def test_resumir_estado_backlog_does_not_accept_arbitrary_prompt_parameter() -> None:
    import inspect

    signature = inspect.signature(resumir_estado_backlog)
    assert "prompt" not in signature.parameters


def test_resumir_estado_backlog_only_touches_the_http_layer_not_the_backlog() -> None:
    # Criterio de aceptación 2 de T-AF018-US02-03: Scribe NO relee ningún
    # fichero de 02-backlog/ — solo recibe el JSON ya calculado como entrada.
    # Se verifica que la operación no hace NINGUNA lectura de ficheros:
    # patching `Path.open` para que falle haría fallar el test si la
    # operación intentara leer algo del disco.
    ejemplo_json = '{"empty": true}'
    with patch("atlas_forge.local_tools.scribe.requests.post") as mock_post:
        mock_post.return_value = _mock_ollama_response("El backlog está vacío.")
        with patch("pathlib.Path.open", side_effect=AssertionError("leyó un fichero")):
            result = resumir_estado_backlog(ejemplo_json, model="test-model")

    assert result == "El backlog está vacío."


def test_resumir_estado_backlog_raises_explicit_unavailable_error() -> None:
    # Misma degradación explícita que el resto del catálogo: modelo local no
    # disponible -> ScribeUnavailableError, no un error de red genérico.
    with patch("atlas_forge.local_tools.scribe.requests.post") as mock_post:
        mock_post.side_effect = requests.ConnectionError("connection refused")

        with pytest.raises(ScribeUnavailableError):
            resumir_estado_backlog('{"empty": true}')


def test_scribe_raises_explicit_unavailable_error_when_ollama_is_unreachable() -> None:
    # Degradación explícita: el modelo local no disponible se traduce a
    # una excepción específica, no un error genérico de red sin contexto.
    with patch("atlas_forge.local_tools.scribe.requests.post") as mock_post:
        mock_post.side_effect = requests.ConnectionError("connection refused")

        with pytest.raises(ScribeUnavailableError):
            summarize_document("some text")


def test_scribe_raises_explicit_error_on_unexpected_response_body_without_choices() -> (
    None
):
    # Respuesta HTTP 200 (sin error de red) pero con un cuerpo que no
    # tiene la clave "choices" esperada (p. ej. Ollama devolviendo un
    # error de aplicación con status 200) — debe traducirse a
    # ScribeUnavailableError con el cuerpo recibido para diagnóstico, no
    # a un KeyError/IndexError/TypeError sin contexto.
    with patch("atlas_forge.local_tools.scribe.requests.post") as mock_post:
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"error": "model not found"}
        mock_post.return_value = response

        with pytest.raises(ScribeUnavailableError) as exc_info:
            summarize_document("some text")

        assert "model not found" in str(exc_info.value)


def test_scribe_raises_explicit_error_with_specific_reason_for_model_not_found() -> None:
    # T-AF014-US01-02, criterio de aceptación 2: "invocar con un modelo
    # no descargado en Ollama lanza ScribeUnavailableError con el motivo
    # específico". Ollama responde con un error HTTP (no 200) cuando el
    # modelo no está descargado — `raise_for_status()` lo traduce a
    # `requests.HTTPError`, que trae la respuesta original en
    # `error.response` con el motivo exacto reportado por Ollama.
    with patch("atlas_forge.local_tools.scribe.requests.post") as mock_post:
        response = MagicMock()
        response.status_code = 404
        response.json.return_value = {
            "error": "model 'nonexistent-model' not found, try pulling it first"
        }
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
        mock_post.return_value = response

        with pytest.raises(ScribeUnavailableError) as exc_info:
            summarize_document("some text", model="nonexistent-model")

        message = str(exc_info.value)
        assert "nonexistent-model" in message
        assert "not found" in message
        assert "404" in message


def test_scribe_raises_explicit_unavailable_error_when_connection_is_refused() -> None:
    # T-AF014-US01-02, criterio de aceptación 1: "invocar una operación
    # de Scribe con Ollama no disponible (puerto cerrado, servidor no
    # corriendo) lanza ScribeUnavailableError con mensaje claro, no una
    # excepción genérica ni un colgado indefinido". Distinto del test ya
    # existente `test_scribe_raises_explicit_unavailable_error_when_ollama_is_unreachable`
    # en que aquí se verifica también el mensaje (motivo claro, incluye
    # base_url y modelo), no solo el tipo de excepción.
    with patch("atlas_forge.local_tools.scribe.requests.post") as mock_post:
        mock_post.side_effect = requests.ConnectionError(
            "[Errno 111] Connection refused"
        )

        with pytest.raises(ScribeUnavailableError) as exc_info:
            summarize_document("some text", base_url="http://localhost:11434")

        message = str(exc_info.value)
        assert "localhost:11434" in message
        assert "Connection refused" in message


def test_scribe_respects_configured_timeout_without_hanging_indefinitely() -> None:
    # T-AF014-US01-02, criterio de aceptación 4: "test que verifica que
    # el timeout configurado se respeta (no cuelga más allá del valor
    # configurado)". Se simula que `requests.post` tarda más que el
    # timeout configurado lanzando `requests.Timeout` — comportamiento
    # real de la propia librería cuando se supera `timeout=` — y se
    # verifica que `summarize_document` devuelve el control (como
    # `ScribeUnavailableError`) en un tiempo acotado, no que se queda
    # esperando indefinidamente.
    configured_timeout = 0.2

    def _raise_after_delay(*args, **kwargs):
        assert kwargs["timeout"] == configured_timeout
        time.sleep(configured_timeout)
        raise requests.Timeout("Read timed out.")

    with patch("atlas_forge.local_tools.scribe.requests.post") as mock_post:
        mock_post.side_effect = _raise_after_delay

        started_at = time.monotonic()
        with pytest.raises(ScribeUnavailableError):
            summarize_document("some text", timeout_seconds=configured_timeout)
        elapsed = time.monotonic() - started_at

        # Margen generoso sobre el timeout configurado para absorber
        # jitter del entorno de test, sin dejar de detectar un colgado
        # real (que tardaría muchos segundos/indefinidamente).
        assert elapsed < configured_timeout + 2.0


def test_caller_can_catch_scribe_unavailable_error_and_continue_without_it() -> None:
    # T-AF014-US01-02, descripción punto 2: formaliza el patrón de
    # consumo que debe seguir quien invoque Scribe (Developer/Critic, o
    # el Dispatcher en US-AF008-03) — capturar `ScribeUnavailableError` y
    # continuar su propio flujo con un resultado de repliegue, en vez de
    # dejar que la excepción se propague y bloquee el resto de Atlas Forge
    # Atlas Forge.
    def _read_document_maybe_summarized(full_text: str) -> str:
        try:
            return summarize_document(full_text)
        except ScribeUnavailableError:
            return full_text

    with patch("atlas_forge.local_tools.scribe.requests.post") as mock_post:
        mock_post.side_effect = requests.ConnectionError("connection refused")

        result = _read_document_maybe_summarized("the full original document text")

    assert result == "the full original document text"


@pytest.mark.skipif(
    not _ollama_is_reachable(),
    reason="Ollama no está corriendo en este entorno de desarrollo — "
    "test de integración opcional, se salta si no hay servidor real.",
)
def test_summarize_document_against_real_ollama_server() -> None:
    # Test de integración real: solo se ejecuta si hay un servidor Ollama
    # accesible en el entorno (ver _ollama_is_reachable). En este entorno
    # de desarrollo Ollama no está instalado/corriendo (verificado con
    # `curl localhost:11434` antes de escribir esta Task), así que este
    # test se marca como skipped, no como fallo.
    result = summarize_document("Atlas Forge is a development orchestration tool.")

    assert isinstance(result, str)
    assert len(result) > 0

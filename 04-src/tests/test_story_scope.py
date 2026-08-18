"""Tests de `brain.dispatcher.story_scope` (T-FB022-US15-04): heurística
de detección de si una User Story "toca `10-web/`" sobre sus informes de
cierre ya existentes — ver el módulo para la justificación de diseño
frente a las otras dos opciones de la Task (git diff de commits, campo
nuevo de frontmatter)."""

from brain.dispatcher.story_scope import story_touches_web


def test_detects_a_report_mentioning_a_10_web_path():
    report = "# Informe\n\n**`10-web/app.js`**: cambios en el panel.\n"

    assert story_touches_web([report]) is True


def test_does_not_detect_a_report_mentioning_only_backend_paths():
    report = "# Informe\n\n**`04-src/src/brain/api/routes.py`**: cambios.\n"

    assert story_touches_web([report]) is False


def test_detects_web_scope_even_if_mixed_with_backend_reports():
    backend_report = "# Informe\n\n**`04-src/src/brain/api/routes.py`**: cambios.\n"
    web_report = "# Informe\n\n**`10-web/style.css`**: nuevas clases.\n"

    assert story_touches_web([backend_report, web_report]) is True


def test_returns_false_for_empty_reports_list():
    assert story_touches_web([]) is False


def test_does_not_false_positive_on_unrelated_text_mentioning_web_loosely():
    # "web" a secas, sin la ruta real "10-web/", no debe disparar el
    # falso positivo — la heurística busca la ruta concreta del repo, no
    # la palabra genérica.
    report = "# Informe\n\nEsta Task no toca nada de la interfaz web.\n"

    assert story_touches_web([report]) is False

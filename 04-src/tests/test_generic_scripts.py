"""Tests de T-FB018-US01-01: catálogo fijo de scripts genéricos basados en
`git` (commit, push, changed_files, diff_stat) y su ejecución real sobre un
repositorio, reutilizando el mecanismo de ejecución de T-FB001-US03-02
(`run_subprocess`, `brain/workspace/project_scripts.py`) y el mismo tipo
`ScriptRunResult`.

## ADVERTENCIA DE SEGURIDAD (verificada dos veces en cada test)

`commit` y `push` ejecutan comandos git REALES con efectos reales. Todos
los tests operan SIEMPRE sobre un repositorio git temporal aislado creado
con `tmp_path` (fixture de pytest: directorio temporal efímero) + `git
init`, NUNCA sobre el repositorio de trabajo de Factory Brain ni sobre
ningún otro repo real: cada test que toca git crea SU PROPIO repo con
`_init_repo(tmp_path / "repo")` y solo ejecuta comandos git con `-C`
apuntando a ese directorio. No hay ningún test que invoque git sobre la raíz
del proyecto ni sobre el directorio de trabajo actual.

Mismo criterio de "comportamiento real, no simulado" ya aplicado en el
resto del proyecto (p. ej. `test_run_project_script.py`): nunca se mockea
`subprocess.run` ni el binario `git`, se ejecutan de verdad sobre el repo
temporal aislado.
"""

import json
import subprocess
from pathlib import Path

import pytest

from brain.workspace.generic_scripts import list_generic_scripts, run_generic_script


def _git(repo_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Ejecuta un comando git REAL sobre `repo_path` (directorio de
    trabajo del repo temporal aislado) — nunca sobre el repo real de
    Factory Brain. Usado solo para preparar el repo en el setup de cada
    test y para verificar resultados."""
    return subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _init_repo(repo_path: Path) -> None:
    """Crea un repositorio git REAL nuevo y aislado en `repo_path` (un
    subdirectorio de `tmp_path`), con identidad de usuario configurada para
    que `git commit` funcione (git exige user.name/user.email si no hay una
    identidad global configurada)."""
    repo_path.mkdir(parents=True, exist_ok=True)
    _git(repo_path, "init", "-q")
    _git(repo_path, "config", "user.name", "Test Worker")
    _git(repo_path, "config", "user.email", "test-worker@example.invalid")


def _commit_file(repo_path: Path, filename: str, content: str) -> None:
    """Crea/sobrescribe `filename` en `repo_path` y lo commitea — setup de
    cada test, ejecutado con git real sobre el repo temporal aislado."""
    (repo_path / filename).write_text(content, encoding="utf-8")
    _git(repo_path, "add", filename)
    _git(repo_path, "commit", "-q", "-m", f"add {filename}")


def _current_branch(repo_path: Path) -> str:
    """Nombre de la rama actual del repo temporal aislado (git 2.39 crea
    `master` por defecto, versiones nuevas `main`) — se usa para establecer
    el upstream en el test de push sin asumir un nombre de rama fijo."""
    return _git(repo_path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


# ---------------------------------------------------------------------------
# Catálogo fijo
# ---------------------------------------------------------------------------


def test_list_generic_scripts_returns_the_fixed_catalog_with_its_6_identifiers() -> None:
    entries = list_generic_scripts()

    assert [entry.id for entry in entries] == [
        "commit",
        "push",
        "changed_files",
        "diff_stat",
        "language_stats",
        "backlog_status",
    ]
    # Cada entrada tiene un nombre visible (no vacío) para la interfaz.
    assert all(entry.name.strip() for entry in entries)


def test_list_generic_scripts_does_not_leak_mutable_internal_state() -> None:
    first = list_generic_scripts()
    first.clear()

    assert [entry.id for entry in list_generic_scripts()] == [
        "commit",
        "push",
        "changed_files",
        "diff_stat",
        "language_stats",
        "backlog_status",
    ]


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------


def test_commit_creates_a_real_commit_with_the_given_message(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit_file(repo, "file.txt", "v1")
    # Cambio real pendiente de comitear (el commit genérico NO debe crear
    # nada si no hay nada que comitear).
    (repo / "file.txt").write_text("v2", encoding="utf-8")
    _git(repo, "add", "file.txt")

    result = run_generic_script("commit", str(repo), message="mi primer commit")

    assert result.success is True
    assert result.exit_code == 0
    # Verificación real: el último commit del repo temporal aislado tiene el
    # mensaje pedido.
    log = _git(repo, "log", "-1", "--format=%s").stdout.strip()
    assert log == "mi primer commit"
    # Y el árbol quedó limpio (nada pendiente de comitear).
    status = _git(repo, "status", "--porcelain").stdout.strip()
    assert status == ""


def test_commit_without_message_is_rejected_explicitly(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit_file(repo, "file.txt", "v1")

    result = run_generic_script("commit", str(repo))

    assert result.success is False
    assert result.exit_code is None
    assert "'message'" in result.error_message


def test_commit_with_nothing_to_commit_reflects_the_real_git_failure(
    tmp_path: Path,
) -> None:
    """Criterio de aceptación: 'un fallo real de git (nada que comitear)
    se refleja en ScriptRunResult con la salida real de git, sin excepción
    no controlada' — y no se llega a crear ningún commit."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit_file(repo, "file.txt", "v1")

    result = run_generic_script("commit", str(repo), message="sin cambios")

    assert result.success is False
    assert result.exit_code is not None
    assert result.exit_code != 0
    # La salida real de git está disponible para diagnóstico.
    combined = (result.stdout + result.stderr).lower()
    assert "nothing to commit" in combined or "nada que" in combined


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------


def test_push_pushes_pending_commits_to_the_configured_remote(
    tmp_path: Path,
) -> None:
    """Push real: se monta un remoto local de prueba (un repo `--bare`
    dentro de `tmp_path`), se configura como `origin`, se establece el
    upstream en el setup y se verifica que un commit pendiente llega al
    remoto."""
    repo = tmp_path / "repo"
    bare_remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-q", str(bare_remote)],
        capture_output=True,
        text=True,
        check=True,
    )

    _init_repo(repo)
    _commit_file(repo, "file.txt", "v1")
    _git(repo, "remote", "add", "origin", str(bare_remote))
    # Setup: establece origin/<rama actual> como upstream para que un
    # `git push` simple (sin argumentos) funcione sobre este repo temporal
    # aislado.
    branch = _current_branch(repo)
    _git(repo, "push", "-q", "-u", "origin", branch)

    # Commit pendiente de empujar.
    _commit_file(repo, "file2.txt", "v2")
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""

    result = run_generic_script("push", str(repo))

    assert result.success is True
    assert result.exit_code == 0
    # Verificación real: el remoto local de prueba tiene el commit pendiente.
    remote_log = _git(bare_remote, "log", "-1", "--format=%s").stdout.strip()
    assert remote_log == "add file2.txt"


def test_push_without_a_configured_remote_reflects_the_real_git_failure(
    tmp_path: Path,
) -> None:
    """Criterio de aceptación: 'un fallo real de git (remoto no configurado)
    se refleja en ScriptRunResult con la salida real de git, sin excepción
    no controlada'."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit_file(repo, "file.txt", "v1")

    result = run_generic_script("push", str(repo))

    assert result.success is False
    assert result.exit_code is not None
    assert result.exit_code != 0
    combined = (result.stdout + result.stderr).lower()
    assert "remote" in combined or "push" in combined


# ---------------------------------------------------------------------------
# changed_files
# ---------------------------------------------------------------------------


def test_changed_files_returns_the_real_list_of_modified_files_since_last_commit(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit_file(repo, "unchanged.txt", "v1")
    _commit_file(repo, "modified.txt", "v1")
    # Modificación real tras el último commit (sin commitearla).
    (repo / "modified.txt").write_text("v2", encoding="utf-8")

    result = run_generic_script("changed_files", str(repo))

    assert result.success is True
    assert result.exit_code == 0
    names = result.stdout.splitlines()
    assert "modified.txt" in names
    assert "unchanged.txt" not in names


def test_changed_files_with_a_clean_worktree_returns_an_empty_list(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit_file(repo, "file.txt", "v1")

    result = run_generic_script("changed_files", str(repo))

    assert result.success is True
    assert result.exit_code == 0
    assert result.stdout.strip() == ""


# ---------------------------------------------------------------------------
# diff_stat
# ---------------------------------------------------------------------------


def test_diff_stat_returns_the_summary_not_the_full_diff(tmp_path: Path) -> None:
    """Criterio de ahorro de tokens: el resultado debe ser
    significativamente más corto que `git diff` sin `--stat` para un cambio
    de prueba con varios ficheros, y no debe contener el contenido completo
    del diff."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit_file(repo, "file_a.txt", "linea original a\n")
    _commit_file(repo, "file_b.txt", "linea original b\n")
    # Cambio real en varios ficheros, con líneas nuevas largas (contenido
    # que NO debe aparecer entero en el resumen).
    (repo / "file_a.txt").write_text(
        "linea original a\n" + "nueva linea muy larga numero 1 de a\n" * 40,
        encoding="utf-8",
    )
    (repo / "file_b.txt").write_text(
        "linea original b\n" + "nueva linea muy larga numero 2 de b\n" * 40,
        encoding="utf-8",
    )

    result = run_generic_script("diff_stat", str(repo))
    full_diff = _git(repo, "diff").stdout

    assert result.success is True
    assert result.exit_code == 0
    summary = result.stdout
    # Es un resumen por fichero, no el diff completo: mucho más corto.
    assert len(summary) < len(full_diff) / 10
    # Menciona ambos ficheros del cambio.
    assert "file_a.txt" in summary
    assert "file_b.txt" in summary
    # NO contiene el contenido completo del diff (las líneas nuevas largas).
    assert "nueva linea muy larga numero 1 de a" not in summary
    assert "nueva linea muy larga numero 2 de b" not in summary


# ---------------------------------------------------------------------------
# language_stats
# ---------------------------------------------------------------------------


def test_language_stats_returns_the_real_language_breakdown_of_the_project(
    tmp_path: Path,
) -> None:
    """Criterio de aceptación: `run_generic_script("language_stats",
    project_path)` devuelve el desglose real de lenguajes del proyecto —
    ejecución REAL de la herramienta externa (cloc, decidido en la Task)
    sobre el repo temporal aislado, nunca mockeada."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (repo / "style.css").write_text("body { color: red; }\n", encoding="utf-8")

    result = run_generic_script("language_stats", str(repo))

    assert result.success is True
    assert result.exit_code == 0
    # Salida JSON nativa de cloc con el desglose por lenguaje real.
    assert "Python" in result.stdout
    assert "CSS" in result.stdout


def test_language_stats_reports_a_missing_external_tool_explicitly(
    tmp_path: Path, monkeypatch
) -> None:
    """Criterio de aceptación: 'si la herramienta externa no está
    instalada, el fallo es explícito y menciona qué instalar, no un
    FileNotFoundError genérico'. Se simula la herramienta ausente
    (monkeypatch de `shutil.which`) porque cloc SÍ está instalado en esta
    VM — no se desinstala nada real."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    import brain.workspace.generic_scripts as generic_scripts

    monkeypatch.setattr(generic_scripts.shutil, "which", lambda _name: None)

    result = run_generic_script("language_stats", str(repo))

    assert result.success is False
    assert result.exit_code is None
    assert "cloc" in result.error_message
    # El mensaje explica cómo instalarla, no un error de comando genérico.
    assert "apt-get" in result.error_message or "brew" in result.error_message


def test_language_stats_with_a_non_git_path_is_rejected_before_touching_the_tool(
    tmp_path: Path,
) -> None:
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()

    result = run_generic_script("language_stats", str(not_a_repo))

    assert result.success is False
    assert result.exit_code is None
    assert "no es un repositorio git válido" in result.error_message


# ---------------------------------------------------------------------------
# backlog_status
# ---------------------------------------------------------------------------


def _write_backlog_file(path: Path, item_id: str, *, state: str, priority: str) -> None:
    """Escribe un fichero `.md` siguiendo la convención de `02-backlog/`
    (con `## Estado`, `## Dependencias` y `## Prioridad`)."""
    path.write_text(
        f"# {item_id}\n"
        f"**Epic:** FB-999 · Epic de prueba\n"
        f"## Estado\n\n{state}\n\n"
        f"## Dependencias\n\nNinguna.\n\n"
        f"## Prioridad\n\n{priority}\n",
        encoding="utf-8",
    )


def test_backlog_status_returns_the_structured_report_in_stdout(tmp_path: Path) -> None:
    """Criterio de T-FB018-US02-02: la entrada del catálogo reusa el cálculo
    del comando `brain backlog-status` (misma fuente de verdad) y devuelve el
    informe JSON estructurado en stdout — sin duplicar lógica de invocación."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    backlog = repo / "02-backlog"
    (backlog / "user-stories").mkdir(parents=True)
    (backlog / "tasks").mkdir(parents=True)
    _write_backlog_file(backlog / "user-stories" / "US-FB999-01.md", "US-FB999-01", state="DONE", priority="Alta.")
    _write_backlog_file(backlog / "tasks" / "T-FB999-01.md", "T-FB999-01", state="TODO", priority="Crítica.")
    (repo / "file.txt").write_text("v1", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add backlog")

    result = run_generic_script("backlog_status", str(repo))

    assert result.success is True
    assert result.exit_code == 0
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert report["empty"] is False
    assert report["total"]["items"] == 2
    assert report["total"]["errors"] == 0
    # El item TODO LISTA (sin dependencias pendientes) aparece ordenado por
    # prioridad (Crítica antes que Alta).
    assert [entry["id"] for entry in report["items_lista"]] == ["T-FB999-01"]


def test_backlog_status_on_a_fresh_project_returns_empty_report(tmp_path: Path) -> None:
    """Criterio de T-FB018-US02-02: un proyecto recién creado sin US/Tasks es
    un resultado válido (`success=True`, informe `empty=True`), igual que el
    comando `brain backlog-status` — no una excepción."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "file.txt").write_text("v1", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")

    result = run_generic_script("backlog_status", str(repo))

    assert result.success is True
    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert report["empty"] is True
    assert report["total"]["items"] == 0


def test_backlog_status_with_a_non_git_path_is_rejected_explicitly(
    tmp_path: Path,
) -> None:
    """Mismo criterio que el resto del catálogo: `project_path` que no es un
    repositorio git válido se rechaza con un mensaje explícito."""
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()

    result = run_generic_script("backlog_status", str(not_a_repo))

    assert result.success is False
    assert result.exit_code is None
    assert "no es un repositorio git válido" in result.error_message


# ---------------------------------------------------------------------------
# Rechazo de un project_path que no es un repo git válido (para los 4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script_id, params",
    [
        ("commit", {"message": "cualquiera"}),
        ("push", {}),
        ("changed_files", {}),
        ("diff_stat", {}),
    ],
)
def test_non_git_project_path_is_rejected_explicitly_for_all_four_scripts(
    tmp_path: Path, script_id: str, params: dict
) -> None:
    """Criterio de aceptación: 'ejecutar sobre un project_path que no es un
    repositorio git válido se rechaza con un mensaje explícito, para los 4
    scripts' — un directorio temporal SIN `git init` (no es un repo git)."""
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()

    result = run_generic_script(script_id, str(not_a_repo), **params)

    assert result.success is False
    assert result.exit_code is None
    assert "no es un repositorio git válido" in result.error_message


# ---------------------------------------------------------------------------
# script_id desconocido
# ---------------------------------------------------------------------------


def test_unknown_generic_script_id_is_rejected_with_an_explicit_message(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    result = run_generic_script("does-not-exist", str(repo))

    assert result.success is False
    assert result.exit_code is None
    assert "does-not-exist" in result.error_message

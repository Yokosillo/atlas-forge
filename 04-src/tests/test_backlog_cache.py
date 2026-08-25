"""Tests de la caché determinista del BacklogGraph por proyecto
(T-AF048-US01-01, US-AF048-01) — `load_backlog_cached` en
`atlas_forge.backlog.parser`: invalidación por fingerprint mtime+size,
thread-safe, sin cambiar el contrato de `load_backlog`.

Cubre los criterios de aceptación:
- 2ª lectura sin cambios devuelve el MISMO grafo sin re-parsear (se demuestra
  con un contador sobre `parse_backlog_item`/`load_backlog`);
- tras editar un fichero real del backlog el fingerprint cambia y la siguiente
  lectura re-parsea y devuelve el dato nuevo (sin reiniciar ni cache-clear);
- corrección: para un backlog inmutable el grafo desde la caché es idéntico
  (mismas claves/items/estados) al de `load_backlog` directo;
- concurrencia: accesos concurrentes a la caché son seguros (lock) — sin
  grafos corruptos (doble-parseo no necesario; test de lecturas en hilos)."""
from __future__ import annotations

import threading
from pathlib import Path

from atlas_forge.backlog.parser import (
    _BACKLOG_CACHE,
    load_backlog,
    load_backlog_cached,
)


def _write_us(backlog: Path, us_id: str, state: str, title: str) -> Path:
    target = backlog / "user-stories" / f"{us_id}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "---\n"
        f"id: {us_id}\ntype: user_story\ntitle: {title}\nstate: {state}\n"
        "dependencies: []\nepic: AF-999\npriority: Alta\nversion: 0.9\n"
        "---\n\n## Historia\n\nH.\n\n## Criterios de aceptación\n\n- C.\n",
        encoding="utf-8",
    )
    return target


def _seed(backlog: Path) -> Path:
    for sub in ("epics", "user-stories", "tasks"):
        (backlog / sub).mkdir(parents=True, exist_ok=True)
    return backlog


def test_segunda_lectura_sin_cambios_no_reparsea(monkeypatch, tmp_path: Path) -> None:
    """Criterio: una 2ª lectura con igual fingerprint NO re-parsea — se
    demuestra contando las invocaciones de la parseadora real."""
    import atlas_forge.backlog.parser as backend_parser

    backlog = _seed(tmp_path / "b")
    _write_us(backlog, "US-AF900-01", "NO_TASKS", "Historia 1")

    parse_count = 0
    original_call = backend_parser.parse_backlog_item

    def counting(item_path):
        nonlocal parse_count
        parse_count += 1
        return original_call(item_path)

    monkeypatch.setattr(backend_parser, "parse_backlog_item", counting)

    first = load_backlog_cached(backlog)
    assert parse_count == 1

    # 2ª lectura: sin cambios, sin re-parsear un solo fichero.
    second = load_backlog_cached(backlog)
    assert parse_count == 1
    assert second is first  # mismo objeto servido desde la caché


def test_edit_invalida_y_next_read_devuelve_dato_nuevo(tmp_path: Path) -> None:
    """Criterio: tras editar un fichero (state), el fingerprint cambia y la
    siguiente lectura re-parsea y devuelve el estado nuevo — sin reiniciar."""
    backlog = _seed(tmp_path / "b")
    path = _write_us(backlog, "US-AF900-01", "NO_TASKS", "Historia")

    first = load_backlog_cached(backlog)
    assert first.items["US-AF900-01"].state == "NO_TASKS"

    # Editamos el fichero real (state READY).
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("state: NO_TASKS", "state: READY"), encoding="utf-8")

    second = load_backlog_cached(backlog)
    assert second.items["US-AF900-01"].state == "READY"
    assert second is not first  # se re-parseó


def test_correccion_cached_igual_a_directo(tmp_path: Path) -> None:
    """Criterio: para un backlog inmutable, el grafo de la caché es idéntico
    (mismas claves, estados y conteo) al de `load_backlog` directo."""
    backlog = _seed(tmp_path / "b")
    _write_us(backlog, "US-AF900-01", "NO_TASKS", "Historia")
    _write_us(backlog, "US-AF900-02", "DONE", "Historia 2")
    (backlog / "epics" / "AF-999.md").write_text(
        "---\nid: AF-999\ntype: epic\ntitle: Epic\nstate: TO_DO\ndependencies: []\nversion: 0.9\n"
        "---\n\n## Objetivo\n\nO.\n",
        encoding="utf-8",
    )

    cached = load_backlog_cached(backlog)
    direct = load_backlog(backlog)

    assert set(cached.items) == set(direct.items)
    for item_id, item in direct.items.items():
        assert cached.items[item_id].state == item.state
    assert len(cached.errors) == len(direct.errors)


def test_concurrencia_accesos_paralelos_seguros(tmp_path: Path) -> None:
    """Criterio: varios accesos concurrentes a la caché (mismo proyecto) son
    seguros — todos reciben un grafo coherente sin carreras de escritura."""
    backlog = _seed(tmp_path / "b")
    for i in range(1, 6):
        _write_us(backlog, f"US-AF900-{i:02d}", "NO_TASKS", f"Historia {i}")

    results: list = []
    errors: list = []

    def _reader():
        try:
            for _ in range(30):
                g = load_backlog_cached(backlog)
                results.append(len(g.items))
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=_reader) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert results and all(r == 5 for r in results)


def test_cache_vacia_tras_reparse_no_afecta_a_otros_proyectos(tmp_path: Path) -> None:
    """La clave es por backlog_path: dos proyectos distintos no comparten
    grafo ni fingerprint."""
    backlog_a = _seed(tmp_path / "a")
    backlog_b = _seed(tmp_path / "b")
    _write_us(backlog_a, "US-AF900-01", "NO_TASKS", "A")
    _write_us(backlog_b, "US-AF900-01", "DONE", "B")

    ga = load_backlog_cached(backlog_a)
    gb = load_backlog_cached(backlog_b)

    assert ga.items["US-AF900-01"].state == "NO_TASKS"
    assert gb.items["US-AF900-01"].state == "DONE"
    assert _BACKLOG_CACHE.get(str(backlog_a))[1] is ga

    # _BACKLOG_CACHE limpio para no contaminar otras suites.
    _BACKLOG_CACHE.clear()
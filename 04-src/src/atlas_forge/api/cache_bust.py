"""Cache-busting automático para archivos estáticos (T-AF021-US01-03).

Genera un hash de contenido de los archivos estáticos que se inyecta en el
HTML servido, garantizando que cambios reales en app.js/style.css/etc.
invalidan el cache del navegador automáticamente sin edición manual de
index.html.
"""

import hashlib
from pathlib import Path


def compute_static_file_hash(file_path: Path) -> str:
    """Computa el hash SHA256 de un archivo estático.

    Usado para generar el cache-bust version string. Solo se computa cuando
    se necesita (lazy), no a la carga del módulo.
    """
    if not file_path.exists():
        return "missing"
    try:
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            sha.update(f.read())
        # Devuelve los primeros 8 caracteres del hash (suficiente para
        # cache-busting, evita URLs muy largas)
        return sha.hexdigest()[:8]
    except (OSError, IOError):
        return "error"


def get_cache_bust_version(web_root: Path) -> str:
    """Computa el cache-bust version combinando hashes de los 4 archivos.

    Si cualquiera de los archivos cambia, la versión cambia. Se usa como el
    valor {{CACHE_BUST_VERSION}} en index.html y agent-pane.html.
    """
    files_to_hash = [
        web_root / "app.js",
        web_root / "style.css",
        web_root / "backend-client.js",
        web_root / "reconnecting-websocket.js",
    ]

    hashes = []
    for file_path in files_to_hash:
        hashes.append(compute_static_file_hash(file_path))

    # Combina todos los hashes en uno solo (SHA256 de la concatenación)
    combined = "".join(hashes)
    sha = hashlib.sha256(combined.encode("utf-8"))
    # Prefijo de fecha para legibilidad (YYYYMMDD formato) + primeros 6 chars del hash
    from datetime import datetime
    date_part = datetime.now().strftime("%Y%m%d")
    return f"{date_part}{sha.hexdigest()[:6]}"

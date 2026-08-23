"""Resolución del host en el que escucha el servidor (T-AF016-US01-01).

## Por qué nunca `0.0.0.0` por defecto en producción

AF-015 (T-AF015-US01-01) verificó en esta misma VM que escuchar en todas
las interfaces (`0.0.0.0`) en un host con IP pública lo deja alcanzable
desde internet incluso sin intención explícita de exponerlo — el hallazgo
real fue `sshd` escuchando en `0.0.0.0:22` con el firewall local inactivo,
recibiendo intentos de conexión activos desde IPs públicas ajenas a
Tailscale en cuestión de minutos. El mismo riesgo aplica a cualquier
servidor HTTP nuevo en la misma VM: `0.0.0.0` no es "todas las interfaces
de la red privada", es literalmente todas las interfaces, incluida la
pública. La Epic AF-016 fija explícitamente "sin autenticación propia — el
perímetro de seguridad es la pertenencia a la red Tailscale" (ver
`02-backlog/epics/AF-016-api-backend.md`, "Alcance v1"): si el proceso
escuchara en `0.0.0.0`, ese perímetro quedaría roto por diseño desde el
primer arranque, sin ninguna capa adicional (a diferencia de SSH, que al
menos exige una clave privada) — cualquiera con la IP pública de la VM
podría alcanzar la API sin restricción alguna.

Por eso el host por defecto de `atlas-forge-api` se resuelve dinámicamente a la
IP de la propia interfaz `tailscale0` de la VM (`tailscale ip -4`), nunca
un valor fijo ni `0.0.0.0`. Sigue siendo configurable explícitamente (para
desarrollo local sin VPN, o para un futuro entorno de test) vía el
parámetro `host` de `create_app`/`run_server`, pero el default nunca
degrada silenciosamente a "todas las interfaces"."""

import subprocess


class TailscaleHostUnavailableError(RuntimeError):
    """No se pudo resolver la IP de la interfaz Tailscale de este host —
    Tailscale no está instalado, no está corriendo, o el dispositivo no
    está unido a ninguna red (tailnet)."""


def resolve_tailscale_host() -> str:
    """Resuelve la IPv4 de la interfaz Tailscale de esta máquina
    ejecutando `tailscale ip -4` (mismo binario ya verificado en
    T-AF015-US01-01). Lanza `TailscaleHostUnavailableError` con el motivo
    específico si el binario no existe, el proceso falla, o la salida no
    es una IP reconocible — nunca degrada a `0.0.0.0` ni a `127.0.0.1` en
    silencio."""
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=True,
        )
    except FileNotFoundError as error:
        raise TailscaleHostUnavailableError(
            "El binario 'tailscale' no está instalado en este host."
        ) from error
    except subprocess.CalledProcessError as error:
        raise TailscaleHostUnavailableError(
            f"'tailscale ip -4' falló (código {error.returncode}): "
            f"{error.stderr.strip()}"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise TailscaleHostUnavailableError(
            "'tailscale ip -4' no respondió a tiempo."
        ) from error

    host = result.stdout.strip()
    if not host:
        raise TailscaleHostUnavailableError(
            "'tailscale ip -4' no devolvió ninguna dirección — el "
            "dispositivo puede no estar unido a ninguna red Tailscale."
        )
    return host

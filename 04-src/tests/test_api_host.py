import subprocess
from unittest.mock import patch

import pytest

from brain.api.host import TailscaleHostUnavailableError, resolve_tailscale_host


def _completed_process(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["tailscale", "ip", "-4"], returncode=returncode, stdout=stdout, stderr=""
    )


def test_resolve_tailscale_host_returns_the_ip_from_tailscale_cli() -> None:
    with patch(
        "brain.api.host.subprocess.run",
        return_value=_completed_process("100.86.252.40\n"),
    ):
        host = resolve_tailscale_host()

    assert host == "100.86.252.40"


def test_resolve_tailscale_host_never_returns_a_wildcard_or_loopback_address() -> None:
    # Verificación explícita del criterio de aceptación: "el servidor no
    # escucha en una IP pública por defecto" — la propia función de
    # resolución nunca puede devolver 0.0.0.0 ni 127.0.0.1 mientras
    # tailscale responda con una IP real de la tailnet.
    with patch(
        "brain.api.host.subprocess.run",
        return_value=_completed_process("100.86.252.40\n"),
    ):
        host = resolve_tailscale_host()

    assert host not in ("0.0.0.0", "127.0.0.1")
    assert host.startswith("100.")  # rango CGNAT reservado de Tailscale


def test_resolve_tailscale_host_raises_when_tailscale_binary_is_missing() -> None:
    with patch("brain.api.host.subprocess.run", side_effect=FileNotFoundError()):
        with pytest.raises(TailscaleHostUnavailableError):
            resolve_tailscale_host()


def test_resolve_tailscale_host_raises_when_tailscale_command_fails() -> None:
    error = subprocess.CalledProcessError(
        returncode=1, cmd=["tailscale", "ip", "-4"], stderr="not logged in"
    )
    with patch("brain.api.host.subprocess.run", side_effect=error):
        with pytest.raises(TailscaleHostUnavailableError):
            resolve_tailscale_host()


def test_resolve_tailscale_host_raises_when_tailscale_times_out() -> None:
    error = subprocess.TimeoutExpired(cmd=["tailscale", "ip", "-4"], timeout=5.0)
    with patch("brain.api.host.subprocess.run", side_effect=error):
        with pytest.raises(TailscaleHostUnavailableError):
            resolve_tailscale_host()


def test_resolve_tailscale_host_raises_when_output_is_empty() -> None:
    with patch(
        "brain.api.host.subprocess.run", return_value=_completed_process("\n")
    ):
        with pytest.raises(TailscaleHostUnavailableError):
            resolve_tailscale_host()

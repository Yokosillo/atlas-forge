from unittest.mock import patch

from brain.api.main import DEFAULT_PORT, run_server


def test_run_server_resolves_host_from_tailscale_by_default() -> None:
    with (
        patch(
            "brain.api.main.resolve_tailscale_host", return_value="100.86.252.40"
        ) as mock_resolve,
        patch("brain.api.main.uvicorn.run") as mock_uvicorn_run,
        patch("brain.api.main.create_app", return_value="the-app"),
    ):
        run_server()

    mock_resolve.assert_called_once()
    mock_uvicorn_run.assert_called_once_with(
        "the-app", host="100.86.252.40", port=DEFAULT_PORT
    )


def test_run_server_never_defaults_to_a_public_or_wildcard_host() -> None:
    with (
        patch(
            "brain.api.main.resolve_tailscale_host", return_value="100.86.252.40"
        ),
        patch("brain.api.main.uvicorn.run") as mock_uvicorn_run,
        patch("brain.api.main.create_app", return_value="the-app"),
    ):
        run_server()

    used_host = mock_uvicorn_run.call_args.kwargs["host"]
    assert used_host not in ("0.0.0.0", "127.0.0.1")


def test_run_server_honors_an_explicit_host_without_calling_tailscale() -> None:
    with (
        patch("brain.api.main.resolve_tailscale_host") as mock_resolve,
        patch("brain.api.main.uvicorn.run") as mock_uvicorn_run,
        patch("brain.api.main.create_app", return_value="the-app"),
    ):
        run_server(host="127.0.0.1", port=9000)

    mock_resolve.assert_not_called()
    mock_uvicorn_run.assert_called_once_with("the-app", host="127.0.0.1", port=9000)

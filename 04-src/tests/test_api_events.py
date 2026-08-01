import asyncio

from brain.api.events import _ChannelHub


def test_publish_without_registered_loop_does_not_raise() -> None:
    hub = _ChannelHub()

    # Sin loop registrado (p. ej. hub usado fuera de una app arrancada) y
    # sin conexiones: publish nunca debe lanzar ni bloquear.
    hub.publish({"event": "x"})


def test_publish_without_connections_does_not_raise_even_with_loop() -> None:
    async def _run() -> None:
        hub = _ChannelHub()
        hub.register_event_loop(asyncio.get_running_loop())

        hub.publish({"event": "x"})

    asyncio.run(_run())


def test_disconnect_removes_a_connection_from_the_hub() -> None:
    hub = _ChannelHub()

    class _FakeWebSocket:
        pass

    fake = _FakeWebSocket()
    hub._connections.add(fake)
    assert fake in hub._connections

    hub.disconnect(fake)

    assert fake not in hub._connections


def test_disconnect_of_an_unknown_connection_does_not_raise() -> None:
    hub = _ChannelHub()

    class _FakeWebSocket:
        pass

    # Nunca se registró — discard, no remove, no debe lanzar KeyError.
    hub.disconnect(_FakeWebSocket())

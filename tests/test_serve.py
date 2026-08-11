"""The launcher: choosing a port, finding the interface, opening the window."""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from typing import cast

import pytest
import uvicorn

from bounty_searcher.config import ConfigError
from bounty_searcher.serve import bind, resolve_interface, serve

HOST = "127.0.0.1"
# Long enough to be waited on, short enough not to slow the suite down.
TICK = 0.05


@pytest.fixture
def built(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    return dist


# -- the port --------------------------------------------------------------


def test_it_takes_the_port_it_asked_for() -> None:
    with socket.socket() as probe:
        probe.bind((HOST, 0))
        free = probe.getsockname()[1]

    sock = bind(HOST, free)
    with sock:
        assert sock.getsockname()[1] == free


def test_a_taken_port_gets_a_free_one_instead() -> None:
    """What makes a second window work rather than fail on the first line."""
    with socket.socket() as taken:
        taken.bind((HOST, 0))
        port = taken.getsockname()[1]

        sock = bind(HOST, port)
        with sock:
            assert sock.getsockname()[1] != port
            assert sock.getsockname()[1] != 0


def test_the_socket_is_bound_before_the_server_sees_it() -> None:
    """The port is known without asking whether one was free and then hoping."""
    sock = bind(HOST, 0)
    with sock:
        host, port = sock.getsockname()[:2]

        assert host == HOST
        assert port > 0


# -- the interface ---------------------------------------------------------


def test_an_interface_given_by_name_is_used(built: Path) -> None:
    assert resolve_interface(str(built)) == built


def test_an_interface_given_by_name_must_be_there(tmp_path: Path) -> None:
    """Asked for by name and absent is a mistake, not a reason to serve less."""
    with pytest.raises(ConfigError):
        resolve_interface(str(tmp_path / "nowhere"))


def test_a_directory_without_an_entry_point_is_not_an_interface(
    tmp_path: Path,
) -> None:
    (tmp_path / "empty").mkdir()

    with pytest.raises(ConfigError):
        resolve_interface(str(tmp_path / "empty"))


# -- starting up -----------------------------------------------------------


class FakeServer:
    """A server that comes up after a tick, or fails before it does."""

    def __init__(self, *, fails: bool = False) -> None:
        self.started = False
        self.fails = fails
        self.sockets: list[socket.socket] | None = None

    async def serve(self, sockets: list[socket.socket] | None = None) -> None:
        self.sockets = sockets
        await asyncio.sleep(TICK)
        if self.fails:
            raise RuntimeError("could not start")
        self.started = True
        await asyncio.sleep(TICK)


def as_server(fake: FakeServer) -> uvicorn.Server:
    return cast(uvicorn.Server, fake)


async def test_the_socket_is_handed_to_the_server() -> None:
    fake = FakeServer()
    sock = bind(HOST, 0)

    with sock:
        await serve(as_server(fake), sock, None)

    assert fake.sockets == [sock]


async def test_the_browser_opens_only_once_there_is_something_to_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A window opened optimistically lands on a connection refused page."""
    fake = FakeServer()
    opened: list[tuple[str, bool]] = []

    def record(url: str) -> bool:
        # Whether the server was up at the moment the window was opened, which
        # is the whole point of the test.
        opened.append((url, fake.started))
        return True

    monkeypatch.setattr("bounty_searcher.serve.webbrowser.open", record)
    sock = bind(HOST, 0)

    with sock:
        await serve(as_server(fake), sock, "http://corpus")

    assert opened == [("http://corpus", True)]


async def test_no_browser_opens_when_it_was_not_asked_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("bounty_searcher.serve.webbrowser.open", opened.append)
    sock = bind(HOST, 0)

    with sock:
        await serve(as_server(FakeServer()), sock, None)

    assert opened == []


async def test_a_server_that_never_starts_does_not_hang(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Otherwise the wait for the browser to open outlives the thing it waits on."""
    opened: list[str] = []
    monkeypatch.setattr("bounty_searcher.serve.webbrowser.open", opened.append)
    sock = bind(HOST, 0)

    with sock, pytest.raises(RuntimeError):
        await asyncio.wait_for(
            serve(as_server(FakeServer(fails=True)), sock, "http://corpus"), timeout=5
        )

    assert opened == []

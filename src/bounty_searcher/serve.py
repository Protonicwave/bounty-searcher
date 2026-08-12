"""The launcher: one process, one port, one window.

Everything the interface needs comes from here. The corpus is opened once, the
API is built over it, the built interface is served beside it, and a browser is
pointed at the result once there is something listening to answer it.

The port is chosen by binding rather than by asking whether a port is free and
then hoping. The bound socket is handed to the server, so nothing can take the
port in between, and the address printed is read back off the socket rather
than assumed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import sys
import webbrowser
from pathlib import Path

import uvicorn

from .api.app import create_app
from .config import ConfigError, load_config, scan_settings, score_weights
from .store.db import Database, default_db_path

# Asked for first, so the address is usually the same one as last time. Any
# free port will do if it is taken, which is what makes a second window work.
PREFERRED_PORT = 8000
HOST = "127.0.0.1"

# Where the build leaves the interface, relative to the repository root. An
# installed wheel does not carry it, which is what `--interface` is for.
INTERFACE = Path("web") / "dist"

# How often to look at whether the server has come up. Small enough that the
# browser opens on what feels like the same action, and it is only ever waited
# on for as long as the server takes to bind.
POLL_SECONDS = 0.02


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bounty-searcher-web",
        description="Open the bounty corpus in a browser.",
    )
    p.add_argument(
        "--port",
        type=int,
        default=PREFERRED_PORT,
        metavar="N",
        help=f"port to ask for (default {PREFERRED_PORT}; any free one if taken)",
    )
    p.add_argument("--host", default=HOST, help=f"address to bind (default {HOST})")
    p.add_argument("--db", default=None, help=f"corpus (default {default_db_path()})")
    p.add_argument("--config", default=None, help="path to a config.toml")
    p.add_argument("--token", default=None, help="GitHub token (or set GITHUB_TOKEN)")
    p.add_argument(
        "--interface",
        default=None,
        metavar="DIR",
        help="built interface to serve (default web/dist beside the source)",
    )
    p.add_argument(
        "--no-browser", action="store_true", help="do not open a browser window"
    )
    return p


def repository_interface() -> Path | None:
    """The built interface in a source checkout, if this is one.

    Three levels up from this file is the repository root when the package is
    imported from `src/`, which covers a checkout and an editable install. A
    wheel installed into site-packages has no `web/` beside it, and gets
    nothing rather than a guess.
    """
    candidate = Path(__file__).resolve().parents[2] / INTERFACE
    return candidate if (candidate / "index.html").is_file() else None


def resolve_interface(explicit: str | None) -> Path | None:
    """A path given by name must exist. The default one is allowed not to."""
    if explicit is None:
        return repository_interface()
    path = Path(explicit)
    if not (path / "index.html").is_file():
        raise ConfigError(f"no built interface at {path}")
    return path


def bind(host: str, port: int) -> socket.socket:
    """A socket on the asked-for port, or on any free one.

    Bound but not listening: the server does that, and until it does there is
    nothing to answer a connection. Nothing sets SO_REUSEADDR, because on
    Windows it permits taking a port another process is already using, which is
    the opposite of what is wanted here.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError:
        sock.bind((host, 0))
    return sock


async def open_when_listening(server: uvicorn.Server, url: str) -> None:
    """Open the browser once the server is up, and not before.

    A window opened optimistically races the server and lands on a connection
    refused page often enough to matter.
    """
    while not server.started:
        await asyncio.sleep(POLL_SECONDS)
    webbrowser.open(url)


async def serve(server: uvicorn.Server, sock: socket.socket, url: str | None) -> None:
    running = asyncio.create_task(server.serve(sockets=[sock]))
    if url is not None:
        opener = asyncio.create_task(open_when_listening(server, url))
        # If the server fails before it starts, the opener would wait forever.
        await asyncio.wait((running, opener), return_when=asyncio.FIRST_COMPLETED)
        opener.cancel()
    await running


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = load_config(args.config)
        interface = resolve_interface(args.interface)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if interface is None:
        print(
            "No built interface found, so this serves the API only.\n"
            "Build it with `npm install && npm run build` in web/, or point\n"
            "--interface at one.",
            file=sys.stderr,
        )

    settings = scan_settings(config)
    weights = score_weights(config, settings.languages)
    token = args.token or os.environ.get("GITHUB_TOKEN")

    sock = bind(args.host, args.port)
    host, port = sock.getsockname()[:2]
    url = f"http://{host}:{port}"

    with Database(args.db) as db:
        app = create_app(
            db,
            weights=weights,
            settings=settings,
            token=token,
            interface=interface,
        )
        # Warning level and no access log: a line per request is noise in the
        # window a user is only keeping open so the interface stays up.
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="warning", access_log=False)
        )

        # Flushed, because this is the one line that says where to look and
        # stdout is fully buffered whenever the launcher redirects it.
        print(f"bounty-searcher is at {url}   (ctrl-c to stop)", flush=True)
        asyncio.run(serve(server, sock, None if args.no_browser else url))

    return 0


if __name__ == "__main__":
    sys.exit(main())

# The Purpose of this server is to run benchmark independent of the network issues
import asyncio
import threading
import time
from collections.abc import Iterator, Callable, Coroutine
from socket import socket, SOCK_STREAM
from typing import Awaitable, Any

from pytest_asyncio.plugin import _unused_port
from uvicorn import Config
from uvicorn.server import Server
from yarl import URL

Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Coroutine[None, None, None]]


async def send_html_response(
    send: Send, html_content: bytes, status: int = 200
) -> None:
    """Send an HTML response to the client."""
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [[b"content-type", b"text/html; charset=utf-8"]],
        }
    )
    await send({"type": "http.response.body", "body": html_content})


async def app(scope: dict[str, Any], receive: Receive, send: Send) -> None:
    """Main ASGI application handler that routes requests to specific handlers.

    Args:
        scope: The ASGI connection scope.
        receive: The ASGI receive function.
        send: The ASGI send function.
    """
    assert scope["type"] == "http"
    path = scope["path"]

    # Route requests to appropriate handlers
    await generate_link_page(send=send, path=path)


async def generate_link_page(send: Send, path: str) -> None:
    """Handle basic requests with a simple HTML response."""
    depth_level = 3
    if len(path) == depth_level:
        links = ""
        pass
    else:
        # Links based on the level
        links = "\n".join(f'<a href="{path}{i}">{path}{i}</a>' for i in range(10))

    await send_html_response(
        send,
        f"""\
<html><head>
    <title>{path}</title>
</head>
<body>
    {links}
</body></html>""".encode("utf-8"),
    )


class TestServer(Server):
    """A test HTTP server implementation based on Uvicorn Server."""

    @property
    def url(self) -> URL:
        """Get the base URL of the server.

        Returns:
            A URL instance with the server's base URL.
        """
        protocol = "https" if self.config.is_ssl else "http"
        return URL(f"{protocol}://{self.config.host}:{self.config.port}/")

    async def serve(self, sockets: list[socket] | None = None) -> None:
        """Run the server and set up restart capability.

        Args:
            sockets: Optional list of sockets to bind to.
        """
        self.restart_requested = asyncio.Event()

        loop = asyncio.get_event_loop()
        tasks = {
            loop.create_task(super().serve(sockets=sockets)),
            loop.create_task(self.watch_restarts()),
        }
        await asyncio.wait(tasks)

    async def restart(self) -> None:
        """Request server restart and wait for it to complete.

        This method can be called from a different thread than the one the server
        is running on, and from a different async environment.
        """
        self.started = False
        self.restart_requested.set()
        while not self.started:  # noqa: ASYNC110
            await asyncio.sleep(0.2)

    async def watch_restarts(self) -> None:
        """Watch for and handle restart requests."""
        while True:
            if self.should_exit:
                return

            try:
                await asyncio.wait_for(self.restart_requested.wait(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

            self.restart_requested.clear()
            await self.shutdown()
            await self.startup()


class ThreadTestServer:
    def __init__(self, port: int | None = None) -> None:
        port = port or _unused_port(SOCK_STREAM)
        self.server = TestServer(config=Config(app=app, lifespan="off", loop="asyncio", port=port))
        self.thread = threading.Thread(target=self.server.run)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.server.should_exit = True
        self.thread.join()







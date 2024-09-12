import asyncio
import dataclasses
from tornado.web import Application
from tornado.httputil import (
    HTTPServerRequest,
    HTTPHeaders,
    HTTPConnection,
    RequestStartLine,
    ResponseStartLine,
)
from typing import Dict, Any, Callable, Awaitable, Optional, Union
from urllib.parse import quote
from tornado.concurrent import Future

import logging

logger = logging.getLogger(__name__)

Scope = Dict[str, Any]
Event = Dict[str, Any]


class TornadoASGIAdapter:
    def __init__(self, app: Application):
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Callable[[], Awaitable[Event]],
        send: Callable[[Event], Awaitable[None]],
    ):
        if scope["type"] != "http":
            raise ValueError("Only HTTP connections are supported")

        path = scope.get(
            "raw_path", quote(scope["path"], safe="/", encoding=None, errors=None)
        )
        if scope["query_string"]:
            path += "?" + scope["query_string"]

        start_line = RequestStartLine(
            method=scope["method"],
            path=path.decode("ascii"),
            version=f"HTTP/{scope['http_version']}",
        )
        headers = HTTPHeaders()
        for key, value in scope["headers"]:
            headers.add(key.decode("ascii"), value.decode("ascii"))

        connection = ASGIHTTPConnection(asyncio.get_event_loop(), scope, send)

        request = HTTPServerRequest(
            start_line=start_line,
            headers=headers,
            connection=connection,
        )

        handler = self.app.find_handler(request)
        if aw := handler.headers_received(start_line, request.headers):
            await aw

        while True:
            event = await receive()
            if event["type"] == "http.request":
                body = event.get("body", b"")
                if body:
                    if aw := handler.data_received(body):
                        await aw
                if not event.get("more_body", False):
                    handler.finish()
                    break
            elif event["type"] == "http.disconnect":
                connection.close()
                break

        await connection


@dataclasses.dataclass
class ConnectionContext:
    remote_ip: str
    protocol: str


class ASGIHTTPConnection(HTTPConnection, Awaitable[None]):
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        scope: Scope,
        send: Callable[[Event], Awaitable[None]],
    ):
        self.loop = loop
        self.scope = scope
        self.send = send
        self.context = ConnectionContext(
            remote_ip=scope["client"][0],
            protocol=scope.get("scheme", "http"),
        )
        self._finish = loop.create_future()
        self._close_callback = None

    def __await__(self):
        return self._finish.__await__()

    def write_headers(
        self,
        start_line: Union["RequestStartLine", "ResponseStartLine"],
        headers: HTTPHeaders,
        chunk: Optional[bytes] = None,
    ) -> "Future[None]":
        assert isinstance(start_line, ResponseStartLine)

        events = [
            {
                "type": "http.response.start",
                "status": start_line.code,
                "headers": [(key, value) for key, value in headers.items()],
            }
        ]

        if chunk:
            event = {
                "type": "http.response.body",
                "body": chunk,
                "more_body": True,  # don't know at this point, assume True
            }
            events.append(event)

        async def send_events():
            for event in events:
                await self.send(event)

        return self.loop.create_task(send_events())

    def write(self, chunk: bytes) -> "Future[None]":
        return self.loop.create_task(
            self.send(
                {
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": True,
                }
            )
        )

    def finish(self) -> None:
        task = self.loop.create_task(
            self.send(
                {
                    "type": "http.response.body",
                    "body": b"",
                    "more_body": False,
                }
            )
        )
        task.add_done_callback(lambda _: self._finish.set_result(None))

    def close(self) -> None:
        if self._close_callback:
            self._close_callback()
        self._finish.set_result(None)

    def set_close_callback(self, callback: Callable[[], None]) -> None:
        self._close_callback = callback

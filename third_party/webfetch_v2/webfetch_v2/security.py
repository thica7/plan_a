from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit


class PublicURLBlocked(ValueError):
    """The browser or HTTP client tried to reach a non-public destination."""


def validate_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise PublicURLBlocked("Only public HTTP(S) URLs can be fetched")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        resolve_public_addresses(parsed.hostname, port)
    except PublicURLBlocked:
        raise
    except (OSError, ValueError) as exc:
        raise PublicURLBlocked(f"Unable to resolve URL host: {parsed.hostname}") from exc


def resolve_public_addresses(hostname: str, port: int) -> list[str]:
    try:
        addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except (OSError, ValueError) as exc:
        raise PublicURLBlocked(f"Unable to resolve URL host: {hostname}") from exc
    if not addresses:
        raise PublicURLBlocked(f"Unable to resolve URL host: {hostname}")
    docker_proxy = ipaddress.ip_network("198.18.0.0/15")
    validated: list[str] = []
    for result in addresses:
        try:
            address = ipaddress.ip_address(result[4][0])
        except (IndexError, ValueError) as exc:
            raise PublicURLBlocked("URL host resolved to an invalid address") from exc
        if address.version == 4 and address in docker_proxy:
            validated.append(str(address))
            continue
        if not address.is_global:
            raise PublicURLBlocked(f"Blocked non-public address: {address}")
        validated.append(str(address))
    return list(dict.fromkeys(validated))


async def open_public_connection(hostname: str, port: int):
    """Resolve once, validate every answer, then dial the validated IP itself."""
    addresses = await asyncio.to_thread(resolve_public_addresses, hostname, port)
    last_error: OSError | None = None
    for address in addresses:
        try:
            return await asyncio.wait_for(asyncio.open_connection(address, port), timeout=10)
        except OSError as exc:
            last_error = exc
    raise PublicURLBlocked(f"Unable to connect to public host: {hostname}") from last_error


@asynccontextmanager
async def public_egress_proxy() -> AsyncIterator[str]:
    active: set[asyncio.Task[None]] = set()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            active.add(task)
        try:
            await _handle_proxy_connection(reader, writer)
        finally:
            if task is not None:
                active.discard(task)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)


async def _handle_proxy_connection(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
) -> None:
    upstream_writer: asyncio.StreamWriter | None = None
    try:
        first = await asyncio.wait_for(reader.readline(), timeout=10)
        if len(first) > 8192:
            raise PublicURLBlocked("Proxy request line is too long")
        method, target, version = first.decode("latin-1").strip().split(" ", 2)
        headers = bytearray()
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            if not line or line in {b"\r\n", b"\n"}:
                break
            if not line.lower().startswith((b"connection:", b"proxy-connection:")):
                headers.extend(line)
            if len(headers) > 65536:
                raise PublicURLBlocked("Proxy request headers are too large")
        if method.upper() == "CONNECT":
            parsed = urlsplit(f"//{target}")
            hostname = parsed.hostname
            port = parsed.port or 443
            if not hostname:
                raise PublicURLBlocked("CONNECT hostname is required")
            upstream_reader, upstream_writer = await open_public_connection(hostname, port)
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
        else:
            parsed = urlsplit(target)
            if parsed.scheme != "http" or not parsed.hostname:
                raise PublicURLBlocked("Only HTTP proxy requests are supported")
            upstream_reader, upstream_writer = await open_public_connection(
                parsed.hostname, parsed.port or 80,
            )
            path = parsed.path or "/"
            if parsed.query:
                path += f"?{parsed.query}"
            upstream_writer.write(f"{method} {path} {version}\r\n".encode("latin-1"))
            upstream_writer.write(headers)
            upstream_writer.write(b"Connection: close\r\n\r\n")
            await upstream_writer.drain()
        request_task = asyncio.create_task(_pipe(reader, upstream_writer))
        response_task = asyncio.create_task(_pipe(upstream_reader, writer))
        if method.upper() == "CONNECT":
            _done, pending = await asyncio.wait(
                {request_task, response_task}, return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
        else:
            await response_task
            request_task.cancel()
        await asyncio.gather(request_task, response_task, return_exceptions=True)
    except (PublicURLBlocked, ValueError, TimeoutError):
        writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
    except OSError:
        writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
    finally:
        if upstream_writer is not None:
            upstream_writer.close()
            await upstream_writer.wait_closed()
        writer.close()
        await writer.wait_closed()


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    while chunk := await reader.read(65536):
        writer.write(chunk)
        await writer.drain()

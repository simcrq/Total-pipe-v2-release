"""Shared stdlib-only stdio JSON-RPC 2.0 MCP server transport for Total-pipe."""
from __future__ import annotations

import io
import json
import os
import sys
import threading
from typing import Any, Callable, Iterator

PROTOCOL_VERSION = '2025-06-18'
SUPPORTED_PROTOCOLS = {'2025-06-18', '2025-03-26', '2024-11-05'}
DEFAULT_TIMEOUT = float(os.environ.get('TOTALPIPE_TOOL_TIMEOUT', os.environ.get('PWF2RPA_TOOL_TIMEOUT', '120')))


class _Divert:
    """Write-only stream that forwards anything printed to stderr."""

    def __init__(self, sink: Any) -> None:
        self._sink = sink

    def write(self, data: Any) -> int:
        try:
            self._sink.write(data)
        except Exception:
            pass
        return len(data) if hasattr(data, '__len__') else 0

    def flush(self) -> None:
        try:
            self._sink.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        raise io.UnsupportedOperation('stdout is reserved for JSON-RPC')


def run_callable(fn: Callable[[], Any], timeout: float = DEFAULT_TIMEOUT) -> Any:
    """Run a tool handler off the protocol thread with a wall-clock timeout."""
    box: dict[str, Any] = {}

    def target() -> None:
        saved = sys.stdout
        sys.stdout = _Divert(sys.stderr)
        try:
            box['value'] = fn()
        except BaseException as error:  # noqa: BLE001 - reported to the caller
            box['error'] = error
        finally:
            sys.stdout = saved

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError(f'tool timed out after {timeout:g} s')
    if 'error' in box:
        raise box['error']
    return box.get('value')


def _read_framed(stream: Any, first_line: bytes) -> bytes:
    headers: dict[str, str] = {}
    line = first_line
    while line and line not in (b'\r\n', b'\n'):
        if b':' in line:
            key, _, value = line.decode('utf-8', 'replace').partition(':')
            headers[key.strip().lower()] = value.strip()
        line = stream.readline()
    length = int(headers.get('content-length', '0') or 0)
    return stream.read(length) if length > 0 else b''


def iter_messages(stream: Any) -> Iterator[bytes]:
    """Yield raw message bodies, accepting both newline-delimited and LSP framing."""
    while True:
        line = stream.readline()
        if not line:
            return
        if not line.strip():
            continue
        raw = _read_framed(stream, line) if line.lower().startswith(b'content-length') else line
        if raw.strip():
            yield raw


class StdioMcpServer:
    """Reusable stdio MCP JSON-RPC dispatcher with explicit tool registry."""

    def __init__(self, server_name: str, server_version: str, instructions: str = '',
                 tools: dict[str, dict[str, Any]] | None = None) -> None:
        self.SERVER_NAME = server_name
        self.SERVER_VERSION = server_version
        self.INSTRUCTIONS = instructions
        self.TOOLS: dict[str, dict[str, Any]] = dict(tools or {})
        self.PROTOCOL_VERSION = PROTOCOL_VERSION
        self.SUPPORTED_PROTOCOLS = set(SUPPORTED_PROTOCOLS)

    def _tool_descriptors(self) -> list[dict[str, Any]]:
        return [
            {'name': name, 'description': spec['description'], 'inputSchema': spec['inputSchema']}
            for name, spec in self.TOOLS.items()
        ]

    @staticmethod
    def _write(message: dict[str, Any]) -> None:
        output = sys.__stdout__ or sys.stdout
        output.write(json.dumps(message, ensure_ascii=True) + '\n')
        output.flush()

    @staticmethod
    def _result(message_id: Any, result: Any) -> dict[str, Any] | None:
        return None if message_id is None else {'jsonrpc': '2.0', 'id': message_id, 'result': result}

    @staticmethod
    def _failure(message_id: Any, code: int, text: str) -> dict[str, Any] | None:
        if message_id is None:
            return None
        return {'jsonrpc': '2.0', 'id': message_id, 'error': {'code': code, 'message': text}}

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Dispatch one JSON-RPC request. Returns None for notifications."""
        if not isinstance(message, dict):
            return self._failure(None, -32600, 'request must be a JSON object')

        message_id = message.get('id')
        method = message.get('method')
        params = message.get('params') or {}

        if method == 'initialize':
            requested = params.get('protocolVersion')
            protocol = requested if requested in self.SUPPORTED_PROTOCOLS else self.PROTOCOL_VERSION
            return self._result(
                message_id,
                {
                    'protocolVersion': protocol,
                    'capabilities': {'tools': {'listChanged': False}},
                    'serverInfo': {'name': self.SERVER_NAME, 'version': self.SERVER_VERSION},
                    'instructions': self.INSTRUCTIONS,
                },
            )
        if method in ('notifications/initialized', 'initialized'):
            return None
        if method == 'ping':
            return self._result(message_id, {})
        if method == 'tools/list':
            return self._result(message_id, {'tools': self._tool_descriptors()})
        if method == 'tools/call':
            name = params.get('name')
            spec = self.TOOLS.get(name) if isinstance(name, str) else None
            if spec is None:
                return self._failure(message_id, -32602, 'unknown tool: ' + repr(name))
            arguments = params.get('arguments') or {}
            if not isinstance(arguments, dict):
                return self._failure(message_id, -32602, 'arguments must be an object')
            try:
                value = run_callable(lambda: spec['handler'](arguments), spec.get('timeout', DEFAULT_TIMEOUT))
            except Exception as error:  # noqa: BLE001 - surfaced as a tool error
                if hasattr(error, 'as_dict') and callable(error.as_dict):
                    text = json.dumps(error.as_dict(), ensure_ascii=False, indent=2)
                else:
                    text = f'{type(error).__name__}: {error}'
                return self._result(message_id, {'content': [{'type': 'text', 'text': text}], 'isError': True})
            return self._result(
                message_id,
                {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False, indent=2)}], 'isError': False},
            )
        if method in ('resources/list', 'prompts/list'):
            return self._result(message_id, {method.split('/')[0]: []})
        if method == 'shutdown':
            return self._result(message_id, {})
        return self._failure(message_id, -32601, 'method not found: ' + repr(method))

    def main(self) -> int:
        for raw in iter_messages(sys.stdin.buffer):
            try:
                message = json.loads(raw.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                self._write({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': str(error)}})
                continue
            response = self.handle(message)
            if response is not None:
                self._write(response)
        return 0

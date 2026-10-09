#!/usr/bin/env python3
"""jsonl-v2 SPARQL HTTP client worker with one keep-alive session.

Run as: ``python -m benchmark_core.http_runner.client '<json config>'``. The runner talks
to it over stdin/stdout. For every query the worker writes two lines: ``done`` as soon as the
complete HTTP response body has been read (the runner stops its timer there), then ``result``
with the count and correctness data, which is never timed.

The timed part is the POST plus reading the complete response body. Counting, JSON parsing and
fingerprinting happen after ``done``.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import urllib.parse

import requests
import requests.adapters
import urllib3.connection
import urllib3.connectionpool

from benchmark_core.http_runner.normalize import (
    _correct_qlever_integer_datatypes, _normalize_graph_response, normalize_sparql_json_result,
)

from benchmark_core.http_runner.protocol import PROTOCOL, serve, stage_clock  # noqa: E402,F401


_QLEVER_SYSTEM = "qlever/default"
_VIRTUOSO_SYSTEM = "virtuoso/default"
_VIRTUOSO_DEFAULT_GRAPH = "http://example.com/graph"
_SELECT_TYPES = {"application/sparql-results+json", "application/json"}


def _count_ntriples(body: bytes) -> int:
    return sum(
        1 for line in body.split(b"\n")
        if line.strip() and not line.strip().startswith(b"#")
    )


class _QuickAckSocket(socket.socket):
    """Re-arm TCP_QUICKACK after every receive.

    Some servers (QLever 0.6) write a chunked response in several small
    segments with Nagle enabled; with Linux delayed ACKs a reused keep-alive
    connection then stalls about 40 ms per response. Acknowledging at once
    removes that client-side artifact uniformly for every HTTP system.
    """

    def _rearm(self) -> None:
        try:
            self.setsockopt(socket.IPPROTO_TCP, socket.TCP_QUICKACK, 1)
        except OSError:
            pass

    def recv(self, *args, **kwargs):
        data = super().recv(*args, **kwargs)
        self._rearm()
        return data

    def recv_into(self, *args, **kwargs):
        count = super().recv_into(*args, **kwargs)
        self._rearm()
        return count


class _QuickAckConnection(urllib3.connection.HTTPConnection):
    def _new_conn(self):
        sock = super()._new_conn()
        return _QuickAckSocket(sock.family, sock.type, sock.proto, fileno=sock.detach())


class _QuickAckPool(urllib3.connectionpool.HTTPConnectionPool):
    ConnectionCls = _QuickAckConnection


def quickack_session(enabled: bool = True) -> requests.Session:
    """Return a keep-alive session whose sockets acknowledge immediately."""
    session = requests.Session()
    if not enabled:
        return session
    adapter = requests.adapters.HTTPAdapter()
    adapter.poolmanager.pool_classes_by_scheme = {
        **adapter.poolmanager.pool_classes_by_scheme, "http": _QuickAckPool,
    }
    session.mount("http://", adapter)
    return session


def direct_endpoint(endpoint: str, container: str | None) -> str:
    """Address the container directly instead of through docker-proxy.

    Docker publishes ports through a userland proxy for localhost, which
    adds a second TCP connection (and its own delayed-ACK stalls) to every
    request. The container's network address and internal port reach the
    same server without that hop.
    """
    if not container:
        return endpoint
    parsed = urllib.parse.urlsplit(endpoint)
    result = subprocess.run(
        ["docker", "container", "inspect", "--format", "{{json .NetworkSettings}}", container],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"cannot inspect server container {container}: {result.stderr.strip()}")
    settings = json.loads(result.stdout)
    host_port = str(parsed.port or 80)
    container_port = None
    for key, bindings in (settings.get("Ports") or {}).items():
        if any(str(binding.get("HostPort")) == host_port for binding in bindings or ()):
            container_port = key.split("/", 1)[0]
    addresses = [network.get("IPAddress") for network in (settings.get("Networks") or {}).values()
                 if network.get("IPAddress")]
    if container_port is None or not addresses:
        raise RuntimeError(f"cannot resolve direct address of {container} for {endpoint}")
    return urllib.parse.urlunsplit(
        (parsed.scheme, f"{addresses[0]}:{container_port}", parsed.path, parsed.query, "")
    )


def make_handlers(config: dict, session):
    """Return the timed ``execute`` and untimed ``finish`` request handlers."""
    endpoint = config["endpoint"]
    system = config.get("system")
    request_max_rows = config.get("request_max_rows")

    def execute(request):
        result_type = request["result_type"]
        graph = result_type in {"construct", "describe"}
        if graph:
            accept = ("application/n-triples" if request["mode"] == "count"
                      else "application/n-triples, text/turtle;q=0.9")
        else:
            accept = "application/sparql-results+json"
        data = {"query": request["query"]}
        if request_max_rows is not None:
            data["maxrows"] = str(request_max_rows)
        if system == _VIRTUOSO_SYSTEM:
            data["default-graph-uri"] = _VIRTUOSO_DEFAULT_GRAPH
        started = stage_clock()
        response = session.post(endpoint, data=data, headers={"Accept": accept},
                                stream=True)
        headers = stage_clock()
        body = response.content
        consumed = stage_clock()
        if response.status_code >= 400:
            raise RuntimeError(
                f"HTTP {response.status_code}: "
                + body[:300].decode("utf-8", errors="replace")
            )
        return (response, body, result_type), {
            "request_until_response_headers": headers - started,
            "response_body": consumed - headers,
        }

    def finish(request, state):
        response, body, result_type = state
        content_type = response.headers.get("Content-Type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        metadata = {
            "http_status": response.status_code,
            "response_bytes": len(body),
            "response_media_type": media_type,
            "http_version": getattr(getattr(response, "raw", None), "version", None),
            "request_max_rows": request_max_rows,
            "result_cap_requested": request_max_rows is not None,
            "http_transport": config.get("transport", {}),
        }
        if request["mode"] == "count":
            if result_type == "ask":
                value = json.loads(body).get("boolean")
                if not isinstance(value, bool):
                    raise ValueError("SPARQL ASK boolean must be true or false")
                count = int(value)
            elif result_type == "select":
                if media_type not in _SELECT_TYPES:
                    raise ValueError(f"Unsupported SPARQL SELECT response type: {media_type!r}")
                bindings = json.loads(body)["results"]["bindings"]
                if not isinstance(bindings, list):
                    raise ValueError("SPARQL SELECT bindings must be an array")
                count = len(bindings)
            else:
                if media_type not in {"application/n-triples", "text/plain"}:
                    raise ValueError(f"Unsupported graph response type: {media_type!r}")
                count = _count_ntriples(body)
            return {"result_count": count, "metadata": metadata}
        if media_type in _SELECT_TYPES:
            document = json.loads(body)
            if system == _QLEVER_SYSTEM:
                document = _correct_qlever_integer_datatypes(document)
            normalized = normalize_sparql_json_result(document, request["query"])
        else:
            normalized = _normalize_graph_response(body, media_type)
        normalized.pop("normalized_result", None)
        return {"normalized": normalized, "metadata": metadata}

    return execute, finish


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("one JSON configuration argument is required")
    config = json.loads(sys.argv[1])
    published = config["endpoint"]
    quickack = config.get("tcp_quickack", True)
    if config.get("direct", True):
        config["endpoint"] = direct_endpoint(published, config.get("container"))
    config["transport"] = {"published_endpoint": published,
                           "endpoint": config["endpoint"],
                           "bypasses_docker_proxy": config["endpoint"] != published,
                           "tcp_quickack": quickack, "keep_alive": True}
    session = quickack_session(quickack)
    execute, finish = make_handlers(config, session)
    try:
        serve({"worker": "sparql-http", "endpoint": published}, execute, finish)
    finally:
        session.close()


if __name__ == "__main__":
    main()

# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import logging
import threading
import time
import typing
from dataclasses import dataclass
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Iterable

import requests

from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
from opentelemetry.proto.common.v1 import common_pb2
from opentelemetry.proto.trace.v1 import trace_pb2
from pants.backend.observability.opentelemetry.subsystem import TracingExporterId
from pants.testutil.pants_integration_test import run_pants, setup_tmpdir

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecordedRequest:
    method: str
    path: str
    body: bytes


class _RequestRecorder(BaseHTTPRequestHandler):
    def __init__(self, *args, requests: list[RecordedRequest], **kwargs) -> None:
        self.requests = requests
        super().__init__(*args, **kwargs)

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)

        received_request = RecordedRequest(method=self.command, path=self.path, body=body)
        self.requests.append(received_request)

        self.send_response(200)
        self.end_headers()


def _wait_for_server_availability(port: int, *, num_attempts: int = 4) -> None:
    url = f"http://127.0.0.1:{port}/"
    while num_attempts > 0:
        try:
            r = requests.get(url)
            if r.status_code == 200:
                break
        except requests.exceptions.ConnectionError:
            pass

        num_attempts -= 1
        time.sleep(0.15)

    if num_attempts <= 0:
        raise Exception("HTTP server did not startup.")


def _get_span_attr(span: trace_pb2.Span, key: str) -> common_pb2.KeyValue | None:
    for attr in span.attributes:
        if attr.key == key:
            return typing.cast(common_pb2.KeyValue, attr)
    return None


def _assert_trace_requests(requests: Iterable[trace_service_pb2.ExportTraceServiceRequest]) -> None:
    root_span: trace_pb2.Span | None = None
    for request in requests:
        for resource_span in request.resource_spans:

            def _get_resouce_span_attr(key: str) -> common_pb2.KeyValue | None:
                for attr in resource_span.resource.attributes:
                    if attr.key == key:
                        return typing.cast(common_pb2.KeyValue, attr)
                return None

            service_name_attr = _get_resouce_span_attr("service.name")
            assert service_name_attr is not None, "Missing service.name attribute in resource span."
            assert service_name_attr.value.string_value == "pantsbuild"

            for scope_span in resource_span.scope_spans:
                for span in scope_span.spans:
                    if not span.parent_span_id:
                        assert root_span is None, "Found multiple candidate root spans."
                        root_span = span

                    workunit_level_attr = _get_span_attr(span, "pantsbuild.workunit.level")
                    assert workunit_level_attr is not None, (
                        "Missing workunit.level attribute in span."
                    )

                    workunit_span_id_attr = _get_span_attr(span, "pantsbuild.workunit.span_id")
                    assert workunit_span_id_attr is not None, (
                        "Missing workunit.span_id attribute in span."
                    )

    assert root_span is not None, "No root span found."
    assert (
        root_span.links[0].trace_id
        == b"\xaa\xaa\xaa\xaa\xaa\xaa\xaa\xaa\xaa\xaa\xaa\xaa\xaa\xaa\xaa\xaa"
    )
    assert root_span.links[0].span_id == b"\xbb\xbb\xbb\xbb\xbb\xbb\xbb\xbb"
    metrics_attr = _get_span_attr(root_span, "pantsbuild.metrics-v0")
    assert metrics_attr is not None, "Missing metrics attribute in root span."


def test_otlp_http_exporter() -> None:
    recorded_requests: list[RecordedRequest] = []
    server_handler = partial(_RequestRecorder, requests=recorded_requests)
    http_server = HTTPServer(("127.0.0.1", 0), server_handler)
    server_port = http_server.server_port

    def _server_thread_func() -> None:
        http_server.serve_forever()

    server_thread = threading.Thread(target=_server_thread_func)
    server_thread.daemon = True
    server_thread.start()

    _wait_for_server_availability(server_port)

    sources = {
        "otlp-http/BUILD": "python_sources(name='src')\n",
        "otlp-http/main.py": "print('Hello World!)\n",
    }
    with setup_tmpdir(sources) as tmpdir:
        result = run_pants(
            [
                "--backend-packages=['pants.backend.python', 'pants.backend.observability.opentelemetry']",
                "--opentelemetry-enabled",
                f"--opentelemetry-exporter={TracingExporterId.OTLP.value}",
                f"--opentelemetry-exporter-endpoint=http://127.0.0.1:{server_port}/v1/traces",
                "list",
                f"{tmpdir}/otlp-http::",
            ],
            extra_env={
                "TRACEPARENT": "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-00",
            },
            stream_output=True,
        )
        result.assert_success()

        # Assert that tracing spans were received over HTTP.
        assert len(recorded_requests) > 0, "No trace requests received!"

        def _convert(body: bytes) -> trace_service_pb2.ExportTraceServiceRequest:
            trace_request = trace_service_pb2.ExportTraceServiceRequest()
            trace_request.ParseFromString(body)
            return trace_request

        _assert_trace_requests([_convert(request.body) for request in recorded_requests])


def test_json_file_exporter() -> None:
    sources = {
        "otel-json/BUILD": "python_sources(name='src')\n",
        "otel-json/main.py": "print('Hello World!)\n",
    }
    with setup_tmpdir(sources) as tmpdir:
        trace_file = Path("dist", "otel-json-trace.jsonl")
        assert not trace_file.exists()

        result = run_pants(
            [
                "--backend-packages=['pants.backend.python', 'pants.backend.observability.opentelemetry']",
                "--opentelemetry-enabled",
                f"--opentelemetry-exporter={TracingExporterId.JSON_FILE.value}",
                "list",
                f"{tmpdir}/otel-json::",
            ],
            extra_env={
                "TRACEPARENT": "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-00",
            },
        )
        result.assert_success()

        # Assert that tracing spans were output.
        traces_content = trace_file.read_text()
        root_span_json: dict[Any, Any] | None = None
        for trace_line in traces_content.splitlines():
            trace_json = json.loads(trace_line)
            assert len(trace_json["context"]["trace_id"]) > 0
            assert len(trace_json["context"]["span_id"]) > 0
            assert trace_json["resource"]["attributes"]["service.name"] == "pantsbuild"
            if trace_json.get("parent_id") is None:
                assert root_span_json is None, "Found multiple candidate root spans."
                root_span_json = trace_json

        assert root_span_json is not None, "No root span found."
        assert (
            root_span_json["links"][0]["context"]["trace_id"]
            == "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )


def test_resource_attributes() -> None:
    """Test that OTEL_RESOURCE_ATTRIBUTES are properly included in
    telemetry."""
    trace_file = Path("dist", "otel-json-trace-resource-attributes.jsonl")
    assert not trace_file.exists()

    result = run_pants(
        [
            "--backend-packages=['pants.backend.python', 'pants.backend.observability.opentelemetry']",
            "--opentelemetry-enabled",
            f"--opentelemetry-exporter={TracingExporterId.JSON_FILE.value}",
            "--opentelemetry-json-file=dist/otel-json-trace-resource-attributes.jsonl",
            "version",
        ],
        extra_env={
            "OTEL_RESOURCE_ATTRIBUTES": "user.name=testuser,team=ml-platform,env=test",
        },
    )
    result.assert_success()

    # Assert that tracing spans were output with resource attributes
    traces_content = trace_file.read_text()
    for trace_line in traces_content.splitlines():
        trace_json = json.loads(trace_line)
        resource_attrs = trace_json["resource"]["attributes"]

        # Verify standard attributes
        assert resource_attrs["service.name"] == "pantsbuild"
        assert "telemetry.sdk.name" in resource_attrs

        # Verify our custom resource attributes from OTEL_RESOURCE_ATTRIBUTES
        assert resource_attrs["user.name"] == "testuser"
        assert resource_attrs["team"] == "ml-platform"
        assert resource_attrs["env"] == "test"

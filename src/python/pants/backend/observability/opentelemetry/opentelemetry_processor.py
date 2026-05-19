# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import datetime
import json
import logging
import os
import typing
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter as HttpOTLPSpanExporter,
)
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider, sampling
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import Link, TraceFlags
from opentelemetry.trace.span import (
    NonRecordingSpan,
    Span,
    SpanContext,
    format_span_id,
    format_trace_id,
)
from opentelemetry.trace.status import StatusCode
from pants.backend.observability.opentelemetry.opentelemetry_config import OtlpParameters
from pants.backend.observability.opentelemetry.processor import (
    IncompleteWorkunit,
    Level,
    Processor,
    ProcessorContext,
    Workunit,
)
from pants.backend.observability.opentelemetry.subsystem import TracingExporterId
from pants.util.frozendict import FrozenDict

logger = logging.getLogger(__name__)

_UNIX_EPOCH = datetime.datetime(year=1970, month=1, day=1, tzinfo=datetime.UTC)


@contextmanager
def _temp_env_var(key: str, value: str | None):
    """Temporarily set an environment variable, restoring the original value
    afterward."""
    old_value = os.environ.get(key)
    try:
        if value is not None:
            os.environ[key] = value
        yield
    finally:
        if old_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old_value


def _datetime_to_otel_timestamp(d: datetime.datetime) -> int:
    """OTEL times are nanoseconds since the Unix epoch."""
    duration_since_epoch = d - _UNIX_EPOCH
    nanoseconds = duration_since_epoch.days * 24 * 60 * 60 * 1000000000
    nanoseconds += duration_since_epoch.seconds * 1000000000
    nanoseconds += duration_since_epoch.microseconds * 1000
    return nanoseconds


class JsonFileSpanExporter(SpanExporter):
    def __init__(self, file: TextIO) -> None:
        self._file = file

    def export(self, spans: typing.Sequence[ReadableSpan]) -> SpanExportResult:
        for span in spans:
            self._file.write(span.to_json(indent=0).replace("\n", " ") + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        self._file.close()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        self._file.flush()
        return True


def get_processor(
    span_exporter_name: TracingExporterId,
    otlp_parameters: OtlpParameters,
    build_root: Path,
    traceparent_env_var: str | None,
    otel_resource_attributes: str | None,
    json_file: str | None,
    trace_link_template: str | None,
) -> Processor:
    logger.debug(f"OTEL: get_processor: otlp_parameters={otlp_parameters}; build_root={build_root}")

    # Temporarily set OTEL_RESOURCE_ATTRIBUTES so Resource.create() can parse it
    with _temp_env_var("OTEL_RESOURCE_ATTRIBUTES", otel_resource_attributes):
        # Resource.create() will automatically merge OTEL_RESOURCE_ATTRIBUTES from os.environ
        resource = Resource.create(
            attributes={
                SERVICE_NAME: "pantsbuild",
            }
        )
    tracer_provider = TracerProvider(
        sampler=sampling.ALWAYS_ON, resource=resource, shutdown_on_exit=False
    )
    tracer = tracer_provider.get_tracer(__name__)

    span_exporter: SpanExporter
    if span_exporter_name == TracingExporterId.OTLP:
        span_exporter = HttpOTLPSpanExporter(
            endpoint=otlp_parameters.resolve_traces_endpoint(),
            certificate_file=otlp_parameters.certificate_file,
            client_key_file=otlp_parameters.client_key_file,
            client_certificate_file=otlp_parameters.client_certificate_file,
            headers=dict(otlp_parameters.headers) if otlp_parameters.headers else None,
            timeout=otlp_parameters.timeout,
            compression=Compression(otlp_parameters.compression),
        )
    elif span_exporter_name == TracingExporterId.JSON_FILE:
        json_file_path_str = json_file
        if not json_file_path_str:
            raise ValueError(
                f"`--opentelemetry-exporter` is set to `{TracingExporterId.JSON_FILE}` "
                "but the `--opentelemetry-json-file` option is not set."
            )
        json_file_path = build_root / json_file_path_str
        json_file_path.parent.mkdir(parents=True, exist_ok=True)
        span_exporter = JsonFileSpanExporter(open(json_file_path, "w"))
        logger.debug(f"Enabling OpenTelemetry JSON file span exporter: path={json_file_path}")
    else:
        raise AssertionError(f"Unknown span exporter type: {span_exporter_name.value}")

    span_processor = BatchSpanProcessor(
        span_exporter=span_exporter,
        max_queue_size=512,
        max_export_batch_size=100,
        export_timeout_millis=5000,
        schedule_delay_millis=30000,
    )
    tracer_provider.add_span_processor(span_processor)

    otel_processor = OpenTelemetryProcessor(
        tracer=tracer,
        span_processor=span_processor,
        traceparent_env_var=traceparent_env_var,
        tracer_provider=tracer_provider,
        trace_link_template=trace_link_template,
    )

    return otel_processor


class DummySpan(NonRecordingSpan):
    """A dummy Span used in the thread context so we can trick OpenTelemetry as
    to what the parent span ID is.

    Sets `is_recording` to True.
    """

    def is_recording(self) -> bool:
        return True

    def __repr__(self) -> str:
        return f"DummySpan({self._context!r})"


def _parse_id(id_hex: str, id_hex_chars_len: int) -> int:
    # Remove any potential formatting like hyphens or "0x" prefix
    id_hex = id_hex.replace("-", "").replace("0x", "").lower()

    # Check if the length is correct for the given ID type.
    if len(id_hex) != id_hex_chars_len:
        raise ValueError(
            f"Invalid ID length: expected {id_hex_chars_len} hex chars, got {len(id_hex)} instead."
        )

    # Convert hex string to integer
    return int(id_hex, 16)


def _parse_traceparent(value: str) -> tuple[int, int] | None:
    parts = value.split("-")
    if len(parts) < 3:
        return None

    try:
        trace_id = _parse_id(parts[1], 32)
    except ValueError as e:
        logger.warning(f"Ignoring TRACEPARENT due to failure to parse trace ID `{parts[1]}`: {e}")
        return None

    try:
        span_id = _parse_id(parts[2], 16)
    except ValueError as e:
        logger.warning(f"Ignoring TRACEPARENT due to failure to parse span ID `{parts[2]}`: {e}")
        return None

    return trace_id, span_id


class _Encoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, FrozenDict):
            return o._data
        return super().default(o)


class OpenTelemetryProcessor(Processor):
    def __init__(
        self,
        tracer: trace.Tracer,
        span_processor: SpanProcessor,
        traceparent_env_var: str | None,
        tracer_provider: TracerProvider,
        trace_link_template: str | None,
    ) -> None:
        self._tracer = tracer
        self._tracer_provider = tracer_provider
        self._trace_id: int | None = None
        self._workunit_span_id_to_otel_span_id: dict[str, int] = {}
        self._otel_spans: dict[int, trace.Span] = {}
        self._span_processor = span_processor
        self._span_count: int = 0
        self._counters: dict[str, int] = {}
        self._trace_link_template: str | None = trace_link_template
        self._initialized: bool = False
        self._shutdown: bool = False

        self._parent_trace_id: int | None = None
        self._parent_span_id: int | None = None
        if traceparent_env_var is not None:
            ids = _parse_traceparent(traceparent_env_var)
            if ids is not None:
                self._parent_trace_id = ids[0]
                self._parent_span_id = ids[1]

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("OTEL: processor already initialized")
        logger.debug("OpenTelemetryProcessor.initialize called")
        self._initialized = True

    def _increment_counter(self, name: str, delta: int = 1) -> None:
        if name not in self._counters:
            self._counters[name] = 0
        self._counters[name] += delta

    def _log_trace_link(
        self,
        root_span_id: int,
        root_span_start_time: datetime.datetime,
        root_span_end_time: datetime.datetime,
    ) -> None:
        template = self._trace_link_template
        if not template:
            return

        replacements = {
            "trace_id": format_trace_id(self._trace_id) if self._trace_id else "UNKNOWN",
            "root_span_id": format_span_id(root_span_id),
            "trace_start_ms": str(int(root_span_start_time.timestamp() * 1000)),
            "trace_end_ms": str(int(root_span_end_time.timestamp() * 1000)),
        }
        trace_link = template.format(**replacements)
        logger.info(f"OpenTelemetry trace link: {trace_link}")

    def _construct_otel_span(
        self,
        *,
        workunit_span_id: str,
        workunit_parent_span_id: str | None,
        name: str,
        start_time: datetime.datetime,
    ) -> tuple[Span, int]:
        """Construct an OpenTelemetry span.

        Shared between `start_workunit` and `complete_workunit` since
        some spans may arrive already-completed.
        """
        assert workunit_span_id not in self._workunit_span_id_to_otel_span_id

        otel_context = Context()
        if workunit_parent_span_id:
            # OpenTelemetry pulls the parent span ID from the span set as "current" in the supplied context.
            assert self._trace_id is not None
            otel_parent_span_context = SpanContext(
                trace_id=self._trace_id,
                span_id=self._workunit_span_id_to_otel_span_id[workunit_parent_span_id],
                is_remote=False,
            )
            otel_context = trace.set_span_in_context(
                DummySpan(otel_parent_span_context), context=otel_context
            )

        # Record a "link" on the root span to any parent trace set via TRACEPARENT.
        links: list[Link] = []
        if not workunit_parent_span_id and self._parent_trace_id and self._parent_span_id:
            parent_trace_id_context = SpanContext(
                trace_id=self._parent_trace_id,
                span_id=self._parent_span_id,
                is_remote=True,
                trace_flags=TraceFlags(TraceFlags.SAMPLED),
            )
            links.append(Link(context=parent_trace_id_context))

        otel_span = self._tracer.start_span(
            name=name,
            context=otel_context,
            start_time=_datetime_to_otel_timestamp(start_time),
            record_exception=False,
            set_status_on_exception=False,
            links=links,
        )

        # Record the span ID chosen by the tracer for this span.
        otel_span_context = otel_span.get_span_context()
        otel_span_id = otel_span_context.span_id
        self._workunit_span_id_to_otel_span_id[workunit_span_id] = otel_span_id
        self._otel_spans[otel_span_id] = otel_span

        # Record the trace ID generated the first time any span is constructed.
        if self._trace_id is None:
            self._trace_id = otel_span.get_span_context().trace_id

        return otel_span, otel_span_id

    def _apply_incomplete_workunit_attributes(
        self, workunit: IncompleteWorkunit, otel_span: Span
    ) -> None:
        otel_span.set_attribute("pantsbuild.workunit.span_id", workunit.span_id)
        otel_span.set_attribute("pantsbuild.workunit.parent_span_ids", workunit.parent_ids)

        otel_span.set_attribute("pantsbuild.workunit.level", workunit.level.value.upper())
        if workunit.level == Level.ERROR:
            otel_span.set_status(StatusCode.ERROR)

    def _apply_workunit_attributes(self, workunit: Workunit, otel_span: Span) -> None:
        self._apply_incomplete_workunit_attributes(workunit=workunit, otel_span=otel_span)

        for key, value in workunit.metadata.items():
            if isinstance(
                value,
                (
                    str,
                    bool,
                    int,
                    float,
                ),
            ):
                otel_span.set_attribute(f"pantsbuild.workunit.metadata.{key}", value)

    def start_workunit(self, workunit: IncompleteWorkunit, *, context: ProcessorContext) -> None:
        if not self._initialized:
            raise RuntimeError("OTEL: start_workunit called on uninitialized processor")
        if self._shutdown:
            raise RuntimeError("OTEL: start_workunit called on shutdown processor")
        if workunit.span_id in self._workunit_span_id_to_otel_span_id:
            self._increment_counter("multiple_start_workunit_for_span_id")
            return

        otel_span, _ = self._construct_otel_span(
            workunit_span_id=workunit.span_id,
            workunit_parent_span_id=workunit.primary_parent_id,
            name=workunit.name,
            start_time=workunit.start_time,
        )

        self._apply_incomplete_workunit_attributes(workunit=workunit, otel_span=otel_span)

    def complete_workunit(self, workunit: Workunit, *, context: ProcessorContext) -> None:
        if not self._initialized:
            raise RuntimeError("OTEL: complete_workunit called on uninitialized processor")
        if self._shutdown:
            raise RuntimeError("OTEL: complete_workunit called on shutdown processor")
        otel_span: Span
        otel_span_id: int
        if workunit.span_id in self._workunit_span_id_to_otel_span_id:
            otel_span_id = self._workunit_span_id_to_otel_span_id[workunit.span_id]
            otel_span = self._otel_spans[otel_span_id]
        else:
            otel_span, otel_span_id = self._construct_otel_span(
                workunit_span_id=workunit.span_id,
                workunit_parent_span_id=workunit.primary_parent_id,
                name=workunit.name,
                start_time=workunit.start_time,
            )

        self._apply_workunit_attributes(workunit=workunit, otel_span=otel_span)

        # Set the metrics for the session as an attribute of the root span.
        if not workunit.primary_parent_id:
            metrics = context.get_metrics()
            otel_span.set_attribute(
                "pantsbuild.metrics-v0", json.dumps(metrics, sort_keys=True, cls=_Encoder)
            )

        otel_span.end(end_time=_datetime_to_otel_timestamp(workunit.end_time))

        del self._otel_spans[otel_span_id]
        self._span_count += 1

        # If this the root span, then log any vendor trace link as a side effect.
        if not workunit.primary_parent_id and self._trace_link_template:
            self._log_trace_link(
                root_span_id=otel_span_id,
                root_span_start_time=workunit.start_time,
                root_span_end_time=workunit.end_time,
            )

    def finish(
        self, timeout: datetime.timedelta | None = None, *, context: ProcessorContext
    ) -> None:
        if self._shutdown:
            raise RuntimeError("OTEL: finish called on shutdown processor")
        logger.debug("OpenTelemetryProcessor requested to finish workunit transmission.")
        logger.debug(f"OpenTelemetry processing counters: {self._counters.items()}")
        if len(self._otel_spans) > 0:
            logger.warning(
                "Multiple OpenTelemetry spans have not been submitted as completed to the library."
            )
        timeout_millis: int = int(timeout.total_seconds() * 1000.0) if timeout is not None else 2000
        self._span_processor.force_flush(timeout_millis)
        self._span_processor.shutdown()
        self._tracer_provider.shutdown()
        self._shutdown = True

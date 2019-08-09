# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import subprocess
import time

import requests
from py_zipkin import Encoding, get_default_tracer, Kind
from py_zipkin.encoding import Span
from py_zipkin.exception import ZipkinError
from py_zipkin.logging_helper import ZipkinLoggingContext, LOGGING_END_KEY
from py_zipkin.thrift import copy_endpoint_with_new_service_name
from py_zipkin.transport import BaseTransportHandler
from py_zipkin.util import generate_random_64bit_string
from py_zipkin.zipkin import ZipkinAttrs, create_attrs_for_span

from pants.base.workunit import WorkUnitLabel
from pants.reporting.reporter import Reporter
from pants.util.dirutil import safe_mkdir


logger = logging.getLogger(__name__)

NANOSECONDS_PER_SECOND = 1000000000.0


class HTTPTransportHandler(BaseTransportHandler):
  def __init__(self, endpoint):
    self.endpoint = endpoint

  def get_max_payload_bytes(self):
    return None

  def send(self, file_path):
    try:
      command = 'curl -v -X POST -H "Content-Type: application/json" --data @{} {}'.format(file_path, self.endpoint)
      args = command.split(' ')
      p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

      logger.debug("pid of child process that sends spans to Zipkin server: {}".format(p.pid))

    except Exception as err:
      logger.error("Failed to post the payload to zipkin server. Error {}".format(err))


class ZipkinReporter(Reporter):
  """
    Reporter that implements Zipkin tracing.
  """

  def __init__(self, run_tracker, settings, endpoint, trace_id, parent_id, sample_rate,
                service_name_prefix, max_span_batch_size):
    """
    When trace_id and parent_id are set a Zipkin trace will be created with given trace_id
    and parent_id. If trace_id and parent_id are set to None, a trace_id will be randomly
    generated for a Zipkin trace. trace-id and parent-id must both either be set or not set.

    :param RunTracker run_tracker: Tracks and times the execution of a pants run.
    :param Settings settings: Generic reporting settings.
    :param string endpoint: The full HTTP URL of a zipkin server to which traces should be posted.
    :param string trace_id: The overall 64 or 128-bit ID of the trace. May be None.
    :param string parent_id: The 64-bit ID for a parent span that invokes Pants. May be None.
    :param float sample_rate: Rate at which to sample Zipkin traces. Value 0.0 - 100.0.
    :param string service_name_prefix: Prefix for service name.
    :param int max_span_batch_size: Spans in a trace are sent in batches,
           max_span_batch_size defines max size of one batch.

    """
    super().__init__(run_tracker, settings)
    # Create a transport handler
    self.handler = HTTPTransportHandler(endpoint)
    self.trace_id = trace_id
    self.parent_id = parent_id
    self.sample_rate = float(sample_rate)
    self.endpoint = endpoint
    self.tracer = get_default_tracer()
    self.run_tracker = run_tracker
    self.service_name_prefix = service_name_prefix
    self.max_span_batch_size = max_span_batch_size

  def start_workunit(self, workunit):
    """Implementation of Reporter callback."""
    if workunit.has_label(WorkUnitLabel.GOAL):
      service_name = "goal"
    elif workunit.has_label(WorkUnitLabel.TASK):
      service_name = "task"
    else:
      service_name = "workunit"

    # Set local_tracer. Tracer stores spans and span's zipkin_attrs.
    # If start_workunit is called from the root thread then local_tracer is the same as self.tracer.
    # If start_workunit is called from a new thread then local_tracer will have an empty span
    # storage and stack.
    local_tracer = get_default_tracer()

    # Check if it is the first workunit
    first_span = self.run_tracker.is_main_root_workunit(workunit)
    if first_span:
      # If trace_id and parent_id are given as flags create zipkin_attrs
      if self.trace_id is not None and self.parent_id is not None:
        zipkin_attrs = ZipkinAttrs(
          # trace_id and parent_id are passed to Pants by another process that collects
          # Zipkin trace
          trace_id=self.trace_id,
          span_id=generate_random_64bit_string(),
          parent_span_id=self.parent_id,
          flags='0', # flags: stores flags header. Currently unused
          is_sampled=True,
        )
      else:
        zipkin_attrs = create_attrs_for_span(
          # trace_id is the same as run_uuid that is created in run_tracker and is the part of
          # pants_run id
          trace_id=self.trace_id,
          sample_rate=self.sample_rate, # Value between 0.0 and 100.0
        )
        # TODO delete this line when parent_id will be passed in v2 engine:
        #  - with ExecutionRequest when Nodes from v2 engine are called by a workunit;
        #  - when a v2 engine Node is called by another v2 engine Node.
        self.parent_id = zipkin_attrs.span_id

      span = local_tracer.zipkin_span(
        service_name=self.service_name_prefix.format("main"),
        span_name=workunit.name,
        transport_handler=self.handler,
        encoding=Encoding.V1_JSON,
        zipkin_attrs=zipkin_attrs,
        max_span_batch_size=self.max_span_batch_size,
      )
    else:
      # If start_workunit is called from a new thread local_tracer doesn't have zipkin attributes.
      # Parent's attributes need to be added to the local_tracer zipkin_attrs storage.
      if not local_tracer.get_zipkin_attrs():
        parent_attrs = workunit.parent.zipkin_span.zipkin_attrs
        local_tracer.push_zipkin_attrs(parent_attrs)
        local_tracer.set_transport_configured(configured=True)
      span = local_tracer.zipkin_span(
        service_name=self.service_name_prefix.format(service_name),
        span_name=workunit.name,
      )
    # For all spans except the first span zipkin_attrs for span are created at this point
    span.start()
    if workunit.name == 'background' and self.run_tracker.is_main_root_workunit(workunit.parent):
      span.zipkin_attrs = span.zipkin_attrs._replace(
        parent_span_id=workunit.parent.zipkin_span.zipkin_attrs.span_id
      )
      span.service_name = self.service_name_prefix.format("background")

    # Goals and tasks save their start time at the beginning of their run.
    # This start time is passed to workunit, because the workunit may be created much later.
    span.start_timestamp = workunit.start_time
    if first_span and span.zipkin_attrs.is_sampled:
      span.logging_context.start_timestamp = workunit.start_time
      if span.encoding in (Encoding.V1_JSON, Encoding.V2_JSON):
        span.logging_context.emit_spans = emit_spans.__get__(span.logging_context, ZipkinLoggingContext)
      span.logging_context.zipkin_spans_dir = os.path.join(self.run_tracker.run_info_dir, 'zipkin')
      span.logging_context.encoding = span.encoding
    workunit.zipkin_span = span

  def end_workunit(self, workunit):
    """Implementation of Reporter callback."""
    span = workunit.zipkin_span
    span.stop()
    span_tracer = span.get_tracer()
    if span_tracer is not self.tracer:
      for span in span_tracer.get_spans():
        self.tracer.add_span(span)
      span_tracer.clear()

  def close(self):
    """End the report."""
    endpoint = self.endpoint.replace("/api/v1/spans", "")

    logger.debug("Zipkin trace may be located at this URL {}/traces/{}".format(endpoint, self.trace_id))

  def bulk_record_workunits(self, engine_workunits):
    """A collection of workunits from v2 engine part"""
    for workunit in engine_workunits:
      start_timestamp = from_secs_and_nanos_to_float(
        workunit['start_secs'],
        workunit['start_nanos']
      )
      duration = from_secs_and_nanos_to_float(
        workunit['duration_secs'],
        workunit['duration_nanos']
      )

      local_tracer = get_default_tracer()

      span = local_tracer.zipkin_span(
        service_name=self.service_name_prefix.format("rule"),
        span_name=workunit['name'],
        duration=duration,
      )
      span.start()
      span.zipkin_attrs = ZipkinAttrs(
        trace_id=self.trace_id,
        span_id=workunit['span_id'],
        # TODO change it when we properly pass parent_id to the v2 engine Nodes
        # TODO Pass parent_id with ExecutionRequest when v2 engine is called by a workunit
        # TODO pass parent_id when v2 engine Node is called by another v2 engine Node
        parent_span_id=workunit.get("parent_id", self.parent_id),
        flags='0', # flags: stores flags header. Currently unused
        is_sampled=True,
      )
      span.start_timestamp = start_timestamp
      span.stop()


def from_secs_and_nanos_to_float(secs, nanos):
  return secs + ( nanos / NANOSECONDS_PER_SECOND )


def emit_spans(self):

  if not self.zipkin_attrs.is_sampled:
    self._get_tracer().clear()
    return

  end_timestamp = time.time()

  annotations = {}
  if self.add_logging_annotation:
    annotations[LOGGING_END_KEY] = time.time()

  last_span = Span(
    trace_id=self.zipkin_attrs.trace_id,
    name=self.span_name,
    parent_id=self.zipkin_attrs.parent_span_id,
    span_id=self.zipkin_attrs.span_id,
    kind=Kind.CLIENT if self.client_context else Kind.SERVER,
    timestamp=self.start_timestamp,
    duration=end_timestamp - self.start_timestamp,
    local_endpoint=self.endpoint,
    remote_endpoint=self.remote_endpoint,
    shared=not self.report_root_timestamp,
    annotations=annotations,
    tags=self.tags,
  )
  self._get_tracer().add_span(last_span)

  safe_mkdir(self.zipkin_spans_dir)

  spans_sender = ZipkinSpanSender(self.transport_handler,
    self.max_span_batch_size,
    self.encoder,
    self.zipkin_spans_dir,
    self.encoding)

  with spans_sender:
    if os.path.exists(self.zipkin_spans_dir):
      for span in self._get_tracer().get_spans():
        span.local_endpoint = copy_endpoint_with_new_service_name(
          self.endpoint,
          span.local_endpoint.service_name,
        )

        spans_sender.add_span(span)

  self._get_tracer().clear()


class ZipkinSpanSender(object):

  MAX_BATCH_SIZE = 100

  def __init__(self, transport_handler, max_span_batch_size, encoder, zipkin_spans_dir, encoding):
    self.transport_handler = transport_handler
    self.max_span_batch_size = max_span_batch_size or self.MAX_BATCH_SIZE
    self.encoder = encoder
    self.zipkin_spans_dir = zipkin_spans_dir
    self.file_count = 0
    self.encoding = encoding

    if isinstance(self.transport_handler, BaseTransportHandler):
      self.max_payload_bytes = self.transport_handler.get_max_payload_bytes()
    else:
      self.max_payload_bytes = None

  def __enter__(self):
    self._reset_queue()
    return self

  def __exit__(self, _exc_type, _exc_value, _exc_traceback):
    if any((_exc_type, _exc_value, _exc_traceback)):
      filename = os.path.split(_exc_traceback.tb_frame.f_code.co_filename)[1]
      error = '({0}:{1}) {2}: {3}'.format(
        filename,
        _exc_traceback.tb_lineno,
        _exc_type.__name__,
        _exc_value,
      )
      raise ZipkinError(error)
    else:
      self.flush()

  def _reset_queue(self):
    self.queue = []
    self.current_size = 0
    self.file_count += 1

  def add_span(self, span):
    encoded_span = self.encoder.encode_span(span)

    # If we've already reached the max batch size or the new span doesn't
    # fit in max_payload_bytes, send what we've collected until now and
    # start a new batch.
    is_over_size_limit = (
      self.max_payload_bytes is not None and
      not self.encoder.fits(
        current_count=len(self.queue),
        current_size=self.current_size,
        max_size=self.max_payload_bytes,
        new_span=encoded_span,
      )
    )
    is_over_portion_limit = len(self.queue) >= self.max_span_batch_size
    if is_over_size_limit or is_over_portion_limit:
      self.flush()

    self.queue.append(encoded_span)
    self.current_size += len(encoded_span)

  def flush(self):
    if self.transport_handler and len(self.queue) > 0:
      file_path = os.path.join(
        self.zipkin_spans_dir, 'spans-{}-{}'.format(self.file_count, self.encoding)
      )
      self.save_json_spans_to_file(file_path)
      self.transport_handler(file_path)
    self._reset_queue()

  def save_json_spans_to_file(self, file_path):
    with open(file_path, 'a') as f:
      f.write('[')
      f.write(','.join(self.queue))
      f.write(']')

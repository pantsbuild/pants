# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging

import requests
from py_zipkin import Encoding, get_default_tracer
from py_zipkin.transport import BaseTransportHandler
from py_zipkin.util import generate_random_64bit_string
from py_zipkin.zipkin import ZipkinAttrs, create_attrs_for_span

from pants.base.workunit import WorkUnitLabel
from pants.reporting.reporter import Reporter


logger = logging.getLogger(__name__)


class HTTPTransportHandler(BaseTransportHandler):
  def __init__(self, endpoint):
    self.endpoint = endpoint

  def get_max_payload_bytes(self):
    return None

  def send(self, payload):
    try:
      requests.post(
        self.endpoint,
        data=payload,
        headers={'Content-Type': 'application/x-thrift'},
      )
    except Exception as err:
      logger.error("Failed to post the payload to zipkin server. Error {}".format(err))


class ZipkinReporter(Reporter):
  """
    Reporter that implements Zipkin tracing.
  """

  def __init__(self, run_tracker, settings, endpoint, trace_id, parent_id, sample_rate):
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

  def start_workunit(self, workunit):
    """Implementation of Reporter callback."""
    if workunit.has_label(WorkUnitLabel.GOAL):
      service_name = "pants goal"
    elif workunit.has_label(WorkUnitLabel.TASK):
      service_name = "pants task"
    else:
      service_name = "pants workunit"

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
        service_name=service_name,
        span_name=workunit.name,
        transport_handler=self.handler,
        encoding=Encoding.V1_THRIFT,
        zipkin_attrs=zipkin_attrs,
      )
    else:
      # If start_workunit is called from a new thread local_tracer doesn't have zipkin attributes.
      # Parent's attributes need to be added to the local_tracer zipkin_attrs storage.
      if not local_tracer.get_zipkin_attrs():
        parent_attrs = workunit.parent.zipkin_span.zipkin_attrs
        local_tracer.push_zipkin_attrs(parent_attrs)
        local_tracer.set_transport_configured(configured=True)
      span = local_tracer.zipkin_span(
        service_name=service_name,
        span_name=workunit.name,
      )
    # For all spans except the first span zipkin_attrs for span are created at this point
    span.start()
    if workunit.name == 'background' and self.run_tracker.is_main_root_workunit(workunit.parent):
      span.zipkin_attrs = span.zipkin_attrs._replace(
        parent_span_id=workunit.parent.zipkin_span.zipkin_attrs.span_id
      )
      span.service_name = "pants background workunit"

    # Goals and tasks save their start time at the beginning of their run.
    # This start time is passed to workunit, because the workunit may be created much later.
    span.start_timestamp = workunit.start_time
    if first_span and span.zipkin_attrs.is_sampled:
      span.logging_context.start_timestamp = workunit.start_time
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
      duration = workunit['end_timestamp'] - workunit['start_timestamp']

      local_tracer = get_default_tracer()

      span = local_tracer.zipkin_span(
        service_name="pants",
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
      span.start_timestamp = workunit['start_timestamp']
      span.stop()

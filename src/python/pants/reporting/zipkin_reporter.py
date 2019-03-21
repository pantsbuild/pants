# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

import requests
from py_zipkin import Encoding
from py_zipkin.transport import BaseTransportHandler
from py_zipkin.util import generate_random_64bit_string
from py_zipkin.zipkin import ZipkinAttrs, create_attrs_for_span, zipkin_span

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
    super(ZipkinReporter, self).__init__(run_tracker, settings)
    # We keep track of connection between workunits and spans
    self._workunits_to_spans = {}
    # Create a transport handler
    self.handler = HTTPTransportHandler(endpoint)
    self.trace_id = trace_id
    self.parent_id = parent_id
    self.sample_rate = float(sample_rate)
    self.endpoint = endpoint

  def start_workunit(self, workunit):
    """Implementation of Reporter callback."""
    if workunit.has_label(WorkUnitLabel.GOAL):
      service_name = "pants goal"
    elif workunit.has_label(WorkUnitLabel.TASK):
      service_name = "pants task"
    else:
      service_name = "pants workunit"

    # Check if it is the first workunit
    first_span = not self._workunits_to_spans
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
        zipkin_attrs =  create_attrs_for_span(
          # trace_id is the same as run_uuid that is created in run_tracker and is the part of
          # pants_run id
          trace_id=self.trace_id,
          sample_rate=self.sample_rate, # Value between 0.0 and 100.0
        )
        self.trace_id = zipkin_attrs.trace_id


      span = zipkin_span(
        service_name=service_name,
        span_name=workunit.name,
        transport_handler=self.handler,
        encoding=Encoding.V1_THRIFT,
        zipkin_attrs=zipkin_attrs
      )
    else:
      span = zipkin_span(
        service_name=service_name,
        span_name=workunit.name,
      )
    self._workunits_to_spans[workunit] = span
    span.start()
    # Goals and tasks save their start time at the beginning of their run.
    # This start time is passed to workunit, because the workunit may be created much later.
    span.start_timestamp = workunit.start_time
    if first_span and span.zipkin_attrs.is_sampled:
      span.logging_context.start_timestamp = workunit.start_time

  def end_workunit(self, workunit):
    """Implementation of Reporter callback."""
    if workunit in self._workunits_to_spans:
      span = self._workunits_to_spans.pop(workunit)
      span.stop()

  def close(self):
    """End the report."""
    endpoint = self.endpoint.replace("/api/v1/spans", "")

    logger.debug("Zipkin trace may be located at this URL {}/traces/{}".format(endpoint, self.trace_id))

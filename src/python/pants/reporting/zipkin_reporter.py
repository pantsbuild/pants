# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

import requests
from py_zipkin import Encoding
from py_zipkin.transport import BaseTransportHandler
from py_zipkin.util import generate_random_64bit_string
from py_zipkin.zipkin import ZipkinAttrs, zipkin_span

from pants.base.workunit import WorkUnitLabel
from pants.reporting.reporter import Reporter


log = logging.getLogger(__name__)


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
      log.error("Failed to post the payload to zipkin server. Error {}".format(err))


class ZipkinReporter(Reporter):
  """Reporter that implements Zipkin tracing .
  """

  def __init__(self, run_tracker, settings, endpoint, trace_id, parent_id):
    super(ZipkinReporter, self).__init__(run_tracker, settings)
    # We keep track of connection between workunits and spans
    self._workunits_to_spans = {}
    # Create a transport handler
    self.handler = HTTPTransportHandler(endpoint)
    self.trace_id = trace_id
    self.parent_id = parent_id

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
      # If trace_id and parent_id are given create zipkin_attrs
      if self.trace_id is not None:
        zipkin_attrs = ZipkinAttrs(
          trace_id=self.trace_id,
          span_id=generate_random_64bit_string(),
          parent_span_id=self.parent_id,
          flags='0',
          is_sampled=True,
        )
      else:
        zipkin_attrs = None

      span = zipkin_span(
        service_name=service_name,
        span_name=workunit.name,
        transport_handler=self.handler,
        sample_rate=100.0, # Value between 0.0 and 100.0
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
    if first_span:
      span.logging_context.start_timestamp = workunit.start_time

  def end_workunit(self, workunit):
    """Implementation of Reporter callback."""
    if workunit in self._workunits_to_spans:
      span = self._workunits_to_spans.pop(workunit)
      span.stop()

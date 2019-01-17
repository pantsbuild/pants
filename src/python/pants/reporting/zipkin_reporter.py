# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import requests
from py_zipkin import Encoding
from py_zipkin.transport import BaseTransportHandler
from py_zipkin.zipkin import zipkin_span

from pants.reporting.reporter import Reporter


class HTTPTransportHandler(BaseTransportHandler):
  def __init__(self, endpoint, encoding):
    self.endpoint = endpoint
    self.encoding = encoding

  def get_max_payload_bytes(self):
    return None

  def send(self, payload):
    try:
      requests.post(
        # Twitter endpoint 'https://zipkin.twitter.biz/api/v1/spans',
        # Local endpoint 'http://localhost:9411/api/v1/spans',
        self.endpoint,
        data=payload,
        headers={'Content-Type': 'application/{}'.format(self.encoding)},
      )
    except Exception as err:
      err


class ZipkinReporter(Reporter):
  """Reporter that implements Zipkin tracing .
  """

  def __init__(self, run_tracker, settings, endpoint, encoding):
    super(ZipkinReporter, self).__init__(run_tracker, settings)
    # We keep track of connection between workunits and spans
    self._workunits_to_spans = {}
    self.encoding = encoding
    # Create a transport handler
    self.handler = HTTPTransportHandler(endpoint, encoding)

  def open(self):
    pass

  def close(self):
    pass

  def start_workunit(self, workunit):
    """Implementation of Reporter callback."""
    # Check if it is the first workunit
    first_span = not self._workunits_to_spans
    if first_span:
      span = zipkin_span(
        service_name='pants_v1',
        span_name=workunit.name,
        transport_handler=self.handler,
        sample_rate=100.0, # Value between 0.0 and 100.0
        encoding=self.set_encoding()
      )
    else:
      span = zipkin_span(
        service_name='pants_v1',
        span_name=workunit.name,
      )
    self._workunits_to_spans[workunit] = span
    span.start()
    span.start_timestamp = workunit.start_time
    if first_span:
      span.logging_context.start_timestamp = workunit.start_time

  def end_workunit(self, workunit):
    """Implementation of Reporter callback."""
    if workunit in self._workunits_to_spans:
      span = self._workunits_to_spans.pop(workunit)
      span.stop()

  def set_encoding(self):
    if self.encoding == 'json':
      return Encoding.V1_JSON
    else:
      return Encoding.V1_THRIFT

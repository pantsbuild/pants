# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from collections import defaultdict
from http.server import BaseHTTPRequestHandler

import psutil


def zipkin_handler():
  class ZipkinHandler(BaseHTTPRequestHandler):
    traces = defaultdict(list)

    def do_POST(self):
      content_length = self.headers.get('content-length')
      json_trace = self.rfile.read(int(content_length))
      trace = json.loads(json_trace)
      for span in trace:
        trace_id = span["traceId"]
        self.__class__.traces[trace_id].append(span)
      self.send_response(200)
  return ZipkinHandler


def find_child_processes_that_send_spans(pants_result_stderr):
  child_processes = set()
  for line in pants_result_stderr.split('\n'):
    if "Sending spans to Zipkin server from pid:" in line:
      i = line.rindex(':')
      child_process_pid = line[i+1:]
      child_processes.add(int(child_process_pid))
  return child_processes


def wait_spans_to_be_sent(child_processes):
  existing_child_processes = child_processes.copy()
  while existing_child_processes:
    for child_pid in child_processes:
      if child_pid in existing_child_processes and not psutil.pid_exists(child_pid):
        existing_child_processes.remove(child_pid)

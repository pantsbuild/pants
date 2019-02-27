# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os.path
import re
import unittest
from builtins import open
from http.server import BaseHTTPRequestHandler

from future.utils import PY3
from parameterized import parameterized
from py_zipkin import Encoding
from py_zipkin.encoding import convert_spans

from pants.util.contextutil import http_server
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


_HEADER = 'invocation_id,task_name,targets_hash,target_id,cache_key_id,cache_key_hash,phase,valid\n'
_REPORT_LOCATION = 'reports/latest/invalidation-report.csv'

_ENTRY = re.compile(r'^\d+,\S+,(init|pre-check|post-check),(True|False)')
_INIT = re.compile(r'^\d+,ZincCompile_compile_zinc,\w+,\S+,init,(True|False)')
_POST = re.compile(r'^\d+,ZincCompile_compile_zinc,\w+,\S+,post-check,(True|False)')
_PRE = re.compile(r'^\d+,ZincCompile_compile_zinc,\w+,\S+,pre-check,(True|False)')


class TestReportingIntegrationTest(PantsRunIntegrationTest, unittest.TestCase):

  def test_invalidation_report_output(self):
    with self.temporary_workdir() as workdir:
      command = ['compile',
                 'examples/src/java/org/pantsbuild/example/hello/main',
                 '--reporting-invalidation-report']
      pants_run = self.run_pants_with_workdir(command, workdir)
      self.assert_success(pants_run)
      output = os.path.join(workdir, _REPORT_LOCATION)
      self.assertTrue(os.path.exists(output))
      with open(output, 'r') as f:
        self.assertEqual(_HEADER, f.readline())
        for line in f.readlines():
          self.assertTrue(_ENTRY.match(line))
          if _INIT.match(line):
            init = True
          elif _PRE.match(line):
            pre = True
          elif _POST.match(line):
            post = True
        self.assertTrue(init and pre and post)

  def test_invalidation_report_clean_all(self):
    with self.temporary_workdir() as workdir:
      command = ['clean-all', 'compile',
                 'examples/src/java/org/pantsbuild/example/hello/main',
                 '--reporting-invalidation-report']
      pants_run = self.run_pants_with_workdir(command, workdir)
      self.assert_success(pants_run)

      # The 'latest' link has been removed by clean-all but that's not fatal.
      report_dirs = os.listdir(os.path.join(workdir, 'reports'))
      self.assertEqual(1, len(report_dirs))

      output = os.path.join(workdir, 'reports', report_dirs[0], 'invalidation-report.csv')
      self.assertTrue(os.path.exists(output), msg='Missing report file {}'.format(output))

  INFO_LEVEL_COMPILE_MSG='Compiling 1 zinc source in 1 target (examples/src/java/org/pantsbuild/example/hello/simple:simple).'
  DEBUG_LEVEL_COMPILE_MSG='compile(examples/src/java/org/pantsbuild/example/hello/simple:simple) finished with status Successful'

  def test_output_level_warn(self):
    command = ['compile',
               'examples/src/java/org/pantsbuild/example/hello/simple',
               '--compile-zinc-level=warn']
    pants_run = self.run_pants(command)
    self.assert_success(pants_run)
    self.assertFalse(self.INFO_LEVEL_COMPILE_MSG in pants_run.stdout_data)
    self.assertFalse(self.DEBUG_LEVEL_COMPILE_MSG in pants_run.stdout_data)

  def test_output_level_info(self):
    command = ['compile',
               'examples/src/java/org/pantsbuild/example/hello/simple',
               '--compile-zinc-level=info']
    pants_run = self.run_pants(command)
    self.assert_success(pants_run)
    self.assertTrue(self.INFO_LEVEL_COMPILE_MSG in pants_run.stdout_data)
    self.assertFalse(self.DEBUG_LEVEL_COMPILE_MSG in pants_run.stdout_data)

  def test_output_level_debug(self):
    command = ['compile',
               'examples/src/java/org/pantsbuild/example/hello/simple',
               '--compile-zinc-level=debug']
    pants_run = self.run_pants(command)
    self.assert_success(pants_run)
    self.assertTrue(self.INFO_LEVEL_COMPILE_MSG in pants_run.stdout_data)
    self.assertTrue(self.DEBUG_LEVEL_COMPILE_MSG in pants_run.stdout_data)

  def test_output_color_enabled(self):
    command = ['compile',
               'examples/src/java/org/pantsbuild/example/hello/simple',
               '--compile-zinc-colors']
    pants_run = self.run_pants(command)
    self.assert_success(pants_run)
    self.assertTrue(self.INFO_LEVEL_COMPILE_MSG + '\x1b[0m' in pants_run.stdout_data)

  def test_output_level_group_compile(self):
    """Set level with the scope 'compile' and see that it propagates to the task level."""
    command = ['compile',
               'examples/src/java/org/pantsbuild/example/hello/simple',
               '--compile-level=debug']
    pants_run = self.run_pants(command)
    self.assert_success(pants_run)
    self.assertTrue(self.INFO_LEVEL_COMPILE_MSG in pants_run.stdout_data)
    self.assertTrue(self.DEBUG_LEVEL_COMPILE_MSG in pants_run.stdout_data)

  def test_default_console(self):
    command = ['compile',
               'examples/src/java/org/pantsbuild/example/hello::']
    pants_run = self.run_pants(command)
    self.assert_success(pants_run)
    self.assertIn('Compiling 1 zinc source in 1 target (examples/src/java/org/pantsbuild/example/hello/greet:greet)',
                  pants_run.stdout_data)
    # Check zinc's label
    self.assertIn('[zinc]\n', pants_run.stdout_data)

  def test_suppress_compiler_output(self):
    command = ['compile',
               'examples/src/java/org/pantsbuild/example/hello::',
               '--reporting-console-label-format={ "COMPILER" : "SUPPRESS" }',
               '--reporting-console-tool-output-format={ "COMPILER" : "CHILD_SUPPRESS"}']
    pants_run = self.run_pants(command)
    self.assert_success(pants_run)
    self.assertIn('Compiling 1 zinc source in 1 target (examples/src/java/org/pantsbuild/example/hello/greet:greet)',
                  pants_run.stdout_data)
    for line in pants_run.stdout_data:
      # zinc's stdout should be suppressed
      self.assertNotIn('Compile success at ', line)
      # zinc's label should be suppressed
      self.assertNotIn('[zinc]', line)

  def test_invalid_config(self):
    command = ['compile',
               'examples/src/java/org/pantsbuild/example/hello::',
               '--reporting-console-label-format={ "FOO" : "BAR" }',
               '--reporting-console-tool-output-format={ "BAZ" : "QUX"}']
    pants_run = self.run_pants(command)
    self.assert_success(pants_run)
    self.assertIn('*** Got invalid key FOO for --reporting-console-label-format. Expected one of [', pants_run.stdout_data)
    self.assertIn('*** Got invalid value BAR for --reporting-console-label-format. Expected one of [', pants_run.stdout_data)
    self.assertIn('*** Got invalid key BAZ for --reporting-console-tool-output-format. Expected one of [', pants_run.stdout_data)
    self.assertIn('*** Got invalid value QUX for --reporting-console-tool-output-format. Expected one of [', pants_run.stdout_data)
    self.assertIn('', pants_run.stdout_data)

  @parameterized.expand(['--quiet', '--no-quiet'])
  def test_epilog_to_stderr(self, quiet_flag):
    command = ['--time', quiet_flag, 'bootstrap', 'examples/src/java/org/pantsbuild/example/hello::']
    pants_run = self.run_pants(command)
    self.assert_success(pants_run)
    self.assertIn('Cumulative Timings', pants_run.stderr_data)
    self.assertNotIn('Cumulative Timings', pants_run.stdout_data)

  def test_zipkin_reporter(self):
    ZipkinHandler = zipkin_handler()
    with http_server(ZipkinHandler) as port:
      endpoint = "http://localhost:{}".format(port)
      command = [
        '--reporting-zipkin-endpoint={}'.format(endpoint),
        'cloc',
        'src/python/pants:version'
      ]

      pants_run = self.run_pants(command)
      self.assert_success(pants_run)

      num_of_traces = len(ZipkinHandler.traces)
      self.assertEqual(num_of_traces, 1)

      trace = ZipkinHandler.traces[-1]
      main_span = self.find_spans_by_name(trace, 'main')
      self.assertEqual(len(main_span), 1)

      parent_id = main_span[0]['id']
      main_children = self.find_spans_by_parentId(trace, parent_id)
      self.assertTrue(main_children)
      self.assertTrue(any(span['name'] == 'cloc' for span in main_children))

  def test_zipkin_reporter_with_given_trace_id_parent_id(self):
    ZipkinHandler = zipkin_handler()
    with http_server(ZipkinHandler) as port:
      endpoint = "http://localhost:{}".format(port)
      trace_id = "aaaaaaaaaaaaaaaa"
      parent_span_id = "ffffffffffffffff"
      command = [
        '--reporting-zipkin-endpoint={}'.format(endpoint),
        '--reporting-zipkin-trace-id={}'.format(trace_id),
        '--reporting-zipkin-parent-id={}'.format(parent_span_id),
        'cloc',
        'src/python/pants:version'
      ]

      pants_run = self.run_pants(command)
      self.assert_success(pants_run)

      num_of_traces = len(ZipkinHandler.traces)
      self.assertEqual(num_of_traces, 1)

      trace = ZipkinHandler.traces[-1]
      main_span = self.find_spans_by_name(trace, 'main')
      self.assertEqual(len(main_span), 1)

      main_span_trace_id = main_span[0]['traceId']
      self.assertEqual(main_span_trace_id, trace_id)
      main_span_parent_id = main_span[0]['parentId']
      self.assertEqual(main_span_parent_id, parent_span_id)

      parent_id = main_span[0]['id']
      main_children = self.find_spans_by_parentId(trace, parent_id)
      self.assertTrue(main_children)
      self.assertTrue(any(span['name'] == 'cloc' for span in main_children))

  def test_zipkin_reporter_with_zero_sample_rate(self):
    ZipkinHandler = zipkin_handler()
    with http_server(ZipkinHandler) as port:
      endpoint = "http://localhost:{}".format(port)
      command = [
        '--reporting-zipkin-endpoint={}'.format(endpoint),
        '--reporting-zipkin-sample-rate=0.0',
        'cloc',
        'src/python/pants:version'
      ]

      pants_run = self.run_pants(command)
      self.assert_success(pants_run)

      num_of_traces = len(ZipkinHandler.traces)
      self.assertEqual(num_of_traces, 0)

  @staticmethod
  def find_spans_by_name(trace, name):
    return [span for span in trace if span['name'] == name]

  @staticmethod
  def find_spans_by_parentId(trace, parent_id):
    return [span for span in trace if span.get('parentId') == parent_id]


def zipkin_handler():
  class ZipkinHandler(BaseHTTPRequestHandler):
    traces = []

    def do_POST(self):
      content_length = self.headers.get('content-length') if PY3 else self.headers.getheader('content-length')
      thrift_trace = self.rfile.read(int(content_length))
      json_trace = convert_spans(thrift_trace, Encoding.V1_JSON, Encoding.V1_THRIFT)
      trace = json.loads(json_trace)
      self.__class__.traces.append(trace)
      self.send_response(200)
  return ZipkinHandler

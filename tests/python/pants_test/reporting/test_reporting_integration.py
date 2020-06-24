# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import unittest
from collections import defaultdict
from http.server import BaseHTTPRequestHandler

import psutil

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.collections import assert_single_element
from pants.util.contextutil import http_server


class TestReportingIntegrationTest(PantsRunIntegrationTest, unittest.TestCase):
    def test_epilog_to_stderr(self) -> None:
        def run_test(quiet_flag: str) -> None:
            command = [
                "--time",
                quiet_flag,
                "bootstrap",
                "examples/src/java/org/pantsbuild/example/hello::",
            ]
            pants_run = self.run_pants(command)
            self.assert_success(pants_run)
            self.assertIn("Cumulative Timings", pants_run.stderr_data)
            self.assertNotIn("Cumulative Timings", pants_run.stdout_data)

        run_test("--quiet")
        run_test("--no-quiet")

    def test_zipkin_reporter_with_zero_sample_rate(self):
        ZipkinHandler = zipkin_handler()
        with http_server(ZipkinHandler) as port:
            endpoint = f"http://localhost:{port}"
            command = [
                "-ldebug",
                f"--reporting-zipkin-endpoint={endpoint}",
                "--reporting-zipkin-sample-rate=0.0",
                "list",
                "examples/src/java/org/pantsbuild/example/hello/simple",
            ]

            pants_run = self.run_pants(command)
            self.assert_success(pants_run)

            child_processes = self.find_child_processes_that_send_spans(pants_run.stderr_data)
            self.assertFalse(child_processes)

            num_of_traces = len(ZipkinHandler.traces)
            self.assertEqual(num_of_traces, 0)

    def test_zipkin_reporter_for_v2_engine(self):
        ZipkinHandler = zipkin_handler()
        with http_server(ZipkinHandler) as port:
            endpoint = f"http://localhost:{port}"
            command = [
                "-ldebug",
                f"--reporting-zipkin-endpoint={endpoint}",
                "--reporting-zipkin-trace-v2",
                "list",
                "examples/src/java/org/pantsbuild/example/hello/simple",
            ]

            pants_run = self.run_pants(command)
            self.assert_success(pants_run)

            child_processes = self.find_child_processes_that_send_spans(pants_run.stderr_data)
            self.assertTrue(child_processes)

            self.wait_spans_to_be_sent(child_processes)

            trace = assert_single_element(ZipkinHandler.traces.values())

            v2_span_name_part = "snapshot"
            self.assertTrue(
                any(v2_span_name_part in span["name"] for span in trace),
                "There is no span that contains '{}' in it's name. The trace:{}".format(
                    v2_span_name_part, trace
                ),
            )

    def test_zipkin_reports_for_pure_v2_goals(self):
        ZipkinHandler = zipkin_handler()
        with http_server(ZipkinHandler) as port:
            endpoint = f"http://localhost:{port}"
            command = [
                "-ldebug",
                "--no-v1",
                "--v2",
                f"--reporting-zipkin-endpoint={endpoint}",
                "--reporting-zipkin-trace-v2",
                "list",
                "3rdparty:",
            ]

            pants_run = self.run_pants(command)
            self.assert_success(pants_run)

            child_processes = self.find_child_processes_that_send_spans(pants_run.stderr_data)
            self.assertTrue(child_processes)

            self.wait_spans_to_be_sent(child_processes)

            trace = assert_single_element(ZipkinHandler.traces.values())

            v2_span_name_part = "snapshot"
            self.assertTrue(
                any(v2_span_name_part in span["name"] for span in trace),
                "There is no span that contains '{}' in it's name. The trace:{}".format(
                    v2_span_name_part, trace
                ),
            )

    @staticmethod
    def find_spans_by_name_and_service_name(trace, name, service_name):
        return [
            span
            for span in trace
            if span["name"] == name
            and span["annotations"][0]["endpoint"]["serviceName"] == service_name
        ]

    @staticmethod
    def find_spans_by_name(trace, name):
        return [span for span in trace if span["name"] == name]

    @staticmethod
    def find_spans_by_parentId(trace, parent_id):
        return [span for span in trace if span.get("parentId") == parent_id]

    @staticmethod
    def find_child_processes_that_send_spans(pants_result_stderr):
        child_processes = set()
        for line in pants_result_stderr.split("\n"):
            if "Sending spans to Zipkin server from pid:" in line:
                i = line.rindex(":")
                child_process_pid = line[i + 1 :]
                child_processes.add(int(child_process_pid))
        return child_processes

    @staticmethod
    def wait_spans_to_be_sent(child_processes):
        existing_child_processes = child_processes.copy()
        while existing_child_processes:
            for child_pid in child_processes:
                if child_pid in existing_child_processes and not psutil.pid_exists(child_pid):
                    existing_child_processes.remove(child_pid)


def zipkin_handler():
    class ZipkinHandler(BaseHTTPRequestHandler):
        traces = defaultdict(list)

        def do_POST(self):
            content_length = self.headers.get("content-length")
            json_trace = self.rfile.read(int(content_length))
            trace = json.loads(json_trace)
            for span in trace:
                trace_id = span["traceId"]
                self.__class__.traces[trace_id].append(span)
            self.send_response(200)

    return ZipkinHandler

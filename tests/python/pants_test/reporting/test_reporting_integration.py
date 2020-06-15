# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import re
import unittest
from collections import defaultdict
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import psutil

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.collections import assert_single_element
from pants.util.contextutil import http_server

_HEADER = "invocation_id,task_name,targets_hash,target_id,cache_key_id,cache_key_hash,phase,valid"
_REPORT_LOCATION = "reports/latest/invalidation-report.csv"

_ENTRY = re.compile(r"^\d+,\S+,(init|pre-check|post-check),(True|False)")
_INIT = re.compile(r"^\d+,RscCompile_compile_rsc,\w+,\S+,init,(True|False)")
_POST = re.compile(r"^\d+,RscCompile_compile_rsc,\w+,\S+,post-check,(True|False)")
_PRE = re.compile(r"^\d+,RscCompile_compile_rsc,\w+,\S+,pre-check,(True|False)")


class TestReportingIntegrationTest(PantsRunIntegrationTest, unittest.TestCase):
    def test_invalidation_report_output(self):
        with self.temporary_workdir() as workdir:
            command = [
                "compile",
                "examples/src/java/org/pantsbuild/example/hello/main",
                "--reporting-invalidation-report",
            ]
            pants_run = self.run_pants_with_workdir(command, workdir)
            self.assert_success(pants_run)
            output = Path(workdir, _REPORT_LOCATION)
            self.assertTrue(output.exists())

            output_contents = output.read_text().splitlines()
            self.assertEqual(_HEADER, output_contents[0])
            init = False
            pre = False
            post = False
            for line in output_contents[1:]:
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
            command = [
                "clean-all",
                "compile",
                "examples/src/java/org/pantsbuild/example/hello/main",
                "--reporting-invalidation-report",
            ]
            pants_run = self.run_pants_with_workdir(command, workdir)
            self.assert_success(pants_run)

            # The 'latest' link has been removed by clean-all but that's not fatal.
            report_dirs = list(Path(workdir, "reports").iterdir())
            self.assertEqual(1, len(report_dirs))

            output = Path(workdir, "reports", report_dirs[0], "invalidation-report.csv")
            self.assertTrue(output.exists(), msg=f"Missing report file {output}")

    INFO_LEVEL_COMPILE_MSG = "Compiling 1 mixed source in 1 target (examples/src/java/org/pantsbuild/example/hello/simple:simple)."
    DEBUG_LEVEL_COMPILE_MSG = "examples/src/java/org/pantsbuild/example/hello/simple:simple) finished with status Successful"

    def test_output_level_warn(self):
        command = [
            "compile",
            "examples/src/java/org/pantsbuild/example/hello/simple",
            "--compile-rsc-level=warn",
        ]
        pants_run = self.run_pants(command)
        self.assert_success(pants_run)
        self.assertFalse(self.INFO_LEVEL_COMPILE_MSG in pants_run.stdout_data)
        self.assertFalse(self.DEBUG_LEVEL_COMPILE_MSG in pants_run.stdout_data)

    def test_output_level_info(self):
        command = [
            "compile",
            "examples/src/java/org/pantsbuild/example/hello/simple",
            "--compile-rsc-level=info",
        ]
        pants_run = self.run_pants(command)
        self.assert_success(pants_run)
        self.assertTrue(self.INFO_LEVEL_COMPILE_MSG in pants_run.stdout_data)
        self.assertFalse(self.DEBUG_LEVEL_COMPILE_MSG in pants_run.stdout_data)

    def test_output_level_debug(self):
        command = [
            "compile",
            "examples/src/java/org/pantsbuild/example/hello/simple",
            "--compile-rsc-level=debug",
        ]
        pants_run = self.run_pants(command)
        self.assert_success(pants_run)
        self.assertTrue(self.INFO_LEVEL_COMPILE_MSG in pants_run.stdout_data)
        self.assertTrue(self.DEBUG_LEVEL_COMPILE_MSG in pants_run.stdout_data)

    def test_output_color_enabled(self):
        command = [
            "compile",
            "examples/src/java/org/pantsbuild/example/hello/simple",
            "--compile-rsc-colors",
        ]
        pants_run = self.run_pants(command)
        self.assert_success(pants_run)
        self.assertTrue(self.INFO_LEVEL_COMPILE_MSG + "\x1b[0m" in pants_run.stdout_data)

    def test_output_level_group_compile(self):
        """Set level with the scope 'compile' and see that it propagates to the task level."""
        command = [
            "compile",
            "examples/src/java/org/pantsbuild/example/hello/simple",
            "--compile-level=debug",
        ]
        pants_run = self.run_pants(command)
        self.assert_success(pants_run)
        self.assertTrue(self.INFO_LEVEL_COMPILE_MSG in pants_run.stdout_data)
        self.assertTrue(self.DEBUG_LEVEL_COMPILE_MSG in pants_run.stdout_data)

    def test_default_console(self):
        command = ["--no-colors", "compile", "examples/src/java/org/pantsbuild/example/hello::"]
        pants_run = self.run_pants(command)
        self.assert_success(pants_run)
        self.assertIn(
            "Compiling 1 mixed source in 1 target (examples/src/java/org/pantsbuild/example/hello/greet:greet)",
            pants_run.stdout_data,
        )
        # Check rsc's label
        self.assertIn("[rsc]\n", pants_run.stdout_data)

    def test_suppress_compiler_output(self):
        command = [
            "compile",
            "examples/src/java/org/pantsbuild/example/hello::",
            '--reporting-console-label-format={ "COMPILER" : "SUPPRESS" }',
            '--reporting-console-tool-output-format={ "COMPILER" : "CHILD_SUPPRESS"}',
        ]
        pants_run = self.run_pants(command)
        self.assert_success(pants_run)
        self.assertIn(
            "Compiling 1 mixed source in 1 target (examples/src/java/org/pantsbuild/example/hello/greet:greet)",
            pants_run.stdout_data,
        )
        for line in pants_run.stdout_data:
            # rsc's stdout should be suppressed
            self.assertNotIn("Compile success at ", line)
            # rsc's label should be suppressed
            self.assertNotIn("[rsc]", line)

    def test_suppress_background_workunits_output(self):
        command = ["compile", "examples/src/java/org/pantsbuild/example/hello::"]
        pants_run = self.run_pants(command)
        self.assert_success(pants_run)
        # background workunit label should be suppressed
        self.assertNotIn("[background]", pants_run.stdout_data)
        # labels of children of the background workunit should be suppressed
        self.assertNotIn("[workdir_build_cleanup]", pants_run.stdout_data)

    def test_invalid_config(self):
        command = [
            "compile",
            "examples/src/java/org/pantsbuild/example/hello::",
            '--reporting-console-label-format={ "FOO" : "BAR" }',
            '--reporting-console-tool-output-format={ "BAZ" : "QUX"}',
        ]
        pants_run = self.run_pants(command)
        self.assert_success(pants_run)
        self.assertIn(
            "*** Got invalid key FOO for --reporting-console-label-format. Expected one of [",
            pants_run.stdout_data,
        )
        self.assertIn(
            "*** Got invalid value BAR for --reporting-console-label-format. Expected one of [",
            pants_run.stdout_data,
        )
        self.assertIn(
            "*** Got invalid key BAZ for --reporting-console-tool-output-format. Expected one of [",
            pants_run.stdout_data,
        )
        self.assertIn(
            "*** Got invalid value QUX for --reporting-console-tool-output-format. Expected one of [",
            pants_run.stdout_data,
        )
        self.assertIn("", pants_run.stdout_data)

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

    def test_zipkin_reporter(self):
        ZipkinHandler = zipkin_handler()
        with http_server(ZipkinHandler) as port:
            endpoint = f"http://localhost:{port}"
            command = [
                "-ldebug",
                f"--reporting-zipkin-endpoint={endpoint}",
                "minimize",
                "examples/src/java/org/pantsbuild/example/hello/simple",
            ]

            pants_run = self.run_pants(command)
            self.assert_success(pants_run)

            child_processes = self.find_child_processes_that_send_spans(pants_run.stderr_data)
            self.assertTrue(child_processes)

            self.wait_spans_to_be_sent(child_processes)

            trace = assert_single_element(ZipkinHandler.traces.values())

            main_span = self.find_spans_by_name(trace, "main")
            self.assertEqual(len(main_span), 1)

            parent_id = main_span[0]["id"]
            main_children = self.find_spans_by_parentId(trace, parent_id)
            self.assertTrue(main_children)
            self.assertTrue(any(span["name"] == "minimize" for span in main_children))

    def test_zipkin_reporter_with_given_trace_id_parent_id(self):
        ZipkinHandler = zipkin_handler()
        with http_server(ZipkinHandler) as port:
            endpoint = f"http://localhost:{port}"
            trace_id = "aaaaaaaaaaaaaaaa"
            parent_span_id = "ffffffffffffffff"
            command = [
                "-ldebug",
                f"--reporting-zipkin-endpoint={endpoint}",
                f"--reporting-zipkin-trace-id={trace_id}",
                f"--reporting-zipkin-parent-id={parent_span_id}",
                "minimize",
                "examples/src/java/org/pantsbuild/example/hello/simple",
            ]

            pants_run = self.run_pants(command)
            self.assert_success(pants_run)

            child_processes = self.find_child_processes_that_send_spans(pants_run.stderr_data)
            self.assertTrue(child_processes)

            self.wait_spans_to_be_sent(child_processes)

            trace = assert_single_element(ZipkinHandler.traces.values())

            main_span = self.find_spans_by_name(trace, "main")
            self.assertEqual(len(main_span), 1)

            main_span_trace_id = main_span[0]["traceId"]
            self.assertEqual(main_span_trace_id, trace_id)
            main_span_parent_id = main_span[0]["parentId"]
            self.assertEqual(main_span_parent_id, parent_span_id)

            parent_id = main_span[0]["id"]
            main_children = self.find_spans_by_parentId(trace, parent_id)
            self.assertTrue(main_children)
            self.assertTrue(any(span["name"] == "minimize" for span in main_children))

    def test_zipkin_reporter_with_zero_sample_rate(self):
        ZipkinHandler = zipkin_handler()
        with http_server(ZipkinHandler) as port:
            endpoint = f"http://localhost:{port}"
            command = [
                "-ldebug",
                f"--reporting-zipkin-endpoint={endpoint}",
                "--reporting-zipkin-sample-rate=0.0",
                "minimize",
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
                "minimize",
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

    def test_zipkin_reporter_multi_threads(self):
        ZipkinHandler = zipkin_handler()
        with http_server(ZipkinHandler) as port:
            endpoint = f"http://localhost:{port}"
            command = [
                "-ldebug",
                f"--reporting-zipkin-endpoint={endpoint}",
                "compile",
                "examples/src/scala/org/pantsbuild/example/several_scala_targets::",
            ]

            pants_run = self.run_pants(command)
            self.assert_success(pants_run)

            child_processes = self.find_child_processes_that_send_spans(pants_run.stderr_data)
            self.assertTrue(child_processes)

            self.wait_spans_to_be_sent(child_processes)

            trace = assert_single_element(ZipkinHandler.traces.values())

            rsc_task_span = self.find_spans_by_name_and_service_name(trace, "rsc", "pants/task")
            self.assertEqual(len(rsc_task_span), 1)
            rsc_task_span_id = rsc_task_span[0]["id"]

            compile_workunit_spans = self.find_spans_by_name_and_service_name(
                trace, "compile", "pants/workunit"
            )
            self.assertEqual(len(compile_workunit_spans), 4)
            self.assertTrue(
                all(span["parentId"] == rsc_task_span_id for span in compile_workunit_spans)
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

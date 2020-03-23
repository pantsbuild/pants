# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
from urllib.parse import urlencode

import requests

from pants.goal.run_tracker import RunTracker
from pants.reporting.reporting import Reporting
from pants.reporting.reporting_server import PantsHandler, ReportingServer
from pants.testutil.test_base import TestBase
from pants.util.contextutil import http_server, temporary_dir
from pants.util.dirutil import safe_file_dump


class ReportingTest(TestBase):

    # Options for Zipkin tracing
    trace_id = "aaaaaaaaaaaaaaaa"
    parent_id = "ffffffffffffffff"
    zipkin_endpoint = "http://localhost:9411/api/v1/spans"

    def test_raise_no_zipkin_endpoint_set(self):

        options = {
            "reporting": {"zipkin_trace_id": self.trace_id, "zipkin_parent_id": self.parent_id}
        }
        context = self.context(for_subsystems=[RunTracker, Reporting], options=options)
        run_tracker = RunTracker.global_instance()
        reporting = Reporting.global_instance()

        with self.assertRaises(ValueError) as result:
            reporting.initialize(run_tracker, context.options)

        self.assertTrue(
            "The zipkin-endpoint flag must be set if zipkin-trace-id and zipkin-parent-id flags are given."
            in str(result.exception)
        )

    def test_raise_no_parent_id_set(self):

        options = {
            "reporting": {"zipkin_trace_id": self.trace_id, "zipkin_endpoint": self.zipkin_endpoint}
        }
        context = self.context(for_subsystems=[RunTracker, Reporting], options=options)

        run_tracker = RunTracker.global_instance()
        reporting = Reporting.global_instance()

        with self.assertRaises(ValueError) as result:
            reporting.initialize(run_tracker, context.options)

        self.assertTrue(
            "Flags zipkin-trace-id and zipkin-parent-id must both either be set or not set."
            in str(result.exception)
        )

    def test_raise_no_trace_id_set(self):

        options = {
            "reporting": {
                "zipkin_parent_id": self.parent_id,
                "zipkin_endpoint": self.zipkin_endpoint,
            }
        }
        context = self.context(for_subsystems=[RunTracker, Reporting], options=options)

        run_tracker = RunTracker.global_instance()
        reporting = Reporting.global_instance()

        with self.assertRaises(ValueError) as result:
            reporting.initialize(run_tracker, context.options)

        self.assertTrue(
            "Flags zipkin-trace-id and zipkin-parent-id must both either be set or not set."
            in str(result.exception)
        )

    def test_raise_if_no_trace_id_and_zipkin_endpoint_set(self):

        options = {"reporting": {"zipkin_parent_id": self.parent_id}}
        context = self.context(for_subsystems=[RunTracker, Reporting], options=options)

        run_tracker = RunTracker.global_instance()
        reporting = Reporting.global_instance()

        with self.assertRaises(ValueError) as result:
            reporting.initialize(run_tracker, context.options)

        self.assertTrue(
            "Flags zipkin-trace-id and zipkin-parent-id must both either be set or not set."
            in str(result.exception)
        )

    def test_raise_if_no_parent_id_and_zipkin_endpoint_set(self):

        options = {"reporting": {"zipkin_trace_id": self.trace_id}}
        context = self.context(for_subsystems=[RunTracker, Reporting], options=options)

        run_tracker = RunTracker.global_instance()
        reporting = Reporting.global_instance()

        with self.assertRaises(ValueError) as result:
            reporting.initialize(run_tracker, context.options)

        self.assertTrue(
            "Flags zipkin-trace-id and zipkin-parent-id must both either be set or not set."
            in str(result.exception)
        )

    def test_raise_if_parent_id_is_of_wrong_len_format(self):
        parent_id = "ff"
        options = {
            "reporting": {
                "zipkin_trace_id": self.trace_id,
                "zipkin_parent_id": parent_id,
                "zipkin_endpoint": self.zipkin_endpoint,
            }
        }
        context = self.context(for_subsystems=[RunTracker, Reporting], options=options)

        run_tracker = RunTracker.global_instance()
        reporting = Reporting.global_instance()

        with self.assertRaises(ValueError) as result:
            reporting.initialize(run_tracker, context.options)

        self.assertTrue(
            "Value of the flag zipkin-parent-id must be a 16-character hex string. "
            + f"Got {parent_id}."
            in str(result.exception)
        )

    def test_raise_if_trace_id_is_of_wrong_len_format(self):
        trace_id = "aa"
        options = {
            "reporting": {
                "zipkin_trace_id": trace_id,
                "zipkin_parent_id": self.parent_id,
                "zipkin_endpoint": self.zipkin_endpoint,
            }
        }
        context = self.context(for_subsystems=[RunTracker, Reporting], options=options)

        run_tracker = RunTracker.global_instance()
        reporting = Reporting.global_instance()

        with self.assertRaises(ValueError) as result:
            reporting.initialize(run_tracker, context.options)

        self.assertTrue(
            "Value of the flag zipkin-trace-id must be a 16-character or 32-character hex string. "
            + f"Got {trace_id}."
            in str(result.exception)
        )

    def test_raise_if_parent_id_is_of_wrong_ch_format(self):
        parent_id = "gggggggggggggggg"
        options = {
            "reporting": {
                "zipkin_trace_id": self.trace_id,
                "zipkin_parent_id": parent_id,
                "zipkin_endpoint": self.zipkin_endpoint,
            }
        }
        context = self.context(for_subsystems=[RunTracker, Reporting], options=options)

        run_tracker = RunTracker.global_instance()
        reporting = Reporting.global_instance()

        with self.assertRaises(ValueError) as result:
            reporting.initialize(run_tracker, context.options)

        self.assertTrue(
            "Value of the flag zipkin-parent-id must be a 16-character hex string. "
            + f"Got {parent_id}."
            in str(result.exception)
        )

    def test_raise_if_trace_id_is_of_wrong_ch_format(self):
        trace_id = "gggggggggggggggg"
        options = {
            "reporting": {
                "zipkin_trace_id": trace_id,
                "zipkin_parent_id": self.parent_id,
                "zipkin_endpoint": self.zipkin_endpoint,
            }
        }
        context = self.context(for_subsystems=[RunTracker, Reporting], options=options)

        run_tracker = RunTracker.global_instance()
        reporting = Reporting.global_instance()

        with self.assertRaises(ValueError) as result:
            reporting.initialize(run_tracker, context.options)

        self.assertTrue(
            "Value of the flag zipkin-trace-id must be a 16-character or 32-character hex string. "
            + f"Got {trace_id}."
            in str(result.exception)
        )

    def test_poll(self):
        with temporary_dir() as dir:

            class TestPantsHandler(PantsHandler):
                def __init__(self, request, client_address, server):
                    super().__init__(
                        settings=ReportingServer.Settings(
                            info_dir=dir,
                            template_dir=dir,
                            assets_dir=dir,
                            root=dir,
                            allowed_clients=["ALL"],
                        ),
                        renderer=None,
                        request=request,
                        client_address=client_address,
                        server=server,
                    )

            safe_file_dump(os.path.join(dir, "file"), "hello")
            with http_server(TestPantsHandler) as port:
                response = requests.get(
                    "http://127.0.0.1:{}/poll?{}".format(
                        port, urlencode({"q": json.dumps([{"id": "0", "path": "file"}])}),
                    )
                )
            self.assertEqual(response.json(), {"0": "hello"})

# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import http.server
import json
import threading
from urllib.parse import parse_qs

from pants.auth.cookies import Cookies
from pants.goal.run_tracker import RunTracker
from pants.testutil.test_base import TestBase
from pants.util.contextutil import temporary_file_path
from pants.version import VERSION


class RunTrackerTest(TestBase):
    def assert_upload_stats(self, *, response_code) -> None:
        stats = {"stats": {"foo": "bar", "baz": 42}}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(handler):
                try:
                    if handler.path.startswith("/redirect"):
                        code = int(handler.path[-3:])
                        handler.send_response(code)
                        handler.send_header("location", mk_url("/upload"))
                        handler.end_headers()
                    else:
                        self.assertEqual("/upload", handler.path)
                        stats_version = handler.headers["X-Pants-Stats-Version"]
                        self.assertIn(stats_version, {"1", "2"})
                        self.assertEqual(handler.headers["User-Agent"], f"pants/v{VERSION}")
                        length = int(handler.headers["Content-Length"])
                        content = handler.rfile.read(length).decode()
                        if stats_version == "2":
                            self.assertEqual("application/json", handler.headers["Content-type"])
                            decoded_post_data = json.loads(content)
                            self.assertEqual(len(decoded_post_data), 1)
                            builds = decoded_post_data["builds"]
                            self.assertEqual(len(builds), 1)
                            received_stats = builds[0]
                        else:
                            self.assertEqual(
                                "application/x-www-form-urlencoded", handler.headers["Content-type"]
                            )
                            received_stats = {
                                k: json.loads(v[0]) for k, v in parse_qs(content).items()
                            }
                        self.assertEqual(stats, received_stats)
                        handler.send_response(response_code)
                        handler.end_headers()
                except Exception:
                    handler.send_response(400)  # Ensure the main thread knows the test failed.
                    raise

        server_address = ("", 0)
        server = http.server.HTTPServer(server_address, Handler)
        host, port = server.server_address

        def mk_url(path):
            return f"http://{host}:{port}{path}"

        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()

        self.context(for_subsystems=[Cookies])
        self.assertTrue(RunTracker.post_stats(mk_url("/upload"), stats, stats_version=1))
        self.assertTrue(RunTracker.post_stats(mk_url("/upload"), stats, stats_version=2))
        self.assertTrue(RunTracker.post_stats(mk_url("/redirect307"), stats, stats_version=1))
        self.assertFalse(RunTracker.post_stats(mk_url("/redirect302"), stats, stats_version=2))
        server.shutdown()
        server.server_close()

    def test_upload_stats(self):
        self.assert_upload_stats(response_code=200)
        self.assert_upload_stats(response_code=201)
        self.assert_upload_stats(response_code=204)

    def test_invalid_stats_version(self):
        stats = {"stats": {"foo": "bar", "baz": 42}}
        url = "http://example.com/upload/"
        with self.assertRaises(ValueError):
            RunTracker.post_stats(url, stats, stats_version=0)

        with self.assertRaises(ValueError):
            RunTracker.post_stats(url, stats, stats_version=None)

        with self.assertRaises(ValueError):
            RunTracker.post_stats(url, stats, stats_version=9)

        with self.assertRaises(ValueError):
            RunTracker.post_stats(url, stats, stats_version="not a number")

    def test_write_stats_to_json_file(self):
        # Set up
        stats = {"stats": {"foo": "bar", "baz": 42}}

        # Execute & verify
        with temporary_file_path() as file_name:
            RunTracker.write_stats_to_json(file_name, stats)
            with open(file_name, "r") as f:
                result = json.load(f)
                self.assertEqual(stats, result)

    def test_create_dict_with_nested_keys_and_val(self):
        keys = []

        with self.assertRaises(ValueError):
            RunTracker._create_dict_with_nested_keys_and_val(keys, "something")

        keys += ["one"]
        self.assertEqual(
            RunTracker._create_dict_with_nested_keys_and_val(keys, "something"),
            {"one": "something"},
        )

        keys += ["two"]
        self.assertEqual(
            RunTracker._create_dict_with_nested_keys_and_val(keys, "something"),
            {"one": {"two": "something"}},
        )

        keys += ["three"]
        self.assertEqual(
            RunTracker._create_dict_with_nested_keys_and_val(keys, "something"),
            {"one": {"two": {"three": "something"}}},
        )

        keys += ["four"]
        self.assertEqual(
            RunTracker._create_dict_with_nested_keys_and_val(keys, "something"),
            {"one": {"two": {"three": {"four": "something"}}}},
        )

    def test_merge_list_of_keys_into_dict(self):
        data = {}
        keys = []

        with self.assertRaises(ValueError):
            RunTracker._merge_list_of_keys_into_dict(data, keys, "something")

        with self.assertRaises(ValueError):
            RunTracker._merge_list_of_keys_into_dict(data, keys, "something", -1)

        keys = ["key"]
        with self.assertRaises(ValueError):
            RunTracker._merge_list_of_keys_into_dict(data, keys, "something", 1)

        keys = ["a"]
        RunTracker._merge_list_of_keys_into_dict(data, keys, "O-N-E")
        self.assertEqual(data, {"a": "O-N-E"})

        keys = ["one", "two", "three"]
        RunTracker._merge_list_of_keys_into_dict(data, keys, "T-H-R-E-E")
        self.assertEqual(data, {"one": {"two": {"three": "T-H-R-E-E"}}, "a": "O-N-E"})

        keys = ["one", "two", "a"]
        RunTracker._merge_list_of_keys_into_dict(data, keys, "L-A")
        self.assertEqual(data, {"one": {"two": {"a": "L-A", "three": "T-H-R-E-E"}}, "a": "O-N-E"})

        keys = ["c", "d", "e", "f"]
        RunTracker._merge_list_of_keys_into_dict(data, keys, "F-O-U-R")
        self.assertEqual(
            data,
            {
                "one": {"two": {"a": "L-A", "three": "T-H-R-E-E"}},
                "a": "O-N-E",
                "c": {"d": {"e": {"f": "F-O-U-R"}}},
            },
        )

        keys = ["one", "two", "x", "y"]
        RunTracker._merge_list_of_keys_into_dict(data, keys, "W-H-Y")
        self.assertEqual(
            data,
            {
                "one": {"two": {"a": "L-A", "three": "T-H-R-E-E", "x": {"y": "W-H-Y"}}},
                "a": "O-N-E",
                "c": {"d": {"e": {"f": "F-O-U-R"}}},
            },
        )

        keys = ["c", "d", "e", "g", "h"]
        RunTracker._merge_list_of_keys_into_dict(data, keys, "H-E-L-L-O")
        self.assertEqual(
            data,
            {
                "one": {"two": {"a": "L-A", "three": "T-H-R-E-E", "x": {"y": "W-H-Y"}}},
                "a": "O-N-E",
                "c": {"d": {"e": {"f": "F-O-U-R", "g": {"h": "H-E-L-L-O"}}}},
            },
        )

        keys = ["one", "two", "x", "z"]
        RunTracker._merge_list_of_keys_into_dict(data, keys, "Z-E-D")
        self.assertEqual(
            data,
            {
                "one": {
                    "two": {"a": "L-A", "three": "T-H-R-E-E", "x": {"y": "W-H-Y", "z": "Z-E-D"}}
                },
                "a": "O-N-E",
                "c": {"d": {"e": {"f": "F-O-U-R", "g": {"h": "H-E-L-L-O"}}}},
            },
        )

        keys = ["c", "d", "e", "g", "i"]
        RunTracker._merge_list_of_keys_into_dict(data, keys, "E-Y-E")
        self.assertEqual(
            data,
            {
                "one": {
                    "two": {"a": "L-A", "three": "T-H-R-E-E", "x": {"y": "W-H-Y", "z": "Z-E-D"}}
                },
                "a": "O-N-E",
                "c": {"d": {"e": {"f": "F-O-U-R", "g": {"h": "H-E-L-L-O", "i": "E-Y-E"}}}},
            },
        )

        keys = ["a"]
        RunTracker._merge_list_of_keys_into_dict(data, keys, "new O-N-E")
        self.assertEqual(
            data,
            {
                "one": {
                    "two": {"a": "L-A", "three": "T-H-R-E-E", "x": {"y": "W-H-Y", "z": "Z-E-D"}}
                },
                "a": "new O-N-E",
                "c": {"d": {"e": {"f": "F-O-U-R", "g": {"h": "H-E-L-L-O", "i": "E-Y-E"}}}},
            },
        )

        keys = ["one", "two", "a"]
        RunTracker._merge_list_of_keys_into_dict(data, keys, "L-A-L-A")
        self.assertEqual(
            data,
            {
                "one": {
                    "two": {"a": "L-A-L-A", "three": "T-H-R-E-E", "x": {"y": "W-H-Y", "z": "Z-E-D"}}
                },
                "a": "new O-N-E",
                "c": {"d": {"e": {"f": "F-O-U-R", "g": {"h": "H-E-L-L-O", "i": "E-Y-E"}}}},
            },
        )

        keys = ["one", "two", "a", "b", "c"]
        with self.assertRaises(ValueError):
            RunTracker._merge_list_of_keys_into_dict(data, keys, "new A")

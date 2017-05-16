# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import BaseHTTPServer
import json
import threading
import urlparse

from pants.goal.run_tracker import RunTracker
from pants.util.contextutil import temporary_file_path
from pants_test.base_test import BaseTest


class RunTrackerTest(BaseTest):
  def test_upload_stats(self):
    stats = {'stats': {'foo': 'bar', 'baz': 42}}

    class Handler(BaseHTTPServer.BaseHTTPRequestHandler):
      def do_POST(handler):
        try:
          self.assertEquals('/upload', handler.path)
          self.assertEquals('application/x-www-form-urlencoded', handler.headers['Content-type'])
          length = int(handler.headers['Content-Length'])
          post_data = urlparse.parse_qs(handler.rfile.read(length).decode('utf-8'))
          decoded_post_data = {k: json.loads(v[0]) for k, v in post_data.items()}
          self.assertEquals(stats, decoded_post_data)
          handler.send_response(200)
        except Exception:
          handler.send_response(400)  # Ensure the main thread knows the test failed.
          raise


    server_address = ('', 0)
    server = BaseHTTPServer.HTTPServer(server_address, Handler)
    host, port = server.server_address

    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    self.assertTrue(RunTracker.post_stats('http://{}:{}/upload'.format(host, port), stats))

    server.shutdown()
    server.server_close()

  def test_write_stats_to_json_file(self):
    # Set up
    stats = {'stats': {'foo': 'bar', 'baz': 42}}

    # Execute & verify
    with temporary_file_path() as file_name:
      self.assertTrue(RunTracker.write_stats_to_json(file_name, stats))
      with open(file_name) as f:
        result = json.load(f)
        self.assertEquals(stats, result)

  def test_create_dict_with_nested_keys_and_val(self):
    keys = []

    self.assertEquals(
      RunTracker.create_dict_with_nested_keys_and_val(keys, 'something', len(keys) - 1),
      None
    )

    keys += ['one']
    self.assertEquals(
      RunTracker.create_dict_with_nested_keys_and_val(keys, 'something', len(keys) - 1),
      {'one': 'something'}
    )

    keys += ['two']
    self.assertEquals(
      RunTracker.create_dict_with_nested_keys_and_val(keys, 'something', len(keys) - 1),
      {'one': {'two': 'something'}}
    )

    keys += ['three']
    self.assertEquals(
      RunTracker.create_dict_with_nested_keys_and_val(keys, 'something', len(keys) - 1),
      {'one': {'two': {'three': 'something'}}}
    )

    keys += ['four']
    self.assertEquals(
      RunTracker.create_dict_with_nested_keys_and_val(keys, 'something', len(keys) - 1),
      {'one': {'two': {'three': {'four': 'something'}}}}
    )

  def test_merge_list_of_keys_into_dict(self):
    data = {}
    keys = []
    index = 0

    with self.assertRaises(ValueError):
      RunTracker.merge_list_of_keys_into_dict(data, keys, 'something', index)

    keys = ['a']
    RunTracker.merge_list_of_keys_into_dict(data, keys, 'O-N-E', index)
    self.assertEquals(data, {'a': 'O-N-E'})

    keys = ['one', 'two', 'three']
    RunTracker.merge_list_of_keys_into_dict(data, keys, 'T-H-R-E-E', index)
    self.assertEquals(data, {'one': {'two': {'three': 'T-H-R-E-E'}}, 'a': 'O-N-E'})

    keys = ['one', 'two', 'a']
    RunTracker.merge_list_of_keys_into_dict(data, keys, 'L-A', index)
    self.assertEquals(data, {'one': {'two': {'a': 'L-A', 'three': 'T-H-R-E-E'}}, 'a': 'O-N-E'})

    keys = ['c', 'd', 'e', 'f']
    RunTracker.merge_list_of_keys_into_dict(data, keys, 'F-O-U-R', index)
    self.assertEquals(data, {
      'one': {'two': {'a': 'L-A', 'three': 'T-H-R-E-E'}}, 'a': 'O-N-E',
      'c': {'d': {'e': {'f': 'F-O-U-R'}}}
    })

    keys = ['one', 'two', 'x', 'y']
    RunTracker.merge_list_of_keys_into_dict(data, keys, 'W-H-Y', index)
    self.assertEquals(data, {
      'one': {'two': {'a': 'L-A', 'three': 'T-H-R-E-E', 'x': {'y': 'W-H-Y'}}}, 'a': 'O-N-E',
      'c': {'d': {'e': {'f': 'F-O-U-R'}}}
    })

    keys = ['c', 'd', 'e', 'g', 'h']
    RunTracker.merge_list_of_keys_into_dict(data, keys, 'H-E-L-L-O', index)
    self.assertEquals(data, {
      'one': {'two': {'a': 'L-A', 'three': 'T-H-R-E-E', 'x': {'y': 'W-H-Y'}}}, 'a': 'O-N-E',
      'c': {'d': {'e': {'f': 'F-O-U-R', 'g': {'h': 'H-E-L-L-O'}}}}
    })

    keys = ['one', 'two', 'x', 'z']
    RunTracker.merge_list_of_keys_into_dict(data, keys, 'Z-E-D', index)
    self.assertEquals(data, {
      'one': {'two': {'a': 'L-A', 'three': 'T-H-R-E-E', 'x': {'y': 'W-H-Y', 'z': 'Z-E-D'}}},
      'a': 'O-N-E', 'c': {'d': {'e': {'f': 'F-O-U-R', 'g': {'h': 'H-E-L-L-O'}}}}
    })

    keys = ['c', 'd', 'e', 'g', 'i']
    RunTracker.merge_list_of_keys_into_dict(data, keys, 'E-Y-E', index)
    self.assertEquals(data, {
      'one': {'two': {'a': 'L-A', 'three': 'T-H-R-E-E', 'x': {'y': 'W-H-Y', 'z': 'Z-E-D'}}},
      'a': 'O-N-E', 'c': {'d': {'e': {'f': 'F-O-U-R', 'g': {'h': 'H-E-L-L-O', 'i': 'E-Y-E'}}}}
    })

    keys = ['a']
    RunTracker.merge_list_of_keys_into_dict(data, keys, 'new O-N-E', index)
    self.assertEquals(data, {
      'one': {'two': {'a': 'L-A', 'three': 'T-H-R-E-E', 'x': {'y': 'W-H-Y', 'z': 'Z-E-D'}}},
      'a': 'new O-N-E', 'c': {'d': {'e': {'f': 'F-O-U-R', 'g': {'h': 'H-E-L-L-O', 'i': 'E-Y-E'}}}}
    })

    keys = ['one', 'two', 'three']
    with self.assertRaises(ValueError):
      RunTracker.merge_list_of_keys_into_dict(data, keys, 'new T-H-R-E-E', index)

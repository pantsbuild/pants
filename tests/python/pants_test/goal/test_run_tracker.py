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

    keys += ['one']
    RunTracker.merge_list_of_keys_into_dict(data, keys, 'O-N-E', index)
    self.assertEquals(data, {'one': 'O-N-E'})

    keys += ['two']
    RunTracker.merge_list_of_keys_into_dict(data, keys, 'T-W-O', index)
    self.assertEquals(data, {'one': {'two': 'T-W-O'}})

    keys += ['three']
    RunTracker.merge_list_of_keys_into_dict(data, keys, 'T-H-R-E-E', index)
    self.assertEquals(data, {'one': {'two': {'three': 'T-H-R-E-E'}}})

    keys = ['one', 'two', 'a']
    RunTracker.merge_list_of_keys_into_dict(data, keys, 'A-E', index)
    self.assertEquals(data, {'one': {'two': {'a': 'A-E', 'three': 'T-H-R-E-E'}}})

    keys = ['one', 'two', 'a', 'b']
    RunTracker.merge_list_of_keys_into_dict(data, keys, 'B-E', index)
    self.assertEquals(data, {'one': {'two': {'a': {'b': 'B-E'}, 'three': 'T-H-R-E-E'}}})

    keys = ['one', 'two', 'three']
    RunTracker.merge_list_of_keys_into_dict(data, keys, 'new T-H-R-E-E', index)
    self.assertEquals(data, {'one': {'two': {'a': {'b': 'B-E'}, 'three': 'new T-H-R-E-E'}}})

    keys = ['one', 'two', 'hi', 'hey', 'hola']
    RunTracker.merge_list_of_keys_into_dict(data, keys, 'H-E-L-L-O', index)
    self.assertEquals(data, {
      'one': {
        'two': {'hi': {'hey': {'hola': 'H-E-L-L-O'}}, 'a': {'b': 'B-E'}, 'three': 'new T-H-R-E-E'}
      }
    })

    keys = ['one', 'two', 'hi', 'hey', 'yeah']
    RunTracker.merge_list_of_keys_into_dict(data, keys, 'Y-E-A-H', index)
    self.assertEquals(data, {
      'one': {
        'two': {
          'hi': {'hey': {'hola': 'H-E-L-L-O', 'yeah': 'Y-E-A-H'}}, 'a': {'b': 'B-E'},
          'three': 'new T-H-R-E-E'
        }
      }
    })

    keys = ['one', 'two', 'a', 'c']
    RunTracker.merge_list_of_keys_into_dict(data, keys, 'S-E-E', index)
    self.assertEquals(data, {
      'one': {
        'two': {
          'hi': {'hey': {'hola': 'H-E-L-L-O', 'yeah': 'Y-E-A-H'}}, 'a': {'b': 'B-E', 'c': 'S-E-E'},
          'three': 'new T-H-R-E-E'
        }
      }
    })

# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants_test.contrib.go.tasks.fetch_utils import zipfile_server
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class GoFetchIntegrationTest(PantsRunIntegrationTest):

  def test_go_fetch(self):
    with zipfile_server():
      args = ['resolve',
              'contrib/go/examples/3rdparty/go/github.com/fakeuser/rlib1',
              'contrib/go/examples/3rdparty/go/github.com/fakeuser/rlib2']
      pants_run = self.run_pants(args)
      self.assert_success(pants_run)
      expected = """
        [go]
        Invalidated 2 targets.
        Downloading http://[::1]:3000/github.com/fakeuser/rlib1.zip...
        Downloading http://[::1]:3000/github.com/fakeuser/rlib2.zip...
        Invalidated 2 targets.
        Downloading http://[::1]:3000/github.com/fakeuser/rlib3.zip...
        Downloading http://[::1]:3000/github.com/fakeuser/rlib4.zip...
      """
      self.assertIn(self.normalize(expected), self.normalize(pants_run.stdout_data))

  def test_go_fetch_failure(self):
    with zipfile_server():
      args = ['resolve',
              'contrib/go/examples/3rdparty/go/github.com/fakeuser/rlib5']
      pants_run = self.run_pants(args)
      self.assert_failure(pants_run)
      expected = """
        [go]
        Invalidated 1 target.
        Downloading http://[::1]:3000/github.com/fakeuser/rlib5.zip...
        github.com/fakeuser/rlib5 has remote dependencies which require local declaration:
          --> github.com/fakeuser/rlib6 (expected go_remote_library declaration at contrib/go/examples/3rdparty/go/github.com/fakeuser/rlib6)
      """
      self.assertIn(self.normalize(expected), self.normalize(pants_run.stdout_data))

  def test_go_fetch_go_run_integration(self):
    with zipfile_server():
      args = ['run',
              'contrib/go/examples/src/go/useRemoteLibs']
      pants_run = self.run_pants(args)
      self.assert_success(pants_run)
      self.assertIn('Hello from main!', pants_run.stdout_data)

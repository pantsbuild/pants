# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_mkdir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class GoFetchIntegrationTest(PantsRunIntegrationTest):

  def setUp(self):
    super(GoFetchIntegrationTest, self).setUp()
    self.zipdir = os.path.join(self.workdir_root(), 'zipdir')
    safe_mkdir(self.zipdir)
    rlib_dir = 'contrib/go/examples/test_remote_libs'
    for p in os.listdir(rlib_dir):
      d = os.path.join(get_buildroot(), rlib_dir, p)
      if os.path.isdir(d):
        zfile = os.path.join(self.zipdir, 'github.com/fakeuser', p)
        shutil.make_archive(zfile, 'zip', root_dir=rlib_dir, base_dir=p)
    self.rlib_host = 'file://{}'.format(os.path.join(get_buildroot(), self.zipdir))

  def test_go_fetch(self):
    args = ['resolve',
            '--resolve-go-remote-lib-host={}'.format(self.rlib_host),
            'contrib/go/examples/3rdparty/go/github.com/fakeuser/rlib1',
            'contrib/go/examples/3rdparty/go/github.com/fakeuser/rlib2']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)
    expected = """
      [go]
      Invalidated 2 targets.
      Downloading {host}/github.com/fakeuser/rlib1.zip...
      Downloading {host}/github.com/fakeuser/rlib2.zip...
      Invalidated 2 targets.
      Downloading {host}/github.com/fakeuser/rlib3.zip...
      Downloading {host}/github.com/fakeuser/rlib4.zip...
    """.format(host=self.rlib_host)
    self.assertIn(self.normalize(expected), self.normalize(pants_run.stdout_data))

  def test_go_fetch_failure(self):
    args = ['resolve',
            '--resolve-go-remote-lib-host={}'.format(self.rlib_host),
            'contrib/go/examples/3rdparty/go/github.com/fakeuser/rlib5']
    pants_run = self.run_pants(args)
    self.assert_failure(pants_run)
    expected = """
      github.com/fakeuser/rlib5 has remote dependencies which require local declaration:
        --> github.com/fakeuser/rlib6 (expected go_remote_library declaration at contrib/go/examples/3rdparty/go/github.com/fakeuser/rlib6)
    """.format(host=self.rlib_host)
    self.assertIn(self.normalize(expected), self.normalize(pants_run.stdout_data))

  def test_go_fetch_go_run_integration(self):
    args = ['run',
            '--resolve-go-remote-lib-host={}'.format(self.rlib_host),
            'contrib/go/examples/src/go/useRemoteLibs']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)
    self.assertIn('Hello from main!', pants_run.stdout_data)

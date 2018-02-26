# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import uuid
from contextlib import contextmanager

from pants.base.build_environment import get_buildroot, pants_version
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_walk
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PantsRequirementIntegrationTest(PantsRunIntegrationTest):
  """A pants plugin should be able to depend on a pants_requirement() alone to
  declare its dependencies on pants modules. This plugin, when added to the
  pythonpath and backend_packages, should be able to declare new BUILD file
  objects."""

  def run_with_testproject_backend_pkgs(self, cmd):
    testproject_backend_src_dir = os.path.join(
      get_buildroot(), 'testprojects/pants-plugins/src/python')
    testproject_backend_pkg_name = 'test_pants_plugin'
    pants_req_addr = 'testprojects/pants-plugins/3rdparty/python/pants'
    pants_test_infra_addr = 'tests/python/pants_test:test_infra'
    pre_cmd_args = [
      "--pythonpath=+['{}']".format(testproject_backend_src_dir),
      "--backend-packages=+['{}']".format(testproject_backend_pkg_name),
      "--pants-test-infra-pants-requirement-target={}".format(pants_req_addr),
      "--pants-test-infra-pants-test-infra-target={}".format(pants_test_infra_addr),
    ]
    command = pre_cmd_args + cmd
    return self.run_pants(command=command)

  @contextmanager
  def unstable_pants_version(self):
    stable_version = pants_version()
    unstable_version = b'{}+{}'.format(stable_version, uuid.uuid4().hex)
    version_dir = os.path.join(get_buildroot(), 'src/python/pants')

    with self.file_renamed(version_dir, 'VERSION', 'VERSION.orig'):
      with open(os.path.join(version_dir, 'VERSION'), 'wb') as fp:
        fp.write(unstable_version)

      pants_run = self.run_pants(['--version'])
      self.assert_success(pants_run)
      self.assertEqual(unstable_version, pants_run.stdout_data.strip())

      yield

  def iter_wheels(self, path):
    for root, _, files in safe_walk(path):
      for f in files:
        if f.endswith('.whl'):
          yield os.path.join(root, f)

  @contextmanager
  def create_unstable_pants_distribution(self):
    with self.unstable_pants_version():
      with temporary_dir() as dist_dir:
        create_pants_dist_cmd = ['--pants-distdir={}'.format(dist_dir),
                                 'setup-py',
                                 '--run=bdist_wheel',
                                 'src/python/pants:pants-packaged']
        pants_run = self.run_pants(create_pants_dist_cmd)
        self.assert_success(pants_run)

        # Create a flat wheel repo from the results of setup-py above.
        with temporary_dir() as repo:
          for wheel in self.iter_wheels(dist_dir):
            shutil.copy(wheel, os.path.join(repo, os.path.basename(wheel)))

          yield repo

  def test_pants_requirement(self):
    self.maxDiff = None

    with self.create_unstable_pants_distribution() as repo:
      tests_dir = 'testprojects/pants-plugins/tests/python/test_pants_plugin'
      with self.file_renamed(os.path.join(get_buildroot(), tests_dir), 'TEST_BUILD', 'BUILD'):
        test_pants_requirement_cmd = ['--python-repos-repos={}'.format(repo),
                                      'test',
                                      tests_dir]
        pants_run = self.run_with_testproject_backend_pkgs(test_pants_requirement_cmd)
        self.assert_success(pants_run)

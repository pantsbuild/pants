# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import shutil
import uuid
from contextlib import contextmanager

from pants.base.build_environment import get_buildroot, pants_version
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_walk
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PantsRequirementIntegrationTestBase(PantsRunIntegrationTest):
  @contextmanager
  def _unstable_pants_version(self):
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

  def _iter_wheels(self, path):
    for root, _, files in safe_walk(path):
      for f in files:
        if f.endswith('.whl'):
          yield os.path.join(root, f)

  @contextmanager
  def create_unstable_pants_distribution(self):
    with self._unstable_pants_version():
      with temporary_dir() as dist_dir:
        create_pants_dist_cmd = ['--pants-distdir={}'.format(dist_dir),
                                 'setup-py',
                                 '--run=bdist_wheel',
                                 'src/python/pants:pants-packaged']
        pants_run = self.run_pants(create_pants_dist_cmd)
        self.assert_success(pants_run)

        # Create a flat wheel repo from the results of setup-py above.
        with temporary_dir() as repo:
          for wheel in self._iter_wheels(dist_dir):
            shutil.copy(wheel, os.path.join(repo, os.path.basename(wheel)))

          yield repo

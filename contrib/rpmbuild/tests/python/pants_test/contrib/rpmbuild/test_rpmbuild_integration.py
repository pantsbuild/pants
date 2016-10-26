# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class RpmbuildIntegrationTest(PantsRunIntegrationTest):
  @classmethod
  def hermetic(cls):
    return True

  def run_pants_with_workdir(self, command, workdir, config=None, stdin_data=None, extra_env=None,
                             build_root=None, tee_output=False, **kwargs):
    full_config = {
      'GLOBAL': {
        'pythonpath': ["%(buildroot)s/contrib/rpmbuild/src/python"],
        'backend_packages': ["pants.backend.python", "pants.contrib.rpmbuild"],
      }
    }
    if config:
      for scope, scoped_cfgs in config.items():
        updated = full_config.get(scope, {})
        updated.update(scoped_cfgs)
        full_config[scope] = updated
    return super(RpmbuildIntegrationTest, self).run_pants_with_workdir(
      command=command,
      workdir=workdir,
      config=full_config,
      stdin_data= stdin_data,
      extra_env=extra_env,
      build_root=build_root,
      tee_output=build_root,
      **kwargs
    )

  def test_build_of_simple_package(self):
    cmd = ['rpmbuild', 'contrib/rpmbuild/tests/python/pants_test/contrib/rpmbuild:pants-testpkg']
    with self.pants_results(cmd) as pants_run:
      self.assert_success(pants_run)

      output_dir = os.path.join(pants_run.workdir, 'rpmbuild', 'rpmbuild', 'current',
        'contrib.rpmbuild.tests.python.pants_test.contrib.rpmbuild.pants-testpkg', 'current')
      self.assertTrue(os.path.exists(os.path.join(output_dir, 'RPMS', 'noarch', 'pants-testpkg-1.0-1.noarch.rpm')))
      self.assertTrue(os.path.exists(os.path.join(output_dir, 'SRPMS', 'pants-testpkg-1.0-1.src.rpm')))

# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ScroogeGenTest(PantsRunIntegrationTest):

  @classmethod
  def hermetic(cls):
    return True

  def run_pants(self, command, config=None, stdin_data=None, extra_env=None, **kwargs):
    full_config = {
      'GLOBAL': {
        'pythonpath': ["%(buildroot)s/contrib/scrooge/src/python"],
        'backend_packages': ["pants.backend.codegen", "pants.backend.jvm", "pants.contrib.scrooge"]
      },
    }
    if config:
      for scope, scoped_cfgs in config.items():
        updated = full_config.get(scope, {})
        updated.update(scoped_cfgs)
        full_config[scope] = updated
    return super(ScroogeGenTest, self).run_pants(command, full_config, stdin_data, extra_env,
                                                   **kwargs)

  @staticmethod
  def thrift_test_target(name):
    return 'contrib/scrooge/tests/thrift/org/pantsbuild/contrib/scrooge/scrooge_gen:' + name

  def test_good(self):
    # scrooge_gen should pass with correct thrift files.
    cmd = ['gen', self.thrift_test_target('good-thrift')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)

  def test_namespace_map(self):
    # scrooge_gen should pass with namespace_map specified
    cmd = ['gen', self.thrift_test_target('namespace-map-thrift')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)

  def test_default_java_namespace(self):
    # scrooge_gen should pass with default_java_namespace specified
    cmd = ['gen', self.thrift_test_target('default-java-namespace-thrift')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)

  def test_include_paths(self):
    # scrooge_gen should pass with include_paths specified
    cmd = ['gen', self.thrift_test_target('include-paths-thrift')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)

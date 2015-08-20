# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from unittest import skipIf

from pants.java.distribution.distribution import DistributionLocator
from pants.util.osutil import OS_ALIASES, get_os_name
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.subsystem.subsystem_util import subsystem_instance


def get_two_distributions():
  with subsystem_instance(DistributionLocator):
    try:
      java7 = DistributionLocator.locate(minimum_version='1.7', maximum_version='1.7.9999')
      java8 = DistributionLocator.locate(minimum_version='1.8', maximum_version='1.8.9999')
      return java7, java8
    except DistributionLocator.Error:
      return None


class DistributionIntegrationTest(PantsRunIntegrationTest):

  def _test_two_distributions(self, os_name=None):
    java7, java8 = get_two_distributions()
    os_name = os_name or get_os_name()

    self.assertNotEqual(java7.home, java8.home)

    for (one, two) in ((java7, java8), (java8, java7)):
      target_spec = 'testprojects/src/java/org/pantsbuild/testproject/printversion'
      run = self.run_pants(['run', target_spec], config={
        'jvm-distributions': {
          'paths': {
            os_name: [one.home],
          }
        }
      }, extra_env={
        'JDK_HOME': two.home,
      })
      self.assert_success(run)
      self.assertIn('java.home:{}'.format(one.home), run.stdout_data)

  @skipIf(get_two_distributions() is None, 'Could not find java 7 and java 8 jvms to test with.')
  def test_jvm_jdk_paths_supercedes_environment_variables(self):
    self._test_two_distributions()

  @skipIf(get_two_distributions() is None, 'Could not find java 7 and java 8 jvms to test with.')
  def test_jdk_paths_with_aliased_os_names(self):
    # NB(gmalmquist): This test will silently no-op and do nothing if the testing machine is running
    # an esoteric os (eg, windows).
    os_name = get_os_name()
    if os_name in OS_ALIASES:
      for other in OS_ALIASES[os_name]:
        if other != os_name:
          self._test_two_distributions(other)

# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager
from unittest import skipIf

from pants.java.distribution.distribution import Distribution, DistributionLocator
from pants.util.osutil import OS_ALIASES, get_os_name
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.subsystem.subsystem_util import subsystem_instance


@contextmanager
def _distribution_locator(**options):
  with subsystem_instance(DistributionLocator, **options) as locator:
    locator._reset()  # Force a fresh locator.
    try:
      yield locator
    finally:
      locator._reset()  # And make sure we we clean up the values we cache.


def _get_two_distributions():
  with _distribution_locator() as locator:
    try:
      java7 = locator.cached(minimum_version='1.7', maximum_version='1.7.9999')
      java8 = locator.cached(minimum_version='1.8', maximum_version='1.8.9999')
      return java7, java8
    except DistributionLocator.Error:
      return None


class DistributionIntegrationTest(PantsRunIntegrationTest):
  def _test_two_distributions(self, os_name=None):
    java7, java8 = _get_two_distributions()
    os_name = os_name or get_os_name()

    self.assertNotEqual(java7.home, java8.home)

    for (one, two) in ((java7, java8), (java8, java7)):
      target_spec = 'testprojects/src/java/org/pantsbuild/testproject/printversion'
      run = self.run_pants(['run', target_spec],
                           config={
                             'jvm-distributions': {
                               'paths': {
                                 os_name: [one.home],
                               }
                             }
                           },
                           extra_env={
                             'JDK_HOME': two.home,
                           })
      self.assert_success(run)
      self.assertIn('java.home:{}'.format(os.path.realpath(one.home)), run.stdout_data)

  @skipIf(_get_two_distributions() is None, 'Could not find java 7 and java 8 jvms to test with.')
  def test_jvm_jdk_paths_supercedes_environment_variables(self):
    self._test_two_distributions()

  @skipIf(_get_two_distributions() is None, 'Could not find java 7 and java 8 jvms to test with.')
  def test_jdk_paths_with_aliased_os_names(self):
    # NB(gmalmquist): This test will silently no-op and do nothing if the testing machine is running
    # an esoteric os (eg, windows).
    os_name = get_os_name()
    if os_name in OS_ALIASES:
      for other in OS_ALIASES[os_name]:
        if other != os_name:
          self._test_two_distributions(other)

  def test_no_jvm_restriction(self):
    with _distribution_locator() as locator:
      distribution = locator.cached()
      target_spec = 'testprojects/src/java/org/pantsbuild/testproject/printversion'
      run = self.run_pants(['run', target_spec])
      self.assert_success(run)
      self.assertIn('java.home:{}'.format(distribution.home), run.stdout_data)

  def test_jvm_meets_min_and_max_distribution(self):
    with _distribution_locator() as locator:
      distribution = locator.cached()
      target_spec = 'testprojects/src/java/org/pantsbuild/testproject/printversion'
      run = self.run_pants(['run', target_spec],
                           config={
                             'jvm-distributions': {
                               'minimum_version': str(distribution.version),
                               'maximum_version': str(distribution.version)
                             }
                           })
      self.assert_success(run)
      self.assertIn('java.home:{}'.format(distribution.home), run.stdout_data)

  def test_impossible_distribution_requirements(self):
    with _distribution_locator() as locator:
      with self.assertRaisesRegexp(Distribution.Error, "impossible constraints"):
        locator.cached('2', '1', jdk=False)

  def _test_jvm_does_not_meet_distribution_requirements(self,
                                                        min_version_arg=None,
                                                        max_version_arg=None,
                                                        min_version_option=None,
                                                        max_version_option=None):
    options = {
      'jvm-distributions': {
        'minimum_version': min_version_option,
        'maximum_version': max_version_option,
      }
    }
    with _distribution_locator(**options) as locator:
      with self.assertRaises(Distribution.Error):
        locator.cached(minimum_version=min_version_arg, maximum_version=max_version_arg, jdk=False)

  # a version less than all other versions
  BOTTOM = '0.00001'
  # a version greater than all other versions
  TOP = '999999'

  def test_does_not_meet_min_version_option(self):
    self._test_jvm_does_not_meet_distribution_requirements(min_version_option=self.TOP)

  def test_does_not_meet_min_version_arg(self):
    self._test_jvm_does_not_meet_distribution_requirements(min_version_arg=self.TOP)

  def test_does_not_meet_max_option(self):
    self._test_jvm_does_not_meet_distribution_requirements(max_version_option=self.BOTTOM)

  def test_does_not_meet_max_arg(self):
    self._test_jvm_does_not_meet_distribution_requirements(max_version_arg=self.BOTTOM)

  def test_min_option_trumps_min_arg(self):
    self._test_jvm_does_not_meet_distribution_requirements(min_version_arg=self.BOTTOM,
                                                           min_version_option=self.TOP)

  def test_min_arg_trumps_min_option(self):
    self._test_jvm_does_not_meet_distribution_requirements(min_version_arg=self.TOP,
                                                           min_version_option=self.BOTTOM)

  def test_max_option_trumps_max_arg(self):
    self._test_jvm_does_not_meet_distribution_requirements(max_version_arg=self.TOP,
                                                           max_version_option=self.BOTTOM)

  def test_max_arg_trumps_max_option(self):
    self._test_jvm_does_not_meet_distribution_requirements(max_version_arg=self.BOTTOM,
                                                           max_version_option=self.TOP)

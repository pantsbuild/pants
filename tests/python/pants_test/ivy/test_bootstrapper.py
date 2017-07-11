# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy_subsystem import IvySubsystem
from pants_test.subsystem.subsystem_util import init_subsystem


class BootstrapperTest(unittest.TestCase):
  def setUp(self):
    super(BootstrapperTest, self).setUp()
    init_subsystem(IvySubsystem)

  def test_simple(self):
    ivy_subsystem = IvySubsystem.global_instance()
    bootstrapper = Bootstrapper(ivy_subsystem=ivy_subsystem)
    ivy = bootstrapper.ivy()
    self.assertIsNotNone(ivy.ivy_cache_dir)
    self.assertIsNone(ivy.ivy_settings)
    bootstrap_jar_path = os.path.join(ivy_subsystem.get_options().pants_bootstrapdir,
                                      'tools', 'jvm', 'ivy', 'bootstrap.jar')
    self.assertTrue(os.path.exists(bootstrap_jar_path))

  def test_reset(self):
    bootstrapper1 = Bootstrapper.instance()
    Bootstrapper.reset_instance()
    bootstrapper2 = Bootstrapper.instance()
    self.assertIsNot(bootstrapper1, bootstrapper2)

  def test_default_ivy(self):
    ivy = Bootstrapper.default_ivy()
    self.assertIsNotNone(ivy.ivy_cache_dir)
    self.assertIsNone(ivy.ivy_settings)

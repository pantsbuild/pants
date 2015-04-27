# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.core.tasks.task import Task
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.util.contextutil import temporary_dir
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase


class DummyBootstrapperTask(Task):
  """A placeholder task used as a hint to BaseTest to initialize the Bootstrapper subsystem."""
  @classmethod
  def options_scope(cls):
    return 'dummy-bootstrapper'

  @classmethod
  def global_subsystems(cls):
    return super(DummyBootstrapperTask, cls).global_subsystems() + (IvySubsystem, )


class BootstrapperTest(JvmToolTaskTestBase):
  @classmethod
  def task_type(cls):
    return DummyBootstrapperTask

  def setUp(self):
    super(BootstrapperTest, self).setUp()
    # Calling self.context() is a hack to make sure subsystems are initialized.
    self.context()

  def test_simple(self):
    bootstrapper = Bootstrapper.instance()
    ivy = bootstrapper.ivy()
    self.assertIsNotNone(ivy.ivy_cache_dir)
    self.assertIsNotNone(ivy.ivy_settings)

  def test_reset(self):
    bootstrapper1 = Bootstrapper.instance()
    Bootstrapper.reset_instance()
    bootstrapper2 = Bootstrapper.instance()
    self.assertNotEqual(bootstrapper1, bootstrapper2)

  def test_default_ivy(self):
    ivy = Bootstrapper.default_ivy()
    self.assertIsNotNone(ivy.ivy_cache_dir)
    self.assertIsNotNone(ivy.ivy_settings)

  def test_fresh_bootstrap(self):
    with temporary_dir() as fresh_bootstrap_dir:
      self.set_bootstrap_options(pants_bootstrapdir=fresh_bootstrap_dir)
      # Initialize the Ivy subsystem
      self.context()
      Bootstrapper.default_ivy()
      bootstrap_jar_path = os.path.join(fresh_bootstrap_dir,
                                        'tools', 'jvm', 'ivy', 'bootstrap.jar')
      self.assertTrue(os.path.exists(bootstrap_jar_path))

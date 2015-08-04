# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.core.tasks.task import Task
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.option.options import Options
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
    # Make sure subsystems are initialized with the given options.
    self.context(options={
      Options.GLOBAL_SCOPE: {'pants_bootstrapdir': self.test_workdir}
    })

  def test_simple(self):
    bootstrapper = Bootstrapper.instance()
    ivy = bootstrapper.ivy()
    self.assertIsNotNone(ivy.ivy_cache_dir)
    self.assertIsNone(ivy.ivy_settings)
    bootstrap_jar_path = os.path.join(self.test_workdir,
                                      'tools', 'jvm', 'ivy', 'bootstrap.jar')
    self.assertTrue(os.path.exists(bootstrap_jar_path))

  def test_reset(self):
    bootstrapper1 = Bootstrapper.instance()
    Bootstrapper.reset_instance()
    bootstrapper2 = Bootstrapper.instance()
    self.assertNotEqual(bootstrapper1, bootstrapper2)

  def test_default_ivy(self):
    ivy = Bootstrapper.default_ivy()
    self.assertIsNotNone(ivy.ivy_cache_dir)
    self.assertIsNone(ivy.ivy_settings)

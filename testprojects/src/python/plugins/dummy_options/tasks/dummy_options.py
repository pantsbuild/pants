# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.task.task import Task


class DummyOptionsTask(Task):
  """This class is only used to test options with deprecations.

  Please see
  pants_test.option.test_options_integration.TestOptionsIntegration#test_options_deprecation_from_config
  """

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--dummy-crufty-deprecated-but-still-functioning', removal_version='999.99.9.dev0',
                removal_hint='blah')
    register('--normal-option')

# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod


class TestTaskMixin(object):
  """A mixin to combine with test runner tasks. The task
  """

  @classmethod
  def register_options(cls, register):
    super(TestTaskMixin, cls).register_options(register)
    register('--skip', action='store_true', help='Skip running tests.')

  def execute(self):
    """Run the task
    """

    if not self.get_options().skip:
      targets = self._get_targets()
      self._validate_targets(targets)
      self._execute(targets)

  @abstractmethod
  def _get_targets(self):
    """Returns the targets that are relevant test targets
    """

  @abstractmethod
  def _validate_targets(self, targets):
    """Ensures that these targets are valid and should be run

    :param targets: list of the targets to validate
    """

  @abstractmethod
  def _execute(self, targets):
    """Actually goes ahead and runs the tests for the targets

    :param targets: list of the targets whose tests are to be run
    """

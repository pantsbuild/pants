# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod

from pants.backend.core.tasks.task import TaskBase


class TestTask(TaskBase):
  def execute(self):
    targets = self.validate_targets()
    self._execute(targets)

  @abstractmethod
  def _validate_targets(self):
    """Ensures the targets are valid, returns the ones that need to be run
    """

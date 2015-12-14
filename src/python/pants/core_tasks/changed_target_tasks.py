# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.core_tasks.noop import NoopCompile, NoopTest
from pants.task.changed_target_task import ChangedTargetTask


class CompileChanged(ChangedTargetTask):
  """Find and compile changed targets."""

  @classmethod
  def prepare(cls, options, round_manager):
    super(CompileChanged, cls).prepare(options, round_manager)
    round_manager.require_data(NoopCompile.product_types()[0])


class TestChanged(ChangedTargetTask):
  """Find and test changed targets."""

  @classmethod
  def prepare(cls, options, round_manager):
    super(TestChanged, cls).prepare(options, round_manager)
    round_manager.require_data(NoopTest.product_types()[0])

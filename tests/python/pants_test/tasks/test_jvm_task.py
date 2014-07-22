# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import pytest

from pants.backend.core.tasks.check_exclusives import ExclusivesMapping
from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_mkdtemp, safe_rmtree
from pants_test.base_test import BaseTest


class DummyJvmTask(JvmTask):
  def execute(self):
    pass


class JvmTaskTest(BaseTest):
  """Test some base functionality in JvmTask."""

  def setUp(self):
    super(JvmTaskTest, self).setUp()
    self.workdir = safe_mkdtemp()

    self.t1 = self.make_target('t1', exclusives={'foo': 'a'})
    self.t2 = self.make_target('t2', exclusives={'foo': 'a'})
    self.t3 = self.make_target('t3', exclusives={'foo': 'b'})
    # Force exclusive propagation on the targets.
    self.t1.get_all_exclusives()
    self.t2.get_all_exclusives()
    self.t3.get_all_exclusives()
    context = self.context(target_roots=[self.t1, self.t2, self.t3])

    # Create the exclusives mapping.
    exclusives_mapping = ExclusivesMapping(context)
    exclusives_mapping.add_conflict('foo', ['a', 'b'])
    exclusives_mapping._populate_target_maps(context.targets())
    context.products.safe_create_data('exclusives_groups', lambda: exclusives_mapping)

    self.task = DummyJvmTask(context, self.workdir)

  def tearDown(self):
    super(JvmTaskTest, self).tearDown()
    safe_rmtree(self.workdir)

  def test_get_base_classpath_for_compatible_targets(self):
    self.task.get_base_classpath_for_compatible_targets([self.t1, self.t2])

  def test_get_base_classpath_for_incompatible_targets(self):
    with pytest.raises(TaskError):
      self.task.get_base_classpath_for_compatible_targets([self.t1, self.t3])

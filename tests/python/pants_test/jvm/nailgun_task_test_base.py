# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.tasks.nailgun_task import NailgunTask

from .jvm_tool_task_test_base import JvmToolTaskTestBase


class NailgunTaskTestBase(JvmToolTaskTestBase):
  """Prepares an ephemeral test build root that supports nailgun tasks."""

  def create_options(self, **kwargs):
    options = dict(nailgun_daemon=True)
    options.update(**kwargs)
    return super(NailgunTaskTestBase, self).create_options(**options)

  @classmethod
  def tearDownClass(cls):
    # Kill any nailguns launched in our ephemeral build root
    NailgunTask.killall()

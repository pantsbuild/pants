# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.tasks.nailgun_task import NailgunProcessGroup
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase


class NailgunTaskTestBase(JvmToolTaskTestBase):
  """Prepares an ephemeral test build root that supports nailgun tasks.
  :API: public
  """

  def setUp(self):
    """
    :API: public
    """
    super(NailgunTaskTestBase, self).setUp()
    self.set_options(use_nailgun=True)

  @classmethod
  def tearDownClass(cls):
    """
    :API: public
    """
    # Kill any nailguns launched in our ephemeral build root.
    NailgunProcessGroup().killall()

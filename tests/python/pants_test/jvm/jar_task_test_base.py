# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase


class JarTaskTestBase(NailgunTaskTestBase):
  """Prepares an ephemeral test build root that supports jar tasks.

  :API: public
  """

# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.util.dirutil import safe_mkdtemp, safe_rmtree
from pants.backend.jvm.tasks.bundle_create import BundleCreate
from pants_test.task_test_base import TaskTestBase


sample_ini_test_1 = """
[DEFAULT]
pants_distdir = /tmp/dist
"""


class BundleCreateTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return BundleCreate

  def setUp(self):
    super(BundleCreateTest, self).setUp()
    self.workdir = safe_mkdtemp()

  def tearDown(self):
    super(BundleCreateTest, self).tearDown()
    safe_rmtree(self.workdir)

  def test_bundle_create_init(self):
    options = {
      'bundle': {
        'deployjar': None,
        'archive_prefix': None,
        'archive': None
      }
    }

    bundle_create = self.create_task(self.context(config=sample_ini_test_1, new_options=options),
                                     self.workdir)
    self.assertEquals(bundle_create._outdir, '/tmp/dist')

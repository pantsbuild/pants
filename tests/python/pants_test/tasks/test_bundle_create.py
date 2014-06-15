# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from pants.backend.jvm.tasks.bundle_create import BundleCreate
from pants_test.base.context_utils import create_context


sample_ini_test_1 = """
[DEFAULT]
pants_distdir = /tmp/dist
"""


class BundleCreateTest(unittest.TestCase):

  def test_bundle_create_init(self):
    options = {
               'bundle_create_deployjar': None,
               'bundle_create_prefix': None,
               'bundle_create_archive': None
               }
    bundle_create = BundleCreate(create_context(config=sample_ini_test_1, options=options),
                                 '/tmp/workdir')
    self.assertEquals(bundle_create._outdir, '/tmp/dist')

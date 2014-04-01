# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from pants.base.context_utils import create_context
from pants.tasks.bundle_create import BundleCreate


sample_ini_test_1 = """
[DEFAULT]
pants_distdir = /tmp/dist
"""


class BundleCreateTest(unittest.TestCase):

  def test_bundle_create_init(self):
    options = {
               'jvm_binary_create_outdir': None,
               'binary_create_compressed': None,
               'binary_create_zip64': None,
               'jvm_binary_create_deployjar': None,
               'bundle_create_prefix': None,
               'bundle_create_archive': None
               }
    bundle_create = BundleCreate(create_context(config=sample_ini_test_1, options=options))
    self.assertEquals(bundle_create.outdir, '/tmp/dist')

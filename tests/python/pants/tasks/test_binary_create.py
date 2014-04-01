# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from pants.base.context_utils import create_context
from pants.tasks.binary_create import BinaryCreate


sample_ini_test_1 = """
[DEFAULT]
pants_distdir = /tmp/dist
"""


class BinaryCreateTest(unittest.TestCase):

  def test_binary_create_init(self):
    options = {'jvm_binary_create_outdir': None,
               'binary_create_compressed': None,
               'binary_create_zip64': None,
               'jvm_binary_create_deployjar': None}
    binary_create = BinaryCreate(create_context(config=sample_ini_test_1, options=options))
    self.assertEquals(binary_create.outdir, '/tmp/dist')

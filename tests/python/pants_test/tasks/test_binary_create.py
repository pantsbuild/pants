# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from pants.backend.jvm.tasks.binary_create import BinaryCreate
from pants_test.base.context_utils import create_context


sample_ini_test_1 = """
[DEFAULT]
pants_distdir = /tmp/dist
"""


class BinaryCreateTest(unittest.TestCase):

  def test_binary_create_init(self):
    binary_create = BinaryCreate(create_context(config=sample_ini_test_1),
                                 '/tmp/workdir')
    self.assertEquals(binary_create._outdir, '/tmp/dist')

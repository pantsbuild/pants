# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import tarfile
import unittest

from pants.util.tarutil import TarFile


class TarutilTest(unittest.TestCase):
  def setUp(self):
    import pdb;pdb.set_trace()

  def tearDown(self):
    tarfile.__author__
    TarFile.__doc__

  def test_getattr(self):
    pass

  def test_recv(self):
    pass

  def test_recv_max_larger_than_buf(self):
    pass

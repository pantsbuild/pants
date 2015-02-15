# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import mox

from pants.base.hash_utils import hash_all, hash_file
from pants.util.contextutil import temporary_file


class TestHashUtils(mox.MoxTestBase):

  def setUp(self):
    super(TestHashUtils, self).setUp()
    self.digest = self.mox.CreateMockAnything()

  def test_hash_all(self):
    self.digest.update('jake')
    self.digest.update('jones')
    self.digest.hexdigest().AndReturn('42')
    self.mox.ReplayAll()

    self.assertEqual('42', hash_all(['jake', 'jones'], digest=self.digest))

  def test_hash_file(self):
    self.digest.update('jake jones')
    self.digest.hexdigest().AndReturn('1137')
    self.mox.ReplayAll()

    with temporary_file() as fd:
      fd.write('jake jones')
      fd.close()

      self.assertEqual('1137', hash_file(fd.name, digest=self.digest))

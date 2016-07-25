# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from internal_backend.utilities.register import PantsReleases
from pants.base.revision import Revision


def _branch_name(revision_str):
  return PantsReleases._branch_name(Revision.semver(revision_str))


class ReleasesTest(unittest.TestCase):

  def test_branch_name_master(self):
    self.assertEquals('master', _branch_name('1.1.0-dev1'))

  def test_branch_name_stable(self):
    self.assertEquals('1.1.x', _branch_name('1.1.0-rc1'))
    self.assertEquals('2.1.x', _branch_name('2.1.0'))

  def test_branch_name_unknown_suffix(self):
    with self.assertRaises(ValueError):
      _branch_name('1.1.0-anything1')

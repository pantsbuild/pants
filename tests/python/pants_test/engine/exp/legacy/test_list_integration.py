# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ListIntegrationTest(PantsRunIntegrationTest, unittest.TestCase):
  def do_list(self, *args):
    pants_run = self.run_pants(['run', 'src/python/pants/engine/exp/legacy:list', '--'] + list(args))
    self.assert_success(pants_run)
    return pants_run

  def test_single(self):
    self.do_list('3rdparty:guava')

  def test_missing(self):
    self.do_list('3rdparty:wait_seriously_there_is_a_library_named_that')

  def test_siblings(self):
    self.do_list('3rdparty:')

  def test_descendants(self):
    self.do_list('3rdparty::')

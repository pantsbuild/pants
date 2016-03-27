# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.pantsd.service.pants_service import PantsService
from pants_test.base_test import BaseTest


class RunnableTestService(PantsService):
  def run(self): pass


class TestPantsService(BaseTest):
  def setUp(self):
    BaseTest.setUp(self)
    self.service = RunnableTestService()

  def test_init(self):
    self.assertTrue(self.service.name)

  def test_run_abstract(self):
    with self.assertRaises(TypeError):
      PantsService()

  def test_terminate(self):
    self.service.terminate()
    assert self.service.is_killed

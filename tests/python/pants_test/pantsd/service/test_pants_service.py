# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.pantsd.service.pants_service import PantsService
from pants_test.test_base import TestBase


class RunnableTestService(PantsService):
  def run(self): pass


class TestPantsService(TestBase):
  def setUp(self):
    super(TestPantsService, self).setUp()
    self.service = RunnableTestService()

  def test_init(self):
    self.assertTrue(self.service.name)

  def test_run_abstract(self):
    with self.assertRaises(TypeError):
      PantsService()

  def test_terminate(self):
    self.service.terminate()
    assert self.service.is_killed

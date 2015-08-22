# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import threading

from pants.pantsd.service.pants_service import PantsService
from pants_test.base_test import BaseTest


class RunnableTestService(PantsService):
  def run(self): pass


class TestPantsService(BaseTest):
  def setUp(self):
    BaseTest.setUp(self)
    self.event = threading.Event()
    self.service = RunnableTestService(self.event)

  def test_init(self):
    self.assertTrue(self.service.name)
    self.assertTrue(self.service.daemon)
    self.assertEquals(self.service._kill_switch, self.event)

  def test_run_abstract(self):
    with self.assertRaises(TypeError):
      PantsService(self.event)

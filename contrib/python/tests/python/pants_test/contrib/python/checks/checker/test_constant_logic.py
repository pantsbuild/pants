# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.contrib.python.checks.checker.plugin_test_base import CheckstylePluginTestBase

from pants.contrib.python.checks.checker.constant_logic import ConstantLogic


class ConstantLogicTest(CheckstylePluginTestBase):
  plugin_type = ConstantLogic

  def test_or(self):
    self.assertNit('None or x', 'T804')
    self.assertNit('True or x', 'T804')
    self.assertNit('False or x', 'T804')
    self.assertNit('1 or x', 'T804')
    self.assertNit('"a" or x', 'T804')
    self.assertNoNits('x or y')

  def test_and(self):
    self.assertNit('None and x', 'T804')
    self.assertNit('x and False', 'T805')
    self.assertNoNits('x and y')

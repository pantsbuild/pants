# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from contextlib import contextmanager

from pants.option.subsystem.global_options import GlobalOptions
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import subsystem_instance


VALID_LEVELS = ['debug', 'info', 'warn']


class GlobalOptionsTest(BaseTest):
  @contextmanager
  def global_options(self):
    with subsystem_instance(GlobalOptions.Factory) as factory:
      yield factory.create()

  def test_get_global_option(self):
    with self.global_options() as global_options:
      self.assertIn(global_options.get_global_option('level'), VALID_LEVELS)

  def test_get_global_options(self):
    with self.global_options() as global_options:
      self.assertIsNotNone(global_options.get_global_options())
      self.assertIn(global_options.get_global_options().level, VALID_LEVELS)

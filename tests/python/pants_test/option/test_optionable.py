# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.option.optionable import Optionable


class OptionableTest(unittest.TestCase):
  def test_optionable(self):
    class NoScope(Optionable):
      pass
    with self.assertRaises(NotImplementedError):
      NoScope()

    class NoneScope(Optionable):
      options_scope = None
    with self.assertRaises(NotImplementedError):
      NoneScope()

    class NonStringScope(Optionable):
      options_scope = 42
    with self.assertRaises(NotImplementedError):
      NonStringScope()

    class StringScope(Optionable):
      options_scope = 'good'
    self.assertEquals('good', StringScope.options_scope)

    class Intermediate(Optionable):
      pass

    class Indirect(Intermediate):
      options_scope = 'good'
    self.assertEquals('good', Indirect.options_scope)

# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.util.argutil import ensure_arg, remove_arg


class ArgutilTest(unittest.TestCase):

  def test_ensure_arg(self):
    self.assertEquals(['foo'], ensure_arg([], 'foo'))
    self.assertEquals(['foo'], ensure_arg(['foo'], 'foo'))
    self.assertEquals(['bar', 'foo'], ensure_arg(['bar'], 'foo'))
    self.assertEquals(['bar', 'foo'], ensure_arg(['bar', 'foo'], 'foo'))

    self.assertEquals(['foo', 'baz'], ensure_arg([], 'foo', param='baz'))
    self.assertEquals(['qux', 'foo', 'baz'], ensure_arg(['qux', 'foo', 'bar'], 'foo', param='baz'))
    self.assertEquals(['foo', 'baz'], ensure_arg(['foo', 'bar'], 'foo', param='baz'))
    self.assertEquals(['qux', 'foo', 'baz', 'foobar'], ensure_arg(['qux', 'foo', 'bar', 'foobar'], 'foo', param='baz'))

  def test_remove_arg(self):
    self.assertEquals([], remove_arg([], 'foo'))
    self.assertEquals([], remove_arg(['foo'], 'foo'))
    self.assertEquals(['bar'], remove_arg(['foo', 'bar'], 'foo'))
    self.assertEquals(['bar'], remove_arg(['bar', 'foo'], 'foo'))
    self.assertEquals(['bar', 'baz'], remove_arg(['bar', 'foo', 'baz'], 'foo'))

    self.assertEquals([], remove_arg([], 'foo', has_param=True))
    self.assertEquals([], remove_arg(['foo', 'bar'], 'foo', has_param=True))
    self.assertEquals(['baz'], remove_arg(['baz', 'foo', 'bar'], 'foo', has_param=True))
    self.assertEquals(['baz'], remove_arg(['foo', 'bar', 'baz'], 'foo', has_param=True))
    self.assertEquals(['qux', 'foobar'], remove_arg(['qux', 'foo', 'bar', 'foobar'], 'foo', has_param='baz'))

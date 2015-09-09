# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import textwrap
import unittest

from pants.base.config import Config
from pants.util.contextutil import temporary_file


class ConfigTest(unittest.TestCase):

  def setUp(self):
    with temporary_file() as ini1:
      ini1.write(textwrap.dedent(
        """
        [DEFAULT]
        name: foo
        answer: 42
        scale: 1.2
        path: /a/b/%(answer)s
        embed: %(path)s::foo
        disclaimer:
          Let it be known
          that.
        blank_section:

        [a]
        list: [1, 2, 3, %(answer)s]

        [b]
        preempt: True
        dict: {
            'a': 1,
            'b': %(answer)s,
            'c': ['%(answer)s', %(answer)s]
          }
        """))
      ini1.close()

      with temporary_file() as ini2:
        ini2.write(textwrap.dedent(
          """
          [a]
          fast: True

          [b]
          preempt: False

          [defined_section]
          """))
        ini2.close()
        self.config = Config.load(configpaths=[ini1.name, ini2.name])

  def test_getstring(self):
    self.assertEquals('foo', self.config.getdefault('name'))
    self.assertEquals('/a/b/42', self.config.get('a', 'path'))
    self.assertEquals('/a/b/42::foo', self.config.get('a', 'embed'))
    self.assertEquals(
      """
Let it be known
that.""",
      self.config.get('b', 'disclaimer'))

    self._check_defaults(self.config.get, '')
    self._check_defaults(self.config.get, '42')

  def test_getint(self):
    self.assertEquals(42, self.config.getint('a', 'answer'))
    self._check_defaults(self.config.get, 42)

  def test_getfloat(self):
    self.assertEquals(1.2, self.config.getfloat('b', 'scale'))
    self._check_defaults(self.config.get, 42.0)

  def test_getbool(self):
    self.assertTrue(self.config.getbool('a', 'fast'))
    self.assertFalse(self.config.getbool('b', 'preempt'))
    self._check_defaults(self.config.get, True)

  def test_getlist(self):
    self.assertEquals([1, 2, 3, 42], self.config.getlist('a', 'list'))
    self._check_defaults(self.config.get, [])
    self._check_defaults(self.config.get, [42])

  def test_getdict(self):
    self.assertEquals(dict(a=1, b=42, c=['42', 42]), self.config.getdict('b', 'dict'))
    self._check_defaults(self.config.get, {})
    self._check_defaults(self.config.get, dict(a=42))

  def test_get_required(self):
    self.assertEquals('foo', self.config.get_required('a', 'name'))
    self.assertEquals(42, self.config.get_required('a', 'answer', type=int))
    with self.assertRaises(Config.ConfigError):
      self.config.get_required('a', 'answer', type=dict)
    with self.assertRaises(Config.ConfigError):
      self.config.get_required('a', 'no_section')
    with self.assertRaises(Config.ConfigError):
      self.config.get_required('a', 'blank_section')

  def test_getdefault(self):
    self.assertEquals('foo', self.config.getdefault('name'))

  def test_getdefault_explicit(self):
    self.assertEquals('foo', self.config.getdefault('name', type=str))

  def test_getdefault_not_found(self):
    with self.assertRaises(Config.ConfigError):
      self.config.getdefault('name', type=int)

  def test_default_section_fallback(self):
    self.assertEquals('foo', self.config.get('defined_section', 'name'))
    self.assertEquals('foo', self.config.get('not_a_defined_section', 'name'))

  def _check_defaults(self, accessor, default):
    self.assertEquals(None, accessor('c', 'fast'))
    self.assertEquals(None, accessor('c', 'preempt', None))
    self.assertEquals(default, accessor('c', 'jake', default=default))

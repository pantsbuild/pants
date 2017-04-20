# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import textwrap
import unittest

from pants.option.config import Config
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
        listappend: +[7, 8, 9]

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
    self.assertEquals('/a/b/42', self.config.get('a', 'path'))
    self.assertEquals('/a/b/42::foo', self.config.get('a', 'embed'))
    self.assertEquals('[1, 2, 3, 42]', self.config.get('a', 'list'))
    self.assertEquals('+[7, 8, 9]', self.config.get('a', 'listappend'))
    self.assertEquals(
      """
Let it be known
that.""",
      self.config.get('b', 'disclaimer'))

    self._check_defaults(self.config.get, '')
    self._check_defaults(self.config.get, '42')

  def test_default_section(self):
    self.assertEquals('foo', self.config.get(Config.DEFAULT_SECTION, 'name'))
    self.assertEquals('foo', self.config.get(Config.DEFAULT_SECTION, 'name'))

  def test_sections(self):
    self.assertEquals(['a', 'b', 'defined_section'], self.config.sections())

  def test_empty(self):
    config = Config.load([])
    self.assertEquals([], config.sections())

  def _check_defaults(self, accessor, default):
    self.assertEquals(None, accessor('c', 'fast'))
    self.assertEquals(None, accessor('c', 'preempt', None))
    self.assertEquals(default, accessor('c', 'jake', default=default))

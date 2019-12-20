# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap
import unittest

from pants.option.config import Config
from pants.util.contextutil import temporary_file, temporary_file_path


class ConfigTest(unittest.TestCase):

  def setUp(self) -> None:
    self.ini1_content = textwrap.dedent(
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
      """
    )

    self.ini2_content = textwrap.dedent(
      """
      [a]
      fast: True

      [b]
      preempt: False

      [defined_section]
      """
    )

    with temporary_file(binary_mode=False) as ini1, \
      temporary_file(binary_mode=False) as ini2, \
      temporary_file_path() as buildroot:
      ini1.write(self.ini1_content)
      ini1.close()
      ini2.write(self.ini2_content)
      ini2.close()
      self.config = Config.load(
        config_paths=[ini1.name, ini2.name], seed_values={"buildroot": buildroot}
      )
      self.assertEqual([ini1.name, ini2.name], self.config.sources())

  def test_getstring(self) -> None:
    self.assertEqual('/a/b/42', self.config.get('a', 'path'))
    self.assertEqual('/a/b/42::foo', self.config.get('a', 'embed'))
    self.assertEqual('[1, 2, 3, 42]', self.config.get('a', 'list'))
    self.assertEqual('+[7, 8, 9]', self.config.get('a', 'listappend'))
    self.assertEqual(
      """
Let it be known
that.""",
      self.config.get('b', 'disclaimer'))

    def check_defaults(default: str) -> None:
      assert self.config.get('c', 'fast') is None
      assert self.config.get('c', 'preempt', None) is None
      assert self.config.get('c', 'jake', default=default) == default

    check_defaults('')
    check_defaults('42')

  def test_default_section(self) -> None:
    self.assertEqual('foo', self.config.get(Config.DEFAULT_SECTION, 'name'))
    self.assertEqual('foo', self.config.get(Config.DEFAULT_SECTION, 'name'))

  def test_sections(self) -> None:
    self.assertEqual(['a', 'b', 'defined_section'], self.config.sections())

  def test_empty(self) -> None:
    config = Config.load([])
    self.assertEqual([], config.sections())

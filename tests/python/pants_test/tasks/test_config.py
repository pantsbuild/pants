# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import textwrap
import unittest
from contextlib import contextmanager

from pants.base.config import Config, get_pants_configdir, get_pants_cachedir
from pants.util.contextutil import environment_as, temporary_file


class ConfigTest(unittest.TestCase):

  @contextmanager
  def env(self, **kwargs):
    environment = dict(PATH=None)
    environment.update(**kwargs)
    with environment_as(**environment):
      yield

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

  def test_getmap(self):
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
    with self.assertRaises(NameError):
      self.assertEquals('foo', self.config.getdefault('name', type=int))

  def _check_defaults(self, accessor, default):
    self.assertEquals(None, accessor('c', 'fast'))
    self.assertEquals(None, accessor('c', 'preempt', None))
    self.assertEquals(default, accessor('c', 'jake', default=default))

  def test_get_configdir(self):
    with self.env():
      self.assertEquals(os.path.expanduser('~/.config/pants'), get_pants_configdir())

  def test_set_cachedir(self):
    with self.env():
      self.assertEquals(os.path.expanduser('~/.cache/pants'), get_pants_cachedir())

  def test_set_configdir(self):
    with temporary_file() as temp:
      with self.env(XDG_CONFIG_HOME=temp.name):
        self.assertEquals(temp.name, get_pants_configdir())

  def test_set_cachedir(self):
    with temporary_file() as temp:
      with self.env(XDG_CACHE_HOME=temp.name):
        self.assertEquals(temp.name, get_pants_cachedir())
# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from pants.base.config import Config
from pants.util.contextutil import temporary_file


class ConfigTest(unittest.TestCase):

  def setUp(self):
    with temporary_file() as ini:
      ini.write(
'''
[DEFAULT]
answer: 42
scale: 1.2
path: /a/b/%(answer)s
embed: %(path)s::foo
disclaimer:
  Let it be known
  that.

[a]
fast: True
list: [1, 2, 3, %(answer)s]

[b]
preempt: False
dict: {
    'a': 1,
    'b': %(answer)s,
    'c': ['%(answer)s', %(answer)s]
  }
''')
      ini.close()
      self.config = Config.load(configpath=ini.name)


  def test_getstring(self):
    self.assertEquals('/a/b/42', self.config.get('a', 'path'))
    self.assertEquals('/a/b/42::foo', self.config.get('a', 'embed'))
    self.assertEquals(
      '''
Let it be known
that.''',
      self.config.get('b', 'disclaimer'))

    self.checkDefaults(self.config.get, '')
    self.checkDefaults(self.config.get, '42')


  def test_getint(self):
    self.assertEquals(42, self.config.getint('a', 'answer'))
    self.checkDefaults(self.config.get, 42)


  def test_getfloat(self):
    self.assertEquals(1.2, self.config.getfloat('b', 'scale'))
    self.checkDefaults(self.config.get, 42.0)


  def test_getbool(self):
    self.assertTrue(self.config.getbool('a', 'fast'))
    self.assertFalse(self.config.getbool('b', 'preempt'))
    self.checkDefaults(self.config.get, True)


  def test_getlist(self):
    self.assertEquals([1, 2, 3, 42], self.config.getlist('a', 'list'))
    self.checkDefaults(self.config.get, [])
    self.checkDefaults(self.config.get, [42])


  def test_getmap(self):
    self.assertEquals(dict(a=1, b=42, c=['42', 42]), self.config.getdict('b', 'dict'))
    self.checkDefaults(self.config.get, {})
    self.checkDefaults(self.config.get, dict(a=42))


  def checkDefaults(self, accessor, default):
    self.assertEquals(None, accessor('c', 'fast'))
    self.assertEquals(None, accessor('c', 'preempt', None))
    self.assertEquals(default, accessor('c', 'jake', default=default))

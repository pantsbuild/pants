# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from collections import OrderedDict
from io import StringIO
from tempfile import NamedTemporaryFile

from pants.backend.jvm.tasks.properties import Properties


class PropertiesTest(unittest.TestCase):
  """Exercise pants.backend.jvm.tasks.properties.Properties.

  Copied from https://github.com/twitter/commons/blob/master/tests/python/twitter/common/config/properties_test.py
  """

  def test_empty(self):
    self.assertLoaded('', {})
    self.assertLoaded(' ', {})
    self.assertLoaded('\t', {})
    self.assertLoaded('''

    ''', {})

  def test_comments(self):
    self.assertLoaded('''
# not=a prop
a=prop
 ! more non prop
    ''', {'a': 'prop'})

  def test_kv_sep(self):
    self.assertLoaded('''
    a=b
    c   d\=
    e\: :f
    jack spratt = \tbob barker
    g
    h=
    i :
    ''', {'a': 'b', 'c': 'd=', 'e:': 'f', 'jack spratt': 'bob barker', 'g': '', 'h': '', 'i': ''})

  def test_line_continuation(self):
    self.assertLoaded('''
    # A 3 line continuation
    a\\\\
        \\
           \\b
    c=\
    d
    e: \
    f
    g\
    :h
    i\
    = j
    ''', {'a\\': '\\b', 'c': 'd', 'e': 'f', 'g': 'h', 'i': 'j'})

  def test_stream(self):
    with NamedTemporaryFile() as props_out:
      props_out.write('''
      it's a = file
      ''')
      props_out.flush()
      with open(props_out.name, 'r') as props_in:
        self.assertLoaded(props_in, {'it\'s a': 'file'})

  def assertLoaded(self, contents, expected):
    self.assertEquals(expected, Properties.load(contents))

  def test_dump(self):
    props = OrderedDict()
    props['a'] = 1
    props['b'] = '''2
'''
    props['c'] =' 3 : ='
    out = StringIO()
    Properties.dump(props, out)
    self.assertEquals('a=1\nb=2\\\n\nc=\\ 3\\ \\:\\ \\=\n', out.getvalue())

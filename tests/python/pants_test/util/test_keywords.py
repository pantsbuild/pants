# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from textwrap import dedent
import unittest2 as unittest

from mock import call, mock_open, patch

import pants.util.keywords
from pants.util.contextutil import temporary_file
from pants.util.strutil import ensure_binary


class TestKeywords(unittest.TestCase):
  def test_keyword_replaced(self):
    # These are ensure_binary because python's read() does not do decoding
    thrift_contents = dedent('''
      # This file contains UTF-8: Anasûrimbor Kellhus
      namespace py gen.twitter.tweetypie.tweet
      struct UrlEntity {
        1: i16 from
      }
    ''').encode('utf-8')
    expected_replaced_contents = ensure_binary(dedent('''
      # This file contains UTF-8: Anasûrimbor Kellhus
      namespace py gen.twitter.tweetypie.tweet
      struct UrlEntity {
        1: i16 from_
      }
    ''').encode('utf-8'))

    with temporary_file() as tmp:
      tmp.write(thrift_contents)
      tmp.flush()
      pants.util.keywords.replace_python_keywords_in_file(tmp.name)
      with open(tmp.name) as f:
        self.assertEquals(expected_replaced_contents, f.read())

  def test_non_keyword_file(self):
    thrift_contents = dedent('''
      namespace py gen.twitter.tweetypie.tweet
      struct UrlEntity {
        1: i16 no_keyword
        2: i16 from_
        3: i16 _fromdsd
        4: i16 FROM
        5: i16 fromsuffix
      }
    ''')
    with temporary_file() as tmp:
      tmp.write(thrift_contents)
      tmp.flush()
      pants.util.keywords.replace_python_keywords_in_file(tmp.name)
      with open(tmp.name) as f:
        self.assertEquals(thrift_contents, f.read())

# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from textwrap import dedent
import unittest2 as unittest

from mock import call, mock_open, patch

from pants.util.strutil import ensure_binary
from pants.util.keywords import replace_python_keywords_in_file


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
    m = mock_open(read_data=thrift_contents)
    with patch('__builtin__.open', m, create=True):
      replace_python_keywords_in_file('thrift_dummmy.thrift')
      expected_open_call_list = [call('thrift_dummmy.thrift'), call('thrift_dummmy.thrift', 'w')]
      m.call_args_list == expected_open_call_list
      mock_file_handle = m()
      mock_file_handle.write.assert_called_once_with(expected_replaced_contents)

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
    m = mock_open(read_data=thrift_contents)
    with patch('__builtin__.open', m, create=True):
      replace_python_keywords_in_file('thrift_dummmy.thrift')
      expected_open_call_list = [call('thrift_dummmy.thrift'), call('thrift_dummmy.thrift', 'w')]
      m.call_args_list == expected_open_call_list
      mock_file_handle = m()
      mock_file_handle.write.assert_called_once_with(thrift_contents)

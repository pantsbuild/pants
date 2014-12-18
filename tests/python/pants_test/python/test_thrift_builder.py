# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from textwrap import dedent

from mock import call, mock_open, patch

from pants.backend.codegen.targets.python_thrift_library import PythonThriftLibrary
from pants.backend.python.thrift_builder import PythonThriftBuilder
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.source_root import SourceRoot
from pants_test.base.context_utils import create_config
from pants_test.base_test import BaseTest
from pants.util.strutil import ensure_binary


sample_ini_test = """
[DEFAULT]
pants_workdir: %(buildroot)s
thrift_workdir: %(pants_workdir)s/thrift
"""


class TestPythonThriftBuilder(BaseTest):
  @property
  def alias_groups(self):
    return BuildFileAliases.create(targets={'python_thrift_library': PythonThriftLibrary})

  def setUp(self):
    super(TestPythonThriftBuilder, self).setUp()
    SourceRoot.register(os.path.realpath(os.path.join(self.build_root, 'test_thrift_replacement')),
                        PythonThriftLibrary)
    self.add_to_build_file('test_thrift_replacement', dedent('''
      python_thrift_library(name='one',
        sources=['thrift/keyword.thrift'],
      )
    '''))

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
    builder = PythonThriftBuilder(target=self.target('test_thrift_replacement:one'),
                                  root_dir=self.build_root,
                                  config=create_config(sample_ini=sample_ini_test))
    m = mock_open(read_data=thrift_contents)
    with patch('__builtin__.open', m, create=True):
      builder = PythonThriftBuilder(target=self.target('test_thrift_replacement:one'),
                                  root_dir=self.build_root,
                                  config=create_config(sample_ini=sample_ini_test))
      builder._modify_thrift('thrift_dummmy.thrift')
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
    builder = PythonThriftBuilder(target=self.target('test_thrift_replacement:one'),
                                  root_dir=self.build_root,
                                  config=create_config(sample_ini=sample_ini_test))
    m = mock_open(read_data=thrift_contents)
    with patch('__builtin__.open', m, create=True):
      builder = PythonThriftBuilder(target=self.target('test_thrift_replacement:one'),
                                  root_dir=self.build_root,
                                  config=create_config(sample_ini=sample_ini_test))
      builder._modify_thrift('thrift_dummmy.thrift')
      expected_open_call_list = [call('thrift_dummmy.thrift'), call('thrift_dummmy.thrift', 'w')]
      m.call_args_list == expected_open_call_list
      mock_file_handle = m()
      mock_file_handle.write.assert_called_once_with(thrift_contents)

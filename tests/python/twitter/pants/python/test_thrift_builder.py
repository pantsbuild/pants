#==================================================================================================
# Copyright 2014 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import os

from textwrap import dedent

from twitter.pants import PythonThriftLibrary, SourceRoot
from twitter.pants.base_build_root_test import BaseBuildRootTest
from twitter.pants.base.context_utils import create_config
from twitter.pants.python.thrift_builder import PythonThriftBuilder

from mock import call, MagicMock, mock_open, patch

sample_ini_test = """
[DEFAULT]
pants_workdir: %(buildroot)s
thrift_workdir: %(pants_workdir)s/thrift
"""


class TestPythonThriftBuilder(BaseBuildRootTest):

  @classmethod
  def setUpClass(self):
    super(TestPythonThriftBuilder, self).setUpClass()
    SourceRoot.register(os.path.realpath(os.path.join(self.build_root, 'test_thrift_replacement')),
                        PythonThriftLibrary)
    self.create_target('test_thrift_replacement', dedent('''
      python_thrift_library(name='one',
        sources=['thrift/keyword.thrift'],
        dependencies=None
      )
    '''))

  def test_keyword_replacement(self):
    m = mock_open(read_data='')
    with patch('__builtin__.open', m, create=True):
      with patch('shutil.copyfile'):
        builder = PythonThriftBuilder(target=self.target('test_thrift_replacement:one'),
                                    root_dir=self.build_root,
                                    config=create_config(sample_ini=sample_ini_test))

        builder._modify_thrift = MagicMock()
        builder._run_thrift = MagicMock()
        builder.run_thrifts()

        builder._modify_thrift.assert_called_once_with(os.path.realpath('%s/thrift/py-thrift/%s'
                                                                      % (self.build_root,
                                                                        'thrift/keyword.thrift')))

  def test_keyword_replaced(self):
    thrift_contents = dedent('''
      namespace py gen.twitter.tweetypie.tweet
      struct UrlEntity {
        1: i16 from
      }
    ''')
    expected_replaced_contents = dedent('''
      namespace py gen.twitter.tweetypie.tweet
      struct UrlEntity {
        1: i16 from_
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

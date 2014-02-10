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
import sys
import unittest

from tempfile import mkdtemp

from twitter.common.dirutil import safe_rmtree

from twitter.pants import BuildRoot, get_buildroot
from twitter.pants.python.file_copier import FileCopier
from twitter.pants.targets.sources import SourceRoot
from twitter.pants.targets.python_thrift_library import PythonThriftLibrary

sys.path.append(os.path.join(get_buildroot(), 'src/python/twitter'))
from twadoop.pants.targets.remote_python_thrift_library import RemotePythonThriftLibrary

from mock import patch


class TestFileCopier(unittest.TestCase):

  @classmethod
  def setUpClass(self):
    self.root = mkdtemp(suffix='_BUILD_ROOT')
    BuildRoot().path = self.root
    self.file_root = mkdtemp(suffix='_FILE_ROOT')
    SourceRoot.register(os.path.realpath(os.path.join(self.root,
                                                      'src/thrift')), PythonThriftLibrary)
    SourceRoot.register(os.path.realpath(os.path.join(self.root,
                                                      '.pantsd/thrift')), RemotePythonThriftLibrary)

  def test_find_and_copy_relative_file(self):
    with patch('shutil.copyfile') as mock:
      file_copier = FileCopier(self.file_root)
      file_copier.find_and_copy_relative_file('src/thrift/com/twitter/example.thrift',
                                               [RemotePythonThriftLibrary, PythonThriftLibrary])
      mock.assert_called_once_with('src/thrift/com/twitter/example.thrift',
                                   os.path.join(self.file_root, 'com/twitter/example.thrift'))

  def test_copy_relative_file(self):
    with patch('shutil.copyfile') as mock:
      file_copier = FileCopier(self.file_root)
      file_copier.copy_relative_file('src/extra/com/twitter/example.thrift', 'src/extra')
      mock.assert_called_once_with('src/extra/com/twitter/example.thrift',
                                   os.path.join(self.file_root, 'com/twitter/example.thrift'))

  def test_file_not_found_exception(self):
    file_copier = FileCopier(self.file_root)
    self.assertRaises(file_copier.FileNotFoundInSourceRoot, file_copier.find_and_copy_relative_file,
                      'some_where_else/com/twitter/example.thrift',
                      [RemotePythonThriftLibrary, PythonThriftLibrary])

  @classmethod
  def tearDownClass(self):
    SourceRoot.reset()
    safe_rmtree(self.root)
    safe_rmtree(self.file_root)

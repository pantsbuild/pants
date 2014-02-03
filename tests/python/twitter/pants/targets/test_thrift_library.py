# ==================================================================================================
# Copyright 2013 Twitter, Inc.
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

import pytest

from textwrap import dedent

from twitter.pants.base.target import TargetDefinitionException
from twitter.pants.base_build_root_test import BaseBuildRootTest
from twitter.pants.targets.thrift_library import ThriftJar


class ThriftLibraryTest(BaseBuildRootTest):
  @classmethod
  def setUpClass(cls):
    super(ThriftLibraryTest, cls).setUpClass()

    cls.create_target('3rdparty',
                      dedent('''
                        jar_library(
                          name='jar',
                          dependencies=[
                            jar(org='foo', name='bar', rev='0.0.1')
                          ]
                        )

                        jar_library(
                          name='thrift-jar',
                          dependencies=[
                            thrift_jar(org='foo', name='bip', rev='0.0.1')
                          ]
                        )
                        ''').strip())

    cls.create_target('valid',
                      dedent('''
                        thrift_library(name='empty', sources=[], dependencies=[])

                        thrift_library(
                          name='local-thrifts',
                          sources=[],
                          dependencies=[
                            pants(':empty'),
                            thrift_library(name='split', sources=[], dependencies=[pants(':empty')])
                          ]
                        )

                        thrift_library(
                          name='remote-thrifts',
                          sources=[],
                          dependencies=[
                            thrift_jar(org='foo', name='bop', rev='0.0.1'),
                            jar_library(
                              name='anon',
                              dependencies=[
                                thrift_jar(org='foo', name='bam', rev='0.0.1'),
                                pants('3rdparty:thrift-jar')
                              ]
                            ),
                            pants('3rdparty:thrift-jar')
                          ]
                        )
                        ''').strip())

    cls.create_target('invalid/direct',
                      dedent('''
                        thrift_library(
                          name='jar',
                          sources=[],
                          dependencies=[
                            jar(org='foo', name='baz', rev='0.0.1')
                          ]
                        )
                        ''').strip())

    cls.create_target('invalid/indirect',
                      dedent('''
                        thrift_library(
                          name='jar',
                          sources=[],
                          dependencies=[
                            pants('3rdparty:jar')
                          ]
                        )
                        ''').strip())

  def test_empty_dependencies(self):
    target = self.target('valid:empty')
    self.assertEquals(0, len(target.sources))
    self.assertEquals(0, len(target.dependencies))

  def test_valid_dependencies_thrift_library(self):
    target = self.target('valid:local-thrifts')
    self.assertEquals(0, len(target.sources))
    self.assertEquals(set([self.target('valid:empty'), self.target('valid:split')]),
                      set(target.dependencies))

  def test_valid_dependencies_thrift_jar(self):
    target = self.target('valid:remote-thrifts')
    self.assertEquals(0, len(target.sources))
    expected = set(self.target('3rdparty:thrift-jar').resolve())
    expected.update(self.target('valid:anon').resolve())
    expected.add(ThriftJar(org='foo', name='bop', rev='0.0.1'))
    expected.add(ThriftJar(org='foo', name='bam', rev='0.0.1'))
    self.assertEquals(expected, set(target.dependencies))

  def test_invalid_dependencies_direct(self):
    with pytest.raises(TargetDefinitionException):
      self.target('invalid/direct:jar')

  def test_invalid_dependencies_indirect(self):
    indirect = self.target('invalid/indirect:jar')
    with pytest.raises(TargetDefinitionException):
      # validation of dependencies is lazy so we access them here only to trip the check.
      self.assertTrue(len(indirect.dependencies) > 0)

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

from twitter.pants.base import ParseContext
from twitter.pants.targets.anonymous import AnonymousDeps
from twitter.pants.targets.jar_dependency import JarDependency
from twitter.pants.targets.jar_library import JarLibrary
from twitter.pants.targets.java_thrift_library import JavaThriftLibrary
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.extract import Extract

from . import TaskTest


class ExtractTest(TaskTest):

  def test_is_registered_jar(self):
    Extract._REGISTERED_JARS.clear()
    jar = JarDependency(org='com.twitter', name='mybird')

    self.assertRaises(AssertionError, Extract.is_registered_jar, org=None, name=jar.name)
    self.assertRaises(AssertionError, Extract.is_registered_jar, org=jar.org, name=None)

    self.assertFalse(Extract.is_registered_jar(jar.org, jar.name))
    Extract._register_jar(jar)
    self.assertTrue(Extract.is_registered_jar(jar.org, jar.name))

  def test_compiled_idl(self):
    buildfile = 'test_compiled_idl/a'
    with pytest.raises(TaskError):
      with ParseContext.temp():
        Extract.compiled_idl(idl_deps='wrong type')

    self.create_target(buildfile, dedent('''
      thrift_library(name='mybird', sources=None)
      '''))
    self.create_target(buildfile, dedent('''
      thrift_library(name='urbird', sources=None)
      '''))
    idl_deps = [self.target('%s:mybird' % buildfile),
                self.target('%s:urbird' % buildfile)]

    self.assertTrue(isinstance(Extract.compiled_idl(idl_deps=idl_deps),
                               AnonymousDeps))
    lib = Extract.compiled_idl(idl_deps=idl_deps, name='margot')
    self.assertTrue(isinstance(lib, JarLibrary))

  def test__register_library(self):
    relpath = 'test__register_library/a'

    self.create_target(relpath, dedent('''
      thrift_library(name='mybird', sources=None)
      '''))
    self.create_target(relpath, dedent('''
      thrift_library(name='urbird', sources=None,
        dependencies=[pants(':mybird')])
      '''))

    lib = Extract._register_library(
      self.target('%s:mybird' % relpath))
    self.assertTrue(isinstance(lib, JavaThriftLibrary))
    self.assertDeps(lib)

    lib = Extract._register_library(self.target('%s:urbird' % relpath),
      generated_deps=[self.target('%s:__compiled_idl_mybird' % relpath)])
    self.assertDeps(lib, self.target('%s:__compiled_idl_mybird' % relpath))

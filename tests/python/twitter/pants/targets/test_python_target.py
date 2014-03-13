# ==================================================================================================
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
import unittest

from textwrap import dedent

from twitter.pants.base.parse_context import ParseContext
from twitter.pants.base.target import TargetDefinitionException
from twitter.pants.base_build_root_test import BaseBuildRootTest
from twitter.pants.targets.artifact import Artifact
from twitter.pants.targets.python_target import PythonTarget
from twitter.pants.targets.python_artifact import PythonArtifact
from twitter.pants.targets.repository import Repository
from twitter.pants.targets.sources import SourceRoot


class PythonTargetTest(BaseBuildRootTest):

  @classmethod
  def setUpClass(self):
    super(PythonTargetTest, self).setUpClass()
    SourceRoot.register(os.path.realpath(os.path.join(self.build_root, 'test_python_target')),
                        PythonTarget)

    self.create_target('test_thrift_replacement', dedent('''
      python_thrift_library(name='one',
        sources=['thrift/keyword.thrift'],
        dependencies=None
      )
    '''))

  def test_validation(self):
    with ParseContext.temp('PythonTargetTest/test_validation'):

      # Adding a JVM Artifact as a provides on a PythonTarget doesn't make a lot of sense. This test
      # sets up that very scenario, and verifies that pants throws a TargetDefinitionException.
      self.assertRaises(TargetDefinitionException, PythonTarget, name="one", sources=[],
        provides=Artifact(org='com.twitter', name='one-jar',
        repo=Repository(name='internal', url=None, push_db=None, exclusives=None)))

      name = "test-with-PythonArtifact"
      pa = PythonArtifact(name='foo', version='1.0', description='foo')

      # This test verifies that adding a 'setup_py' provides to a PythonTarget is okay.
      self.assertEquals(PythonTarget(name=name, provides=pa, sources=[]).name, name)
      name = "test-with-none"

      # This test verifies that having no provides is okay.
      self.assertEquals(PythonTarget(name=name, provides=None, sources=[]).name, name)

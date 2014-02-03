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

import os

from textwrap import dedent

from twitter.pants.base import ParseContext
from twitter.pants.build_root_test import BuildRootTest
from twitter.pants.targets.resources import WithLegacyResources

class WithLegacyResourcesTest(BuildRootTest):

  @classmethod
  def setUpClass(cls):
    super(WithLegacyResourcesTest, cls).setUpClass()

    cls.resource_path = 'a/b.js'
    cls.create_file(os.path.join('resources', cls.resource_path), 'alert("!");')

    cls.create_target('resources', "resources(name='test', sources=['%s'])" % cls.resource_path)
    cls.resources = cls.target('resources/BUILD:test')

  def test_legacy(self):
    self.create_dir('main')
    with ParseContext.temp('main'):
      target = WithLegacyResources('test', resources=['a/b.js'])
      self.assertEquals([self.resources], target.resources)
      self.assertEquals([self.resource_path], self.resources.sources)

  def test_pointer(self):
    self.create_target('a/b/c', dedent('''
      from twitter.pants.targets.resources import WithLegacyResources
      WithLegacyResources(name='jake', resources=pants('resources:test'))
      ''').strip())
    jake = self.target('a/b/c/BUILD:jake')
    self.assertEquals([self.resources], jake.resources)

  def test_pointer_list(self):
    self.create_target('d/e/f', dedent('''
      dependencies(name='ref', dependencies=[pants('resources:test')])

      from twitter.pants.targets.resources import WithLegacyResources
      WithLegacyResources(name='jane', resources=[pants('resources:test'), pants(':ref')])
      ''').strip())
    jane = self.target('d/e/f/BUILD:jane')
    self.assertEquals([self.resources, self.resources], jane.resources)

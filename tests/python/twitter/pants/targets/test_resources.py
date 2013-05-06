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
from twitter.pants.base_build_root_test import BaseBuildRootTest
from twitter.pants.targets.resources import WithLegacyResources


class WithLegacyResourcesTest(BaseBuildRootTest):

  @classmethod
  def setUpClass(cls):
    super(WithLegacyResourcesTest, cls).setUpClass()

    cls.resource_path = 'a/b.js'
    cls.create_file(os.path.join('main/resources', cls.resource_path), 'alert("!");')

  def test_legacy(self):
    self.create_dir('main/src')
    self.create_target('main', dedent('''
      from twitter.pants.targets.resources import WithLegacyResources
      source_root('main', WithLegacyResources)
      ''').strip())
    self.create_dir('main/resources')
    with ParseContext.temp('main/src'):
      target = WithLegacyResources('test', resources=['a/b.js'])
      self.assertEqual(1, len(target.resources))
      resources = target.resources.pop()
      self.assertEquals([self.resource_path], resources.sources)

  def _create_resources(self):
    self.create_target('main/resources',
                       "resources(name='test', sources=['%s'])" % self.resource_path)
    return self.target('main/resources/BUILD:test')

  def test_pointer(self):
    resources = self._create_resources()
    self.create_target('a/b/c', dedent('''
      from twitter.pants.targets.resources import WithLegacyResources
      WithLegacyResources(name='jake', resources=pants('main/resources:test'))
      ''').strip())
    jake = self.target('a/b/c/BUILD:jake')
    self.assertEquals([resources], jake.resources)

  def test_pointer_list(self):
    resources = self._create_resources()
    self.create_target('d/e/f', dedent('''
      dependencies(name='ref', dependencies=[pants('main/resources:test')])

      from twitter.pants.targets.resources import WithLegacyResources
      WithLegacyResources(name='jane', resources=[pants('main/resources:test'), pants(':ref')])
      ''').strip())
    jane = self.target('d/e/f/BUILD:jane')
    self.assertEquals([resources, resources], jane.resources)

  def test_mixed_legacy_and_pointer(self):
    self._create_resources()
    self.create_target(self.test_mixed_legacy_and_pointer.__name__, dedent('''
      from twitter.pants.targets.resources import WithLegacyResources
      WithLegacyResources(name='margot', resources=[pants('main/resources:test'), 'margot.txt'])
      ''').strip())
    self.assertRaises(ValueError, self.target,
                      '%s:margot' % self.test_mixed_legacy_and_pointer.__name__)

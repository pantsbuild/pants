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

from twitter.pants.base_build_root_test import BaseBuildRootTest


class MavenLayoutTest(BaseBuildRootTest):
  @classmethod
  def setUpClass(cls):
    super(MavenLayoutTest, cls).setUpClass()

    cls.create_target('projectB/src/main/scala', 'scala_library(name="test", sources=[])')
    cls.create_file('projectB/BUILD', 'maven_layout()')

    cls.create_target('projectA/subproject/src/main/java', 'java_library(name="test", sources=[])')
    cls.create_file('BUILD', 'maven_layout("projectA/subproject")')

  def test_layout_here(self):
    self.assertEqual('projectB/src/main/scala',
                     self.target('projectB/src/main/scala:test').target_base)

  def test_subproject_layout(self):
    self.assertEqual('projectA/subproject/src/main/java',
                     self.target('projectA/subproject/src/main/java:test').target_base)

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

import unittest

from textwrap import dedent

from twitter.pants.base_build_root_test import BaseBuildRootTest
from twitter.pants.base.parse_context import ParseContext
from twitter.pants.targets.jvm_binary import Bundle

class BundleTest(BaseBuildRootTest):

  def test_bundle_filemap_dest_bypath(self):
    self.create_dir('src/java/org/archimedes/buoyancy/config')
    self.create_file('src/java/org/archimedes/buoyancy/config/densities.xml')
    self.create_target('src/java/org/archimedes/buoyancy/BUILD', dedent('''
      jvm_app(name='buoyancy',
        binary=jvm_binary(name='unused'),
        bundles=bundle().add('config/densities.xml'))
    '''))
    app = self.target('src/java/org/archimedes/buoyancy')
    # after one big refactor, ../../../../../ snuck into this path:
    self.assertEquals(app.bundles[0].filemap.values()[0],
                      'config/densities.xml')

  def test_bundle_filemap_dest_byglobs(self):
    self.create_dir('src/java/org/archimedes/tub/config')
    self.create_file('src/java/org/archimedes/tub/config/one.xml')
    self.create_file('src/java/org/archimedes/tub/config/two.xml')
    self.create_target('src/java/org/archimedes/tub/BUILD', dedent('''
      jvm_app(name='tub',
        binary=jvm_binary(name='unused'),
        bundles=bundle().add(globs('config/*.xml')))
    '''))
    app = self.target('src/java/org/archimedes/tub')
    for k in app.bundles[0].filemap.keys():
      if k.endswith('archimedes/tub/config/one.xml'):
        onexml_key = k
    self.assertEquals(app.bundles[0].filemap[onexml_key],
                      'config/one.xml')

  def test_bundle_filemap_dest_relative(self):
    self.create_dir('src/java/org/archimedes/crown/gold/config')
    self.create_file('src/java/org/archimedes/crown/gold/config/five.xml')
    self.create_target('src/java/org/archimedes/crown/BUILD', dedent('''
      jvm_app(name='crown',
        binary=jvm_binary(name='unused'),
        bundles=bundle(relative_to='gold').add('gold/config/five.xml'))
    '''))
    app = self.target('src/java/org/archimedes/crown')
    for k in app.bundles[0].filemap.keys():
      if k.endswith('archimedes/crown/gold/config/five.xml'):
        fivexml_key = k
    self.assertEquals(app.bundles[0].filemap.values()[0],
                      'config/five.xml')

  def test_bundle_add_add(self):
    self.create_dir('src/java/org/archimedes/volume/config/stone')
    self.create_file('src/java/org/archimedes/volume/config/stone/dense.xml')
    self.create_dir('src/java/org/archimedes/volume/config')
    self.create_file('src/java/org/archimedes/volume/config/metal/dense.xml')
    self.create_target('src/java/org/archimedes/volume/BUILD', dedent('''
      jvm_app(name='volume',
        binary=jvm_binary(name='unused'),
        bundles=bundle(relative_to='config')
          .add('config/stone/dense.xml')
          .add('config/metal/dense.xml'))
    '''))
    app = self.target('src/java/org/archimedes/volume')
    for k in app.bundles[0].filemap.keys():
      if k.endswith('archimedes/volume/config/stone/dense.xml'):
        stonexml_key = k
    self.assertEquals(app.bundles[0].filemap[stonexml_key],
                      'stone/dense.xml')

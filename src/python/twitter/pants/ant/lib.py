# ==================================================================================================
# Copyright 2011 Twitter, Inc.
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

from twitter.pants.base.generator import Generator
from twitter.pants.base.builder import Builder
from twitter.pants import has_jvm_targets, is_test

import bang
import ide
import os
import shutil
import subprocess
import traceback
import pkgutil

TRANSITIVITY_NONE = 'none'
TRANSITIVITY_SOURCES = 'sources'
TRANSITIVITY_TESTS = 'tests'
TRANSITIVITY_ALL = 'all'

_TEMPLATE_BASEDIR = 'templates'

class AntBuilder(Builder):

  @classmethod
  def generate_ivy(cls, root_dir, output_filename, target):
    """Outputs an ivy.xml file to output_filename for the given java target"""

    AntBuilder._check_target(target)

    library_template_data = target._create_template_data()
    AntBuilder._generate(root_dir, 'ivy', library_template_data, output_filename)

  @classmethod
  def _generate(cls, root_dir, template, template_data, output_filename):
    with open(output_filename, 'w') as output:
      template_path = os.path.join(_TEMPLATE_BASEDIR, '%s.mk' % template)
      generator = Generator(pkgutil.get_data(__name__, template_path),
          root_dir = root_dir, lib = template_data)
      generator.write(output)

  @classmethod
  def _check_target(cls, target):
    assert has_jvm_targets([target]),\
      "AntBuilder can only build jvm targets, given %s" % str(target)

  def __init__(self, ferror, root_dir, is_ide, ide_transitivity):
    Builder.__init__(self, ferror, root_dir)
    self.is_ide = is_ide
    self.ide_transitivity = ide_transitivity

  def build(self, targets, args):
    _, _, result = self.generate_and_build(targets, args)
    return result

  def generate_and_build(self, targets, args, name = None):
    java_target = self._resolve_targets(targets, name)

    extrabuildflags = set()

    workspace_root = os.path.join(self.root_dir, '.pants.d')
    if not os.path.exists(workspace_root):
      os.makedirs(workspace_root)

    buildxml, ivyxml = self.create_ant_builds(workspace_root, dict(), extrabuildflags, java_target)

    buildflags = []
    if extrabuildflags:
      buildflags.extend(extrabuildflags)

    # TODO(John Sirois): introduce java_binary and only allow buildflags from those and disallow
    # java_binary as a pants dep - they must be leaf
    if java_target.buildflags:
      buildflags.extend(java_target.buildflags)

    antargs = [ 'ant', '-f', '"%s"' % buildxml ]

    if buildflags:
      antargs.extend(buildflags)

    if args:
      antargs.extend(args)

    print 'AntBuilder executing (ANT_OPTS="%s") %s' % (os.environ['ANT_OPTS'], ' '.join(antargs))
    return buildxml, ivyxml, subprocess.call(antargs)

  def create_ant_builds(self, workspace_root, targets, flags, target):
    if target._id in targets:
      return targets[target._id]

    try:
      library_template_data = target._create_template_data()
    except:
      self.ferror("Problem creating template data for %s(%s): %s" %
        (type(target).__name__, target.address, traceback.format_exc()))

    workspace = os.path.join(workspace_root, library_template_data.id)
    if not os.path.exists(workspace):
      os.makedirs(workspace)

    ivyxml = os.path.join(workspace, 'ivy.xml')
    AntBuilder._generate(self.root_dir, 'ivy', library_template_data, ivyxml)

    buildxml = os.path.join(workspace, 'build.xml')
    if target.custom_antxml_path:
      shutil.copyfile(target.custom_antxml_path, buildxml)
      pants_buildxml = os.path.join(workspace, 'pants-build.xml')
      flags.add('-Dpants.build.file=pants-build.xml')
    else:
      pants_buildxml = buildxml

    build_template = os.path.join(library_template_data.template_base, 'build')

    AntBuilder._generate(self.root_dir, build_template, library_template_data, pants_buildxml)

    targets[target._id] = buildxml

    for additional_library in target.internal_dependencies:
      self.create_ant_builds(workspace_root, targets, flags, additional_library)

    return buildxml, ivyxml

  def _resolve_targets(self, targets, name = None):
    for target in targets:
      AntBuilder._check_target(target)

    foil = list(targets)[0]
    if self.is_ide:
      def is_transitive():
        if self.ide_transitivity == TRANSITIVITY_TESTS:
          return is_test
        if self.ide_transitivity == TRANSITIVITY_ALL:
          return lambda target: True
        if self.ide_transitivity == TRANSITIVITY_NONE:
          return lambda target: False
        if self.ide_transitivity == TRANSITIVITY_SOURCES:
          return lambda target: not is_test(target)

      is_transitive = is_transitive()
      return foil.do_in_context(lambda: ide.extract_target(targets, is_transitive, name))
    elif len(targets) > 1 or foil.address.is_meta:
      return foil.do_in_context(lambda: bang.extract_target(targets, name))
    else:
      return foil

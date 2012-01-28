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

__author__ = 'Mark McBride'

from . import Command

import json
import os
import shutil
import subprocess
import traceback
from copy import copy

from twitter.common.collections import OrderedSet
from twitter.pants import is_exported, is_jvm
from twitter.pants.base import Address, Target
from twitter.pants.targets import JavaLibrary
from twitter.pants.ant import AntBuilder, bang

class IvyResolve(Command):
  """Resolves ivy dependencies to a local directory, obviating the need for an explicit resolve per build."""

  __command__ = 'ivy_resolve'

  @staticmethod
  def _is_resolvable(target):
    return is_jvm(target)


  def setup_parser(self, parser, args):
    parser.set_usage("%prog ivy_resolve ([spec]...)")
    parser.add_option("--clean", action="store_true", dest = "clean", default = False,
                      help = "removes local libs directories")
    parser.add_option("--intransitive", action="store_true", dest = "intransitive", default = False,
                      help = "only resolve dependencies for given spec")
    parser.epilog = """Links ivy libs to a local directory, obviating the need for an explicit ivy resolve"""

  def __init__(self, root_dir, parser, argv):
    Command.__init__(self, root_dir, parser, argv)

    self.clean = self.options.clean
    self.intransitive = self.options.intransitive
    # TODO: def not shared with lib.py
    self.workspace_root = os.path.join(root_dir, '.pants.d')
    self.ivy_jar = os.path.join(root_dir, 'build-support', 'ivy', 'lib', 'ivy-2.2.0.jar')
    self.ivy_settings = os.path.join(root_dir, 'build-support', 'ivy', 'ivysettings.xml')

    if self.args:
      self.targets = self._parse_targets(OrderedSet(), root_dir)
    else:
      def get_targets():
        for address in Command.scan_addresses(root_dir):
          target = Target.get(address)
          if IvyResolve._is_resolvable(target):
            yield target
      self.targets = list(get_targets())

  def _parse_targets(self, targets, root_dir):
    for spec in self.args:
      try:
        address = Address.parse(root_dir, spec)
      except:
        self.error("Problem parsing spec %s: %s" % (spec, traceback.format_exc()))

      try:
        target = Target.get(address)
      except:
        self.error("Problem parsing target %s: %s" % (address, traceback.format_exc()))

      if address.is_meta:
        print "target is meta"
        target = target.do_in_context(lambda: bang.extract_target([target], None))
      if not IvyResolve._is_resolvable(target):
        self.error("Target: %s is not resolvable" % address)

      targets.add(target)

    if not self.intransitive:
      def add_targets(ttarget):
        if hasattr(ttarget, 'internal_dependencies'):
          for dep in ttarget.internal_dependencies:
            if IvyResolve._is_resolvable(dep):
              targets.add(dep)
            else:
              print "skipping %s as it's not ivy resolvable" % (dep.name)
      target.walk(add_targets)

    return targets


  def execute(self):
    for target in self.targets:
      print "creating ivyxml for " + target.name
      ivyxml = self.create_ivyxml(target)
      libs_dir = os.path.join(os.path.dirname(ivyxml), 'libs')
      print "cleaning " + libs_dir
      if os.path.exists(libs_dir):
        shutil.rmtree(libs_dir)

      if not self.clean:
        self.build_target_dir_fileset(target, ivyxml)
        for configuration in ['default', 'test']:
          self.build_libs_dir(target, ivyxml, configuration)

  def build_target_dir_fileset(self, target, ivyxml):
    print "writing target_dir fileset for " + target.name
    target_dirs = OrderedSet()
    def add_targets(ttarget):
      target_dirs.add(ttarget._create_template_data().id)

    target.walk(add_targets)
    target_dirs_file_name = os.path.join(os.path.dirname(ivyxml), "dependency_target_dirs.txt")
    target_dirs_file = open(target_dirs_file_name, "w")
    for target_dir in target_dirs:
      target_dirs_file.write(target_dir + "/jvm\n")
    target_dirs_file.close

  def create_ivyxml(self, target):
    builder = AntBuilder(self.error, self.workspace_root, False, False)
    buildxml, ivyxml = builder.create_ant_builds(self.workspace_root, dict(), set(), target)
    return ivyxml

  def build_libs_dir(self, target, ivyxml, conf):
    all_deps = OrderedSet()
    all_sources = ['dummy']
    def extract_jars(ttarget):
      for jar_dep in ttarget.jar_dependencies:
        if jar_dep.rev:
          all_deps.add(copy(jar_dep))
    target.walk(extract_jars)
    def create_meta_target():
      return JavaLibrary(target.name + '.deps',
                         all_sources,
                         dependencies = all_deps,
                         is_meta = True)

    meta_target = target.do_in_context(create_meta_target)

    local_ivy = os.path.abspath(ivyxml) + ".local"
    AntBuilder.generate_ivy(self.workspace_root, local_ivy, meta_target)
    libs_dir = os.path.join(os.path.dirname(os.path.abspath(ivyxml)), 'libs', conf)
    if not os.path.exists(libs_dir):
      os.makedirs(libs_dir)
    classpath_result = subprocess.call([
        'java',
        '-jar', self.ivy_jar,
        '-settings', self.ivy_settings,
        '-ivy', local_ivy,
        '-confs', conf,
        '-retrieve',
        "%s/[artifact]-[revision].[ext]" % libs_dir,
        "-symlink",
        "-sync"])


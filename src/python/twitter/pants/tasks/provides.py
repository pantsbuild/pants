# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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

__author__ = 'Benjy Weinberger'

import os
import sys

from twitter.common.collections import OrderedSet
from twitter.common.contextutil import open_zip as open_jar
from twitter.pants import is_jar_dependency, is_jar_library, is_jvm
from twitter.pants.tasks import Task
from twitter.pants.tasks.ivy_utils import IvyModuleRef, IvyUtils
from twitter.pants.targets.jvm_binary import JvmBinary


class Provides(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("outdir"), dest="provides_outdir",
      help="Emit provides outputs into this directory.")
    option_group.add_option(mkflag("transitive"), default=False,
      action="store_true", dest='provides_transitive',
      help="Shows the symbols provided not just by the specified targets but by all their transitive dependencies.")
    option_group.add_option(mkflag("also-write-to-stdout"), default=False,
      action="store_true", dest='provides_also_write_to_stdout',
      help="If set, also outputs the provides information to stdout.")

  def __init__(self, context):
    Task.__init__(self, context)
    self.ivy_utils = IvyUtils(context, context.config.get('ivy', 'cache_dir'))
    self.confs = context.config.getlist('ivy', 'confs')
    self.target_roots = context.target_roots
    self.transitive = context.options.provides_transitive
    self.workdir = context.config.get('provides', 'workdir')
    self.outdir = context.options.provides_outdir or self.workdir
    self.also_write_to_stdout = context.options.provides_also_write_to_stdout or False
    # Create a fake target, in case we were run directly on a JarLibrary containing nothing but JarDependencies.
    # TODO(benjy): Get rid of this special-casing of jar dependencies.
    context.add_new_target(self.workdir,
      JvmBinary,
      name='provides',
      dependencies=self.target_roots,
      configurations=self.confs)
    context.products.require('jars')

  def execute(self, targets):
    for conf in self.confs:
      outpath = os.path.join(self.outdir, '%s.%s.provides' % (self.ivy_utils.identify()[1], conf))
      if self.transitive:
        outpath += '.transitive'
      ivyinfo = self.ivy_utils.parse_xml_report(conf)
      jar_paths = OrderedSet()
      for root in self.target_roots:
        jar_paths.update(self.get_jar_paths(ivyinfo, root, conf))

      with open(outpath, 'w') as outfile:
        def do_write(s):
          outfile.write(s)
          if self.also_write_to_stdout:
            sys.stdout.write(s)
        for jar in jar_paths:
          do_write('# from jar %s\n' % jar)
          for line in self.list_jar(jar):
            if line.endswith('.class'):
              class_name = line[:-6].replace('/', '.')
              do_write(class_name)
              do_write('\n')
      print 'Wrote provides information to %s' % outpath

  def get_jar_paths(self, ivyinfo, target, conf):
    jar_paths = OrderedSet()
    if is_jar_library(target):
      # Jar library proxies jar dependencies or jvm targets, so the jars are just those of the
      # dependencies.
      for paths in [ self.get_jar_paths(ivyinfo, dep, conf) for dep in target.dependencies ]:
        jar_paths.update(paths)
    elif is_jar_dependency(target):
      ref = IvyModuleRef(target.org, target.name, target.rev, conf)
      jar_paths.update(self.get_jar_paths_for_ivy_module(ivyinfo, ref))
    elif is_jvm(target):
      for basedir, jars in self.context.products.get('jars').get(target).items():
        jar_paths.update([os.path.join(basedir, jar) for jar in jars])
      if self.transitive:
        for dep in target.dependencies:
          jar_paths.update(self.get_jar_paths(ivyinfo, dep, conf))

    return jar_paths

  def get_jar_paths_for_ivy_module(self, ivyinfo, ref):
    jar_paths = OrderedSet()
    module = ivyinfo.modules_by_ref[ref]
    jar_paths.update([a.path for a in module.artifacts])
    if self.transitive:
      for dep in ivyinfo.deps_by_caller.get(ref, []):
        jar_paths.update(self.get_jar_paths_for_ivy_module(ivyinfo, dep))
    return jar_paths

  def list_jar(self, path):
    with open_jar(path, 'r') as jar:
      return jar.namelist()


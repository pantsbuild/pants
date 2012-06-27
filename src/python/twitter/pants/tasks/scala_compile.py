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

__author__ = 'John Sirois'

import os
import textwrap

from collections import defaultdict

from twitter.common.dirutil import safe_mkdir, safe_open

from twitter.pants import is_scala, is_scalac_plugin
from twitter.pants.targets.scala_library import ScalaLibrary
from twitter.pants.targets.scala_tests import ScalaTests
from twitter.pants.targets import resolve_target_sources
from twitter.pants.targets.internal import InternalTarget
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.binary_utils import nailgun_profile_classpath
from twitter.pants.tasks.jvm_compiler_dependencies import Dependencies
from twitter.pants.tasks.nailgun_task import NailgunTask


# Well known metadata file required to register scalac plugins with nsc.
_PLUGIN_INFO_FILE = 'scalac-plugin.xml'


class ScalaCompile(NailgunTask):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    NailgunTask.setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("warnings"), mkflag("warnings", negate=True),
                            dest="scala_compile_warnings", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Compile scala code with all configured warnings "
                                 "enabled.")

    option_group.add_option(mkflag("flatten"), mkflag("flatten", negate=True),
                            dest="scala_compile_flatten", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Compile scala code for all dependencies in a "
                                 "single pass.")

  def __init__(self, context):
    NailgunTask.__init__(self, context, workdir=context.config.get('scala-compile', 'nailgun_dir'))

    self._compile_profile = context.config.get('scala-compile', 'compile-profile')
    self._depemitter_profile = context.config.get('scala-compile', 'dependencies-plugin-profile')

    # All scala targets implicitly depend on the selected scala runtime.
    scaladeps = []
    for spec in context.config.getlist('scala-compile', 'scaladeps'):
      scaladeps.extend(context.resolve(spec))
    for target in context.targets(is_scala):
      target.update_dependencies(scaladeps)

    workdir = context.config.get('scala-compile', 'workdir')
    self._classes_dir = os.path.join(workdir, 'classes')
    self._resources_dir = os.path.join(workdir, 'resources')

    self._main = context.config.get('scala-compile', 'main')

    self._args = context.config.getlist('scala-compile', 'args')
    if context.options.scala_compile_warnings:
      self._args.extend(context.config.getlist('scala-compile', 'warning_args'))
    else:
      self._args.extend(context.config.getlist('scala-compile', 'no_warning_args'))

    self._flatten = context.options.scala_compile_flatten
    self._confs = context.config.getlist('scala-compile', 'confs')
    self._depfile = os.path.join(workdir, 'dependencies')

  def execute(self, targets):
    if not self._flatten and len(targets) > 1:
      topologically_sorted_targets = filter(is_scala, reversed(InternalTarget.sort_targets(targets)))
      for target in topologically_sorted_targets:
        self.execute([target])
      return

    self.context.log.info('Compiling targets %s' % str(targets))

    scala_targets = filter(is_scala, targets)
    if scala_targets:
      with self.context.state('classpath', []) as cp:
        for conf in self._confs:
          cp.insert(0, (conf, self._resources_dir))
          cp.insert(0, (conf, self._classes_dir))

      with self.changed(scala_targets, invalidate_dependants=True) as changed_targets:
        sources_by_target = self.calculate_sources(changed_targets)
        if sources_by_target:
          sources = reduce(lambda all, sources: all.union(sources), sources_by_target.values())
          if not sources:
            self.context.log.warn('Skipping scala compile for targets with no sources:\n  %s' %
                                  '\n  '.join(str(t) for t in sources_by_target.keys()))
          else:
            classpath = [jar for conf, jar in cp if conf in self._confs]
            result = self.compile(classpath, sources)
            if result != 0:
              raise TaskError('%s returned %d' % (self._main, result))

      if self.context.products.isrequired('classes'):
        genmap = self.context.products.get('classes')

        # Map generated classes to the owning targets and sources.
        dependencies = Dependencies(self._classes_dir, self._depfile)
        for target, classes_by_source in dependencies.findclasses(targets).items():
          for source, classes in classes_by_source.items():
            genmap.add(source, self._classes_dir, classes)
            genmap.add(target, self._classes_dir, classes)

        # TODO(John Sirois): Map target.resources in the same way
        # Create and Map scala plugin info files to the owning targets.
        for target in targets:
          if is_scalac_plugin(target) and target.classname:
            basedir = self.write_plugin_info(target)
            genmap.add(target, basedir, [_PLUGIN_INFO_FILE])

  def calculate_sources(self, targets):
    sources = defaultdict(set)
    def collect_sources(target):
      src = (os.path.join(target.target_base, source)
             for source in target.sources if source.endswith('.scala'))
      if src:
        sources[target].update(src)

        if (isinstance(target, ScalaLibrary) or isinstance(target, ScalaTests)) and (
            target.java_sources):
          sources[target].update(resolve_target_sources(target.java_sources, '.java'))

    for target in targets:
      collect_sources(target)
    return sources

  def compile(self, classpath, sources):
    safe_mkdir(self._classes_dir)

    compiler_classpath = nailgun_profile_classpath(self, self._compile_profile)

    # TODO(John Sirois): separate compiler profile from runtime profile
    args = [
      '-classpath', ':'.join(compiler_classpath + classpath),
      '-d', self._classes_dir,

      # Support for outputting a dependencies file of source -> class
      '-Xplugin:%s' % self.get_depemitter_plugin(),
      '-P:depemitter:file:%s' % self._depfile
    ]

    args.extend(self._args)
    args.extend(sources)
    self.context.log.debug('Executing: %s %s' % (self._main, ' '.join(args)))
    return self.runjava(self._main, classpath=compiler_classpath, args=args)

  def get_depemitter_plugin(self):
    depemitter_classpath = nailgun_profile_classpath(self, self._depemitter_profile)
    depemitter_jar = depemitter_classpath.pop()
    if depemitter_classpath:
      raise TaskError('Expected only 1 jar for the depemitter plugin, '
                      'found these extra: ' % depemitter_classpath)
    return depemitter_jar

  def write_plugin_info(self, target):
    basedir = os.path.join(self._resources_dir, target.id)
    with safe_open(os.path.join(basedir, _PLUGIN_INFO_FILE), 'w') as f:
      f.write(textwrap.dedent('''
        <plugin>
          <name>%s</name>
          <classname>%s</classname>
        </plugin>
      ''' % (target.plugin, target.classname)).strip())
    return basedir

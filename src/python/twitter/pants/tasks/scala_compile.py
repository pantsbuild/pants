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

from collections import defaultdict
import os

from twitter.common.dirutil import safe_mkdir
from twitter.pants import get_buildroot, is_scala
from twitter.pants.targets.scala_library import ScalaLibrary
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.binary_utils import nailgun_profile_classpath
from twitter.pants.tasks.nailgun_task import NailgunTask

class ScalaCompile(NailgunTask):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("warnings"), mkflag("warnings", negate=True),
                            dest="scala_compile_warnings", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Compile scala code with all configured warnings "
                                 "enabled.")

  def __init__(self, context, output_dir=None, classpath=None, main=None, args=None, confs=None):
    workdir = context.config.get('scala-compile', 'nailgun_dir')
    NailgunTask.__init__(self, context, workdir=workdir)

    self._compile_profile = context.config.get('scala-compile', 'compile-profile')

    # All scala targets implicitly depend on the selected scala runtime.
    scaladeps = []
    for spec in context.config.getlist('scala-compile', 'scaladeps'):
      scaladeps.extend(context.resolve(spec))
    for target in context.targets(is_scala):
      target.update_dependencies(scaladeps)

    self._compiler_classpath = classpath
    self._output_dir = output_dir or context.config.get('scala-compile', 'workdir')
    self._main = main or context.config.get('scala-compile', 'main')

    self._args = args or context.config.getlist('scala-compile', 'args')
    if context.options.scala_compile_warnings:
      self._args.extend(context.config.getlist('scala-compile', 'warning_args'))
    else:
      self._args.extend(context.config.getlist('scala-compile', 'no_warning_args'))

    self._confs = confs or context.config.getlist('scala-compile', 'confs')
    self._depfile = os.path.join(self._output_dir, 'dependencies')

  def execute(self, targets):
    scala_targets = filter(is_scala, targets)
    if scala_targets:
      with self.context.state('classpath', []) as cp:
        for conf in self._confs:
          cp.insert(0, (conf, self._output_dir))

      with self.changed(scala_targets, invalidate_dependants=True) as changed_targets:
        bases, sources_by_target = self.calculate_sources(changed_targets)
        if sources_by_target:
            classpath = [jar for conf, jar in cp if conf in self._confs]
            result = self.compile(classpath, bases, sources_by_target)
            if result != 0:
              raise TaskError('%s returned %d' % (self._main, result))

      if self.context.products.isrequired('classes'):
        genmap = self.context.products.get('classes')
        _, sources = self.calculate_sources(scala_targets)
        for target, sources in sources.items():
          classes = ScalaCompiler.findclasses(self._output_dir, sources, self._depfile)
          genmap.add(target, self._output_dir, classes)

  def calculate_sources(self, targets):
    bases = set()
    sources = defaultdict(set)
    def collect_sources(target):
      src = (os.path.join(target.target_base, source)
             for source in target.sources if source.endswith('.scala'))
      if src:
        bases.add(target.target_base)
        sources[target].update(src)

        if isinstance(target, ScalaLibrary) and target.java_sources:
          # TODO(John Sirois): XXX this assumes too much about project layouts - fix
          base_parent = os.path.dirname(target.target_base)
          sibling_java_base = os.path.join(base_parent, 'java')

          java_src = (os.path.join(sibling_java_base, source)
                      for source in target.java_sources if source.endswith('.java'))
          if java_src:
            bases.add(sibling_java_base)
            sources[target].update(java_src)

    for target in targets:
      collect_sources(target)
    return bases, sources

  def compile(self, classpath, bases, sources_by_target):
    safe_mkdir(self._output_dir)

    compiler_classpath = (
      self._compiler_classpath
      or nailgun_profile_classpath(self, self._compile_profile)
    )
    self.ng('ng-cp', *compiler_classpath)

    # TODO(John Sirois): separate compiler profile from runtime profile
    args = [
      '-classpath', ':'.join(compiler_classpath + classpath),
      '-sourcepath', ':'.join(bases),
      '-d', self._output_dir,

      # TODO(John Sirois): dependencyfile requires the deprecated -make:XXX - transition to ssc
      '-dependencyfile', self._depfile,
      '-make:transitivenocp'
    ]
    args.extend(self._args)
    args.extend(reduce(lambda all, sources: all | sources, sources_by_target.values()))
    self.context.log.debug('Executing: %s %s' % (self._main, ' '.join(args)))
    return self.ng(self._main, *args)


class ScalaCompiler(object):
  _SECTIONS = ['classpath', 'sources', 'source_to_class']

  @staticmethod
  def findclasses(outputdir, sources, depfile):
    classes = []
    with open(depfile, 'r') as deps:
      section = 0
      for dep in deps.readlines():
        line = dep.strip()
        if '-------' == line:
          section += 1
        elif ScalaCompiler._SECTIONS[section] == 'source_to_class':
          mapping = line.split('->')
          sourcefile = os.path.relpath(os.path.join(outputdir, mapping[0].strip()), get_buildroot())
          if sourcefile in sources:
            classfile = os.path.relpath(os.path.join(outputdir, mapping[1].strip()), outputdir)
            classes.append(classfile)
    return classes

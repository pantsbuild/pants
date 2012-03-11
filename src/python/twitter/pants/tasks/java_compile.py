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
import re

from twitter.common import log
from twitter.common.dirutil import safe_open, safe_mkdir
from twitter.pants import get_buildroot, is_apt
from twitter.pants.targets import JavaLibrary, JavaTests
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.binary_utils import nailgun_profile_classpath
from twitter.pants.tasks.nailgun_task import NailgunTask


# Well known metadata file to auto-register annotation processors with a java 1.6+ compiler
_PROCESSOR_INFO_FILE = 'META-INF/services/javax.annotation.processing.Processor'


_JMAKE_MAIN = 'com.sun.tools.jmake.Main'


class JavaCompile(NailgunTask):
  @staticmethod
  def _is_java(target):
    return is_apt(target) or isinstance(target, JavaLibrary) or isinstance(target, JavaTests)

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("warnings"), mkflag("warnings", negate=True),
                            dest="java_compile_warnings", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Compile java code with all configured warnings "
                                 "enabled.")

  def __init__(self, context):
    NailgunTask.__init__(self, context, workdir=context.config.get('java-compile', 'nailgun_dir'))

    workdir = context.config.get('java-compile', 'workdir')
    self._classes_dir = os.path.join(workdir, 'classes')
    self._resources_dir = os.path.join(workdir, 'resources')
    self._dependencies_file = os.path.join(workdir, 'dependencies')

    self._jmake_profile = context.config.get('java-compile', 'jmake-profile')
    self._compiler_profile = context.config.get('java-compile', 'compiler-profile')

    self._args = context.config.getlist('java-compile', 'args')
    if context.options.java_compile_warnings:
      self._args.extend(context.config.getlist('java-compile', 'warning_args'))
    else:
      self._args.extend(context.config.getlist('java-compile', 'no_warning_args'))

    self._confs = context.config.getlist('java-compile', 'confs')

  def execute(self, targets):
    java_targets = filter(JavaCompile._is_java, targets)
    if java_targets:
      with self.context.state('classpath', []) as cp:
        for conf in self._confs:
          cp.insert(0, (conf, self._resources_dir))
          cp.insert(0, (conf, self._classes_dir))

        with self.changed(java_targets, invalidate_dependants=True) as changed:
          sources_by_target, processors, fingerprint = self.calculate_sources(changed)
          if sources_by_target:
            sources = reduce(lambda all, sources: all.union(sources), sources_by_target.values())
            if not sources:
              self.context.log.warn('Skipping java compile for targets with no sources:\n  %s' %
                                    '\n  '.join(str(t) for t in sources_by_target.keys()))
            else:
              classpath = [jar for conf, jar in cp if conf in self._confs]
              result = self.compile(classpath, sources, fingerprint)
              if result != 0:
                raise TaskError('%s returned %d' % (_JMAKE_MAIN, result))

            if processors:
              # Produce a monolithic apt processor service info file for further compilation rounds
              # and the unit test classpath.
              processor_info_file = os.path.join(self._classes_dir, _PROCESSOR_INFO_FILE)
              if os.path.exists(processor_info_file):
                with safe_open(processor_info_file, 'r') as f:
                  for processor in f:
                    processors.add(processor.strip())
              self.write_processor_info(processor_info_file, processors)

      if self.context.products.isrequired('classes'):
        genmap = self.context.products.get('classes')

        # Map generated classes to the owning targets and sources.
        compiler = DependencyCompiler(self._classes_dir, self._dependencies_file)
        for target, classes_by_source in compiler.findclasses(targets).items():
          for source, classes in classes_by_source.items():
            genmap.add(source, self._classes_dir, classes)
            genmap.add(target, self._classes_dir, classes)

        # TODO(John Sirois): Map target.resources in the same way
        # 'Map' (rewrite) annotation processor service info files to the owning targets.
        for target in targets:
          if is_apt(target) and target.processors:
            basedir = os.path.join(self._resources_dir, target.id)
            processor_info_file = os.path.join(basedir, _PROCESSOR_INFO_FILE)
            self.write_processor_info(processor_info_file, target.processors)
            genmap.add(target, basedir, [_PROCESSOR_INFO_FILE])

  def calculate_sources(self, targets):
    sources = defaultdict(set)
    processors = set()
    def collect_sources(target):
      src = (os.path.join(target.target_base, source)
             for source in target.sources if source.endswith('.java'))
      if src:
        sources[target].update(src)
        if is_apt(target) and target.processors:
          processors.update(target.processors)

    for target in targets:
      collect_sources(target)
    return sources, processors, self.context.identify(targets)

  def compile(self, classpath, sources, fingerprint):
    safe_mkdir(self._classes_dir)

    jmake_classpath = nailgun_profile_classpath(self, self._jmake_profile)
    self.ng('ng-cp', *jmake_classpath)

    args = [
      '-classpath', ':'.join(classpath),
      '-d', self._classes_dir,
      '-pdb', os.path.join(self._classes_dir, '%s.dependencies.pdb' % fingerprint),
    ]

    compiler_classpath = nailgun_profile_classpath(self, self._compiler_profile)
    args.extend([
      '-jcpath', ':'.join(compiler_classpath),
      '-jcmainclass', 'com.twitter.common.tools.Compiler',
      '-C-dependencyfile', '-C%s' % self._dependencies_file
    ])

    args.extend(self._args)
    args.extend(sources)
    log.debug('Executing: %s %s' % (_JMAKE_MAIN, ' '.join(args)))
    return self.ng(_JMAKE_MAIN, *args)

  def write_processor_info(self, processor_info_file, processors):
    with safe_open(processor_info_file, 'w') as f:
      for processor in processors:
        f.write('%s\n' % processor)


class DependencyCompiler(object):
  _CLASS_FILE_NAME_PARSER = re.compile(r'(?:\$.*)*\.class$')

  def __init__(self, outputdir, depfile):
    self.outputdir = outputdir
    self.depfile = depfile

  def findclasses(self, targets):
    sources = set()
    target_by_source = dict()
    for target in targets:
      for source in target.sources:
        src = os.path.normpath(os.path.join(target.target_base, source))
        target_by_source[src] = target
        sources.add(src)

    classes_by_target_by_source = defaultdict(lambda: defaultdict(set))
    if os.path.exists(self.depfile):
      with open(self.depfile, 'r') as deps:
        for dep in deps.readlines():
          src, cls = dep.strip().split('->')
          sourcefile = os.path.relpath(os.path.join(self.outputdir, src.strip()), get_buildroot())
          if sourcefile in sources:
            classfile = os.path.relpath(os.path.join(self.outputdir, cls.strip()), self.outputdir)
            target = target_by_source[sourcefile]
            relsrc = os.path.relpath(sourcefile, target.target_base)
            classes_by_target_by_source[target][relsrc].add(classfile)
    return classes_by_target_by_source

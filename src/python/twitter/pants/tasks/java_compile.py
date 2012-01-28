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
from twitter.pants import is_apt
from twitter.pants.targets import JavaLibrary, JavaTests
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.binary_utils import nailgun_profile_classpath
from twitter.pants.tasks.nailgun_task import NailgunTask

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

  def __init__(self, context, output_dir=None, classpath=None, main=None, args=None, confs=None):
    self._profile = context.config.get('java-compile', 'profile')
    workdir = context.config.get('java-compile', 'nailgun_dir')
    NailgunTask.__init__(self, context, workdir=workdir)

    self._compiler_classpath = classpath
    self._output_dir = output_dir or context.config.get('java-compile', 'workdir')
    self._processor_service_info_file = \
        os.path.join(self._output_dir, 'META-INF/services/javax.annotation.processing.Processor')
    self._main = main or context.config.get('java-compile', 'main')

    self._args = args or context.config.getlist('java-compile', 'args')
    if context.options.java_compile_warnings:
      self._args.extend(context.config.getlist('java-compile', 'warning_args'))
    else:
      self._args.extend(context.config.getlist('java-compile', 'no_warning_args'))

    self._confs = confs or context.config.getlist('java-compile', 'confs')

  def execute(self, targets):
    java_targets = filter(JavaCompile._is_java, targets)
    if java_targets:
      with self.context.state('classpath', []) as cp:
        for conf in self._confs:
          cp.insert(0, (conf, self._output_dir))

        with self.changed(java_targets, invalidate_dependants=True) as changed:
          bases, sources_by_target, processors, fingerprint = self.calculate_sources(changed)
          if sources_by_target:
            classpath = [jar for conf, jar in cp if conf in self._confs]
            result = self.compile(classpath, bases, sources_by_target, fingerprint)
            if result != 0:
              raise TaskError('%s returned %d' % (self._main, result))

            if processors:
              if os.path.exists(self._processor_service_info_file):
                with safe_open(self._processor_service_info_file, 'r') as f:
                  for processor in f:
                    processors.add(processor.strip())
              with safe_open(self._processor_service_info_file, 'w') as f:
                for processor in processors:
                  f.write('%s\n' % processor)

      if self.context.products.isrequired('classes'):
        genmap = self.context.products.get('classes')
        classes_by_target = SunCompiler.findclasses(self._output_dir, targets)
        for target, classes in classes_by_target.items():
          genmap.add(target, self._output_dir, classes)

  def calculate_sources(self, targets):
    bases = set()
    sources = defaultdict(set)
    processors = set()
    def collect_sources(target):
      src = (os.path.join(target.target_base, source)
             for source in target.sources if source.endswith('.java'))
      if src:
        bases.add(target.target_base)
        sources[target].update(src)
        if is_apt(target) and target.processors:
          processors.update(target.processors)

    for target in targets:
      collect_sources(target)
    return bases, sources, processors, self.context.identify(targets)

  def compile(self, classpath, bases, sources_by_target, fingerprint):
    safe_mkdir(self._output_dir)

    compiler_classpath = self._compiler_classpath or nailgun_profile_classpath(self, self._profile)
    self.ng('ng-cp', *compiler_classpath)

    args = [
      '-classpath', ':'.join(classpath),

      # TODO(John Sirois): untangle the jmake -C hacks somehow
      '-C-sourcepath', '-C%s' % ':'.join(bases),
#      '-sourcepath', ':'.join(bases),

      '-d', self._output_dir,

      # TODO(John Sirois): untangle this jmake specific bit
      '-pdb', os.path.join(self._output_dir, '%s.dependencies.pdb' % fingerprint),
    ]
    args.extend(self._args)
    args.extend(reduce(lambda all, sources: all | sources, sources_by_target.values()))
    log.debug('Executing: %s %s' % (self._main, ' '.join(args)))
    return self.ng(self._main, *args)


class SunCompiler(object):
  _CLASS_FILE_NAME_PARSER = re.compile(r'(?:\$.*)*\.class$')

  @staticmethod
  def findclasses(outputdir, targets):
    sources_by_target = []
    for target in targets:
      sources_by_target.append((target, set(target.sources)))

    classes_by_target = defaultdict(list)
    for root, dirs, files in os.walk(outputdir):
      for file in files:
        path = os.path.relpath(os.path.join(root, file), outputdir)
        rel_sourcefile = SunCompiler._CLASS_FILE_NAME_PARSER.sub('.java', path)
        for target, rel_sources in sources_by_target:
          if rel_sourcefile in rel_sources:
            classes_by_target[target].append(path)
    return classes_by_target
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

from twitter.common import log
from twitter.common.dirutil import safe_open, safe_mkdir, touch
from twitter.pants import is_apt
from twitter.pants.base.target import Target
from twitter.pants.targets import JavaLibrary, JavaTests
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.binary_utils import nailgun_profile_classpath
from twitter.pants.tasks.jvm_compiler_dependencies import Dependencies
from twitter.pants.tasks.nailgun_task import NailgunTask


# Well known metadata file to auto-register annotation processors with a java 1.6+ compiler
_PROCESSOR_INFO_FILE = 'META-INF/services/javax.annotation.processing.Processor'


_JMAKE_MAIN = 'com.sun.tools.jmake.Main'


# From http://kenai.com/projects/jmake/sources/mercurial/content/src/com/sun/tools/jmake/Main.java?rev=26
# Main.mainExternal docs.
_JMAKE_ERROR_CODES = {
   -1: 'invalid command line option detected',
   -2: 'error reading command file',
   -3: 'project database corrupted',
   -4: 'error initializing or calling the compiler',
   -5: 'compilation error',
   -6: 'error parsing a class file',
   -7: 'file not found',
   -8: 'I/O exception',
   -9: 'internal jmake exception',
  -10: 'deduced and actual class name mismatch',
  -11: 'invalid source file extension',
  -12: 'a class in a JAR is found dependent on a class with the .java source',
  -13: 'more than one entry for the same class is found in the project',
  -20: 'internal Java error (caused by java.lang.InternalError)',
  -30: 'internal Java error (caused by java.lang.RuntimeException).'
}
# When executed via a subprocess return codes will be treated as unsigned
_JMAKE_ERROR_CODES.update((256+code, msg) for code, msg in _JMAKE_ERROR_CODES.items())


class JavaCompile(NailgunTask):
  @staticmethod
  def _has_java_sources(target):
    return is_apt(target) or isinstance(target, JavaLibrary) or isinstance(target, JavaTests)

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    NailgunTask.setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("warnings"), mkflag("warnings", negate=True),
                            dest="java_compile_warnings", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Compile java code with all configured warnings "
                                 "enabled.")

    option_group.add_option(mkflag("flatten"), mkflag("flatten", negate=True),
                            dest="java_compile_flatten",
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Compile java code for all dependencies in a "
                                 "single compilation.")

  def __init__(self, context):
    NailgunTask.__init__(self, context, workdir=context.config.get('java-compile', 'nailgun_dir'))

    self._flatten = \
      context.options.java_compile_flatten if context.options.java_compile_flatten is not None else \
      context.config.getbool('java-compile', 'default_to_flatten')

    workdir = context.config.get('java-compile', 'workdir')
    self._classes_dir = os.path.join(workdir, 'classes')
    self._resources_dir = os.path.join(workdir, 'resources')
    self._depfile_dir = os.path.join(workdir, 'depfiles')
    self._deps = Dependencies(self._classes_dir)

    self._jmake_profile = context.config.get('java-compile', 'jmake-profile')
    self._compiler_profile = context.config.get('java-compile', 'compiler-profile')

    self._args = context.config.getlist('java-compile', 'args')
    self._jvm_args = context.config.getlist('java-compile', 'jvm_args')

    if context.options.java_compile_warnings:
      self._args.extend(context.config.getlist('java-compile', 'warning_args'))
    else:
      self._args.extend(context.config.getlist('java-compile', 'no_warning_args'))

    self._confs = context.config.getlist('java-compile', 'confs')

  def product_type(self):
    return 'classes'

  def invalidate_for(self):
    return self._flatten

  def execute(self, targets):
    java_targets = filter(JavaCompile._has_java_sources, targets)
    if java_targets:
      safe_mkdir(self._classes_dir)
      safe_mkdir(self._depfile_dir)

      with self.context.state('classpath', []) as cp:
        for conf in self._confs:
          cp.insert(0, (conf, self._resources_dir))
          cp.insert(0, (conf, self._classes_dir))

      with self.invalidated(java_targets, invalidate_dependants=True) as invalidated:
        if self._flatten:
          # The deps go to a single well-known file, so we need only pass in the invalid targets here.
          self.execute_single_compilation(invalidated.combined_invalid_versioned_targets(), cp)
        else:
          # We must pass all targets,even valid ones, to execute_single_compilation(), so it can
          # track the per-target deps correctly.
          for vt in invalidated.all_versioned_targets():
            self.execute_single_compilation(vt, cp)

      if self.context.products.isrequired('classes'):
        genmap = self.context.products.get('classes')

        # Map generated classes to the owning targets and sources.
        for target, classes_by_source in self._deps.findclasses(java_targets).items():
          for source, classes in classes_by_source.items():
            genmap.add(source, self._classes_dir, classes)
            genmap.add(target, self._classes_dir, classes)

        # TODO(John Sirois): Map target.resources in the same way
        # 'Map' (rewrite) annotation processor service info files to the owning targets.
        for target in java_targets:
          if is_apt(target) and target.processors:
            basedir = os.path.join(self._resources_dir, target.id)
            processor_info_file = os.path.join(basedir, _PROCESSOR_INFO_FILE)
            self.write_processor_info(processor_info_file, target.processors)
            genmap.add(target, basedir, [_PROCESSOR_INFO_FILE])

  def execute_single_compilation(self, versioned_targets, cp):
    compilation_id = Target.maybe_readable_identify(versioned_targets.targets)

    # TODO: Use the artifact cache. In flat mode we may want to look for the artifact for all targets,
    # not just the invalid ones, as it might be more likely to be present. Or we could look for both.

    if self._flatten:
      # If compiling in flat mode, we let all dependencies aggregate into a single well-known depfile. This
      # allows us to build different targets in different invocations without losing dependency information
      # from any of them.
      depfile = os.path.join(self._depfile_dir, 'dependencies.flat')
    else:
      # If not in flat mode, we let each compilation have its own depfile, to avoid quadratic behavior (each
      # compilation will read in the entire depfile, add its stuff to it and write it out again).
      depfile = os.path.join(self._depfile_dir, compilation_id) + '.dependencies'

    if not versioned_targets.valid:
      self.context.log.info('Compiling targets %s' % str(versioned_targets.targets))
      sources_by_target, processors, fingerprint = self.calculate_sources(versioned_targets.targets)
      if sources_by_target:
        sources = reduce(lambda all, sources: all.union(sources), sources_by_target.values())
        if not sources:
          touch(depfile)  # Create an empty depfile, since downstream code may assume that one exists.
          self.context.log.warn('Skipping java compile for targets with no sources:\n  %s' %
                                '\n  '.join(str(t) for t in sources_by_target.keys()))
        else:
          classpath = [jar for conf, jar in cp if conf in self._confs]
          result = self.compile(classpath, sources, fingerprint, depfile)
          if result != 0:
            default_message = 'Unexpected error - %s returned %d' % (_JMAKE_MAIN, result)
            raise TaskError(_JMAKE_ERROR_CODES.get(result, default_message))

        if processors:
          # Produce a monolithic apt processor service info file for further compilation rounds
          # and the unit test classpath.
          processor_info_file = os.path.join(self._classes_dir, _PROCESSOR_INFO_FILE)
          if os.path.exists(processor_info_file):
            with safe_open(processor_info_file, 'r') as f:
              for processor in f:
                processors.add(processor.strip())
          self.write_processor_info(processor_info_file, processors)

    # Read in the deps created either just now or by a previous compiler run on these targets.
    deps = Dependencies(self._classes_dir)
    deps.load(depfile)
    self._deps.merge(deps)

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
    return sources, processors, Target.identify(targets)

  def compile(self, classpath, sources, fingerprint, depfile):
    jmake_classpath = nailgun_profile_classpath(self, self._jmake_profile)

    args = [
      '-classpath', ':'.join(classpath),
      '-d', self._classes_dir,
      '-pdb', os.path.join(self._classes_dir, '%s.dependencies.pdb' % fingerprint),
    ]

    compiler_classpath = nailgun_profile_classpath(self, self._compiler_profile)
    args.extend([
      '-jcpath', ':'.join(compiler_classpath),
      '-jcmainclass', 'com.twitter.common.tools.Compiler',
      '-C-Tdependencyfile', '-C%s' % depfile,
    ])

    args.extend(self._args)
    args.extend(sources)
    log.debug('Executing: %s %s' % (_JMAKE_MAIN, ' '.join(args)))
    return self.runjava(_JMAKE_MAIN, classpath=jmake_classpath, args=args, jvmargs=self._jvm_args)

  def write_processor_info(self, processor_info_file, processors):
    with safe_open(processor_info_file, 'w') as f:
      for processor in processors:
        f.write('%s\n' % processor)

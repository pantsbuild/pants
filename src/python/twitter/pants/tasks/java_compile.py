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
from twitter.common.dirutil import safe_open, safe_mkdir
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

    option_group.add_option(mkflag("partition-size-hint"), dest="java_compile_partition_size_hint",
      action="store", type="int", default=-1,
      help="Roughly how many source files to attempt to compile together. Set to a large number to compile "\
           "all sources together. Set this to 0 to compile target-by-target. Default is set in pants.ini.")

  def __init__(self, context):
    NailgunTask.__init__(self, context, workdir=context.config.get('java-compile', 'nailgun_dir'))

    self._partition_size_hint = \
      context.options.java_compile_partition_size_hint \
      if context.options.java_compile_partition_size_hint != -1 \
      else context.config.getint('java-compile', 'partition_size_hint')

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

    # The artifact cache to read from/write to.
    artifact_cache_spec = context.config.getlist('java-compile', 'artifact_caches')
    self.setup_artifact_cache(artifact_cache_spec)

  def product_type(self):
    return 'classes'

  def can_dry_run(self):
    return True

  def execute(self, targets):
    java_targets = filter(JavaCompile._has_java_sources, targets)
    if java_targets:
      safe_mkdir(self._classes_dir)
      safe_mkdir(self._depfile_dir)

      with self.context.state('classpath', []) as cp:
        for conf in self._confs:
          cp.insert(0, (conf, self._resources_dir))
          cp.insert(0, (conf, self._classes_dir))

      with self.invalidated(java_targets, invalidate_dependents=True,
          partition_size_hint=self._partition_size_hint) as invalidation_check:
        for vt in invalidation_check.all_vts:
          if vt.valid:  # Don't compile, just post-process.
            self.post_process(vt)
        for vt in invalidation_check.invalid_vts_partitioned:
          # Compile, using partitions for efficiency.
          self.execute_single_compilation(vt, cp)
          if not self.dry_run:
            vt.update()

      if not self.dry_run:
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

  def execute_single_compilation(self, vt, cp):
    depfile = self.create_depfile_path(vt.targets)

    self.merge_depfile(vt)  # Get what we can from previous builds.
    self.context.log.info('Compiling targets %s' % str(vt.targets))
    sources_by_target, processors, fingerprint = self.calculate_sources(vt.targets)
    if sources_by_target:
      sources = reduce(lambda all, sources: all.union(sources), sources_by_target.values())
      if not sources:
        self.context.log.warn('Skipping java compile for targets with no sources:\n  %s' %
                              '\n  '.join(str(t) for t in sources_by_target.keys()))
      else:
        classpath = [jar for conf, jar in cp if conf in self._confs]
        result = self.compile(classpath, sources, fingerprint, depfile)
        if result != 0:
          default_message = 'Unexpected error - %s returned %d' % (_JMAKE_MAIN, result)
          raise TaskError(_JMAKE_ERROR_CODES.get(result, default_message))

      # NOTE: Currently all classfiles go into one global classes_dir. If we compile in
      # multiple partitions the second one will cache all the classes of the first one.
      # This won't result in error, but is wasteful. Currently, however, Java compilation
      # is done in a single pass, so this won't occur in practice.
      # TODO: Handle this case better. Separate classes dirs for each partition, like for scala?
      artifact_files = [self._classes_dir, depfile]

      if processors and not self.dry_run:
        # Produce a monolithic apt processor service info file for further compilation rounds
        # and the unit test classpath.
        processor_info_file = os.path.join(self._classes_dir, _PROCESSOR_INFO_FILE)
        if os.path.exists(processor_info_file):
          with safe_open(processor_info_file, 'r') as f:
            for processor in f:
              processors.add(processor.strip())
        self.write_processor_info(processor_info_file, processors)
        artifact_files.append(processor_info_file)

      if self._artifact_cache and self.context.options.write_to_artifact_cache:
        self.update_artifact_cache(vt, artifact_files)

    self.post_process(vt)

  # Post-processing steps that must happen even for valid targets.
  def post_process(self, versioned_targets):
    depfile = self.create_depfile_path(versioned_targets.targets)
    if not self.dry_run and os.path.exists(depfile):
      # Read in the deps created either just now or by a previous compiler run on these targets.
      deps = Dependencies(self._classes_dir)
      deps.load(depfile)
      self.split_depfile(deps, versioned_targets)
      self._deps.merge(deps)

  def create_depfile_path(self, targets):
    compilation_id = Target.maybe_readable_identify(targets)
    return os.path.join(self._depfile_dir, compilation_id) + '.dependencies'

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

  def split_depfile(self, deps, versioned_target_set):
    if len(versioned_target_set.targets) <= 1:
      return
    classes_by_source_by_target = deps.findclasses(versioned_target_set.targets)
    for target in versioned_target_set.targets:
      classes_by_source = classes_by_source_by_target.get(target, {})
      dst_depfile = self.create_depfile_path([target])
      dst_deps = Dependencies(self._classes_dir)
      for source, classes in classes_by_source.items():
        src = os.path.join(target.target_base, source)
        dst_deps.add(src, classes)
      dst_deps.save(dst_depfile)

  # Merges individual target depfiles into a single one for all those targets.
  # Note that the merged depfile may be incomplete (e.g., if the previous build was aborted).
  # TODO: Is this even necessary? JMake will stomp these anyway on success.
  def merge_depfile(self, versioned_target_set):
    if len(versioned_target_set.targets) <= 1:
      return

    dst_depfile = self.create_depfile_path(versioned_target_set.targets)
    dst_deps = Dependencies(self._classes_dir)

    for target in versioned_target_set.targets:
      src_depfile = self.create_depfile_path([target])
      if os.path.exists(src_depfile):
        src_deps = Dependencies(self._classes_dir)
        src_deps.load(src_depfile)
        dst_deps.merge(src_deps)

    dst_deps.save(dst_depfile)

  def write_processor_info(self, processor_info_file, processors):
    with safe_open(processor_info_file, 'w') as f:
      for processor in processors:
        f.write('%s\n' % processor)

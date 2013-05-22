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

import os
import shlex

from collections import defaultdict

from twitter.common.dirutil import safe_open, safe_mkdir

from twitter.pants import has_sources, is_apt, Task
from twitter.pants.base.target import Target
from twitter.pants.goal.workunit import WorkUnit
from twitter.pants.tasks import TaskError
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


def _is_java(target):
  return has_sources(target, '.java')


class JavaCompile(NailgunTask):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    NailgunTask.setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("warnings"), mkflag("warnings", negate=True),
                            dest="java_compile_warnings", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Compile java code with all configured warnings "
                                 "enabled.")

    option_group.add_option(mkflag("args"), dest="java_compile_args", action="append",
                            help="Pass these extra args to javac.")

    option_group.add_option(mkflag("partition-size-hint"), dest="java_compile_partition_size_hint",
                            action="store", type="int", default=-1,
                            help="Roughly how many source files to attempt to compile together. Set"
                                 " to a large number to compile all sources together. Set this to 0"
                                 " to compile target-by-target. Default is set in pants.ini.")

  def __init__(self, context):
    NailgunTask.__init__(self, context, workdir=context.config.get('java-compile', 'nailgun_dir'))

    if context.options.java_compile_partition_size_hint != -1:
      self._partition_size_hint = context.options.java_compile_partition_size_hint
    else:
      self._partition_size_hint = context.config.getint('java-compile', 'partition_size_hint',
                                                        default=1000)

    workdir = context.config.get('java-compile', 'workdir')
    self._classes_dir = os.path.join(workdir, 'classes')
    self._resources_dir = os.path.join(workdir, 'resources')
    self._depfile_dir = os.path.join(workdir, 'depfiles')
    self._deps = Dependencies(self._classes_dir)

    self._jmake_profile = context.config.get('java-compile', 'jmake-profile')
    self._compiler_profile = context.config.get('java-compile', 'compiler-profile')

    self._opts = context.config.getlist('java-compile', 'args')
    self._jvm_args = context.config.getlist('java-compile', 'jvm_args')

    self._javac_opts = []
    if context.options.java_compile_args:
      for arg in context.options.java_compile_args:
        self._javac_opts.extend(shlex.split(arg))
    else:
      self._javac_opts.extend(context.config.getlist('java-compile', 'javac_args', default=[]))

    if context.options.java_compile_warnings:
      self._opts.extend(context.config.getlist('java-compile', 'warning_args'))
    else:
      self._opts.extend(context.config.getlist('java-compile', 'no_warning_args'))

    self._confs = context.config.getlist('java-compile', 'confs')

    # The artifact cache to read from/write to.
    artifact_cache_spec = context.config.getlist('java-compile', 'artifact_caches')
    self.setup_artifact_cache(artifact_cache_spec)

  def product_type(self):
    return 'classes'

  def can_dry_run(self):
    return True

  def execute(self, targets):
    java_targets = filter(_is_java, targets)
    if java_targets:
      safe_mkdir(self._classes_dir)
      safe_mkdir(self._depfile_dir)

      with self.context.state('classpath', []) as cp:
        for conf in self._confs:
          cp.insert(0, (conf, self._resources_dir))
          cp.insert(0, (conf, self._classes_dir))

      with self.invalidated(java_targets, invalidate_dependents=True,
                            partition_size_hint=self._partition_size_hint) as invalidation_check:
        for vt in invalidation_check.invalid_vts_partitioned:
          # Compile, using partitions for efficiency.
          self.execute_single_compilation(vt, cp)
          if not self.dry_run:
            vt.update()

        for vt in invalidation_check.all_vts:
          depfile = self.create_depfile_path(vt.targets)
          if not self.dry_run and os.path.exists(depfile):
            # Read in the deps created either just now or by a previous run on these targets.
            deps = Dependencies(self._classes_dir)
            deps.load(depfile)
            self._deps.merge(deps)

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
              basedir = os.path.join(self._resources_dir, Target.maybe_readable_identify([target]))
              processor_info_file = os.path.join(basedir, _PROCESSOR_INFO_FILE)
              self.write_processor_info(processor_info_file, target.processors)
              genmap.add(target, basedir, [_PROCESSOR_INFO_FILE])

        # Produce a monolithic apt processor service info file for further compilation rounds
        # and the unit test classpath.
        all_processors = set()
        for target in java_targets:
          if is_apt(target) and target.processors:
            all_processors.update(target.processors)
        processor_info_file = os.path.join(self._classes_dir, _PROCESSOR_INFO_FILE)
        if os.path.exists(processor_info_file):
          with safe_open(processor_info_file, 'r') as f:
            for processor in f:
              all_processors.add(processor.strip())
        self.write_processor_info(processor_info_file, all_processors)

  def execute_single_compilation(self, vt, cp):
    depfile = self.create_depfile_path(vt.targets)

    self.merge_depfile(vt)  # Get what we can from previous builds.
    sources_by_target, fingerprint = self.calculate_sources(vt.targets)
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
        self.split_depfile(vt)

      all_artifact_files = [depfile]

      if self._artifact_cache and self.context.options.write_to_artifact_cache:
        deps = Dependencies(self._classes_dir)
        deps.load(depfile)
        vts_artifactfile_pairs = []
        for single_vt in vt.versioned_targets:
          per_target_depfile = self.create_depfile_path([single_vt.target])
          per_target_artifact_files = [per_target_depfile]
          for _, classes_by_source in deps.findclasses([single_vt.target]).items():
            for _, classes in classes_by_source.items():
              classfile_paths = [os.path.join(self._classes_dir, cls) for cls in classes]
              per_target_artifact_files.extend(classfile_paths)
              all_artifact_files.extend(classfile_paths)
            vts_artifactfile_pairs.append((single_vt, per_target_artifact_files))
        vts_artifactfile_pairs.append((vt, all_artifact_files))
        self.update_artifact_cache(vts_artifactfile_pairs)

  def create_depfile_path(self, targets):
    compilation_id = Target.maybe_readable_identify(targets)
    return os.path.join(self._depfile_dir, compilation_id) + '.dependencies'

  def calculate_sources(self, targets):
    sources = defaultdict(set)
    def collect_sources(target):
      src = (os.path.join(target.target_base, source)
             for source in target.sources if source.endswith('.java'))
      if src:
        sources[target].update(src)

    for target in targets:
      collect_sources(target)
    return sources, Target.identify(targets)

  def compile(self, classpath, sources, fingerprint, depfile):
    jmake_classpath = self.profile_classpath(self._jmake_profile)

    opts = [
      '-classpath', ':'.join(classpath),
      '-d', self._classes_dir,
      '-pdb', os.path.join(self._classes_dir, '%s.dependencies.pdb' % fingerprint),
    ]

    compiler_classpath = self.profile_classpath(self._compiler_profile)
    opts.extend([
      '-jcpath', ':'.join(compiler_classpath),
      '-jcmainclass', 'com.twitter.common.tools.Compiler',
      '-C-Tdependencyfile', '-C%s' % depfile,
    ])
    opts.extend(map(lambda arg: '-C%s' % arg, self._javac_opts))

    opts.extend(self._opts)
    return self.runjava_indivisible(_JMAKE_MAIN, classpath=jmake_classpath, opts=opts, args=sources,
                                    jvmargs=self._jvm_args, workunit_name='jmake',
                                    workunit_labels=[WorkUnit.COMPILER])

  def check_artifact_cache(self, vts):
    # Special handling for java artifacts.
    cached_vts, uncached_vts = Task.check_artifact_cache(self, vts)

    if cached_vts:
      with self.context.new_workunit('split'):
        for vt in cached_vts:
          self.split_depfile(vt)
    return cached_vts, uncached_vts

  def split_depfile(self, vt):
    depfile = self.create_depfile_path(vt.targets)
    if len(vt.targets) <= 1 or not os.path.exists(depfile) or self.dry_run:
      return

    deps = Dependencies(self._classes_dir)
    deps.load(depfile)

    classes_by_source_by_target = deps.findclasses(vt.targets)
    for target in vt.targets:
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

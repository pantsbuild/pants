# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.base.build_environment import get_buildroot, get_pants_cachedir
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.java.distribution.distribution import DistributionLocator
from pants.util.collections import assert_single_element
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_property
from pants.util.process_handler import subprocess

# from upstreamable.tasks.bootstrap_ensime_gen import EnsimeGenJar
from pants.contrib.bloop.tasks.modified_export_task_base import ModifiedExportTaskBase


class EnsimeGen(ModifiedExportTaskBase):

  @classmethod
  def register_options(cls, register):
    super(EnsimeGen, cls).register_options(register)

    register('--reported-scala-version', type=str, default='2.12.8',
             help='Scala version to report to ensime. Defaults to the scala platform version.')
    register('--output-dir', type=str, default='.bloop', advanced=True,
             help='Relative path to the buildroot to write the ensime config to.')

  @classmethod
  def prepare(cls, options, round_manager):
    super(EnsimeGen, cls).prepare(options, round_manager)
    # NB: this is so we run after compile -- we want our class dirs to be populated already.
    round_manager.require_data('runtime_classpath')
    # round_manager.require_data(EnsimeGenJar)
    # cls.prepare_tools(round_manager)

  @classmethod
  def subsystem_dependencies(cls):
    return super(EnsimeGen, cls).subsystem_dependencies() + (DistributionLocator, ScalaPlatform,)

  def _make_ensime_cache_dir(self):
    bootstrap_dir = get_pants_cachedir()
    cache_dir = os.path.join(bootstrap_dir, 'ensime')
    safe_mkdir(cache_dir)
    return cache_dir

  @memoized_property
  def _scala_platform(self):
    return ScalaPlatform.global_instance()

  def execute(self):

    exported_targets_map = self.generate_targets_map(self.context.targets())
    export_result = json.dumps(exported_targets_map, indent=4, separators=(',', ': '))

    # TODO: use JvmPlatform for jvm options!
    reported_scala_version = self.get_options().reported_scala_version
    if not reported_scala_version:
      reported_scala_version = self._scala_platform.version

    output_dir = os.path.join(get_buildroot(), self.get_options().output_dir)
    safe_mkdir(output_dir)

    scala_compiler_jars = [
      cpe.path for cpe in
      self._scala_platform.compiler_classpath_entries(self.context.products, self.context._scheduler)
    ]

    argv = [
      get_buildroot(),
      reported_scala_version,
      self.get_options().pants_distdir,
      output_dir,
    ]

    def split_json_options(options_lines):
      return json.dumps(assert_single_element(options_lines).split('\n'))

    env = {
      'SCALA_COMPILER_JARS_CLASSPATH': ':'.join(scala_compiler_jars),
    }

    self.context.log.debug('export_result:\n{}'.format(export_result))
    self.context.log.debug('env:\n{}'.format(env))

    with self.context.new_workunit('bloop-invoke', labels=[WorkUnitLabel.COMPILER]) as workunit:
      proc = subprocess.Popen([
        'java',
        '-jar',
        '/Users/dmcclanahan/tools/pants/dist/bloop-config-gen.jar'
      ] + argv,
                              env=env,
                              stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
      stdout, stderr = proc.communicate(input=export_result.encode())
      workunit.output('stdout').write(stdout)
      workunit.output('stderr').write(stderr)
      rc = proc.wait()
      if rc != 0:
        raise TaskError('wow', exit_code=rc)

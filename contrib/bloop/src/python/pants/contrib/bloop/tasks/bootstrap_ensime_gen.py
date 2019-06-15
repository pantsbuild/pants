# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import glob
import os
import shutil

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.build_graph.address import Address
from pants.option.custom_types import target_option
from pants.task.task import Task
from pants.util.collections import assert_single_element
from pants.util.contextutil import temporary_dir
from pants.util.memo import memoized_property
from pants.util.objects import datatype
from pants.util.process_handler import subprocess


class EnsimeGenJar(datatype(['tool_jar_path'])): pass


class BootstrapEnsimeGen(Task):

  @classmethod
  def product_types(cls):
    return [EnsimeGenJar]

  @classmethod
  def register_options(cls, register):
    super(BootstrapEnsimeGen, cls).register_options(register)

    register('--skip', type=bool, advanced=True,
             help='Whether to skip this task (e.g. if we are currently executing the subprocess).')

    register('--ensime-gen-binary', type=target_option, default='//:ensime-gen', advanced=True,
             help='jvm_binary() target to execute to interpret export json into an ensime project.')

  @memoized_property
  def _binary_tool_target(self):
    return self.get_options().ensime_gen_binary

  @memoized_property
  def _bootstrap_config_files(self):
    return self.get_options().pants_config_files + [
      os.path.join(get_buildroot(), 'pants.ini.bootstrap'),
    ]

  class BootstrapEnsimeError(TaskError): pass

  def _collect_dist_jar(self, dist_dir):
    # We should only see a single file in the dist dir.
    dist_jar_glob = os.path.join(dist_dir, '*.jar')
    globbed_jars = glob.glob(dist_jar_glob)

    if globbed_jars:
      return assert_single_element(globbed_jars)
    else:
      return None

  _CLEAN_ENV = [
    'PANTS_ENABLE_PANTSD',
    'PANTS_ENTRYPOINT',
  ]

  def _get_subproc_env(self):
    env = os.environ.copy()

    for env_var in self._CLEAN_ENV:
      env.pop(env_var, None)

    return env

  def _build_binary(self, ensime_binary_target_spec):

    pants_config_files_args = ['"{}"'.format(f) for f in self._bootstrap_config_files]

    with temporary_dir() as tmpdir:
      cmd = [
        './pants',
        '--pants-config-files=[{}]'.format(','.join(pants_config_files_args)),
        '--pants-distdir={}'.format(tmpdir),
        'binary',
        ensime_binary_target_spec,
      ]

      env = self._get_subproc_env()

      with self.context.new_workunit(
          name='bootstrap-ensime-gen-subproc',
          labels=[WorkUnitLabel.COMPILER],
          # TODO: replace space join with safe_shlex_join() when #5493 is merged!
          cmd=' '.join(cmd),
      ) as workunit:

        try:
          subprocess.check_call(
            cmd,
            cwd=get_buildroot(),
            stdout=workunit.output('stdout'),
            stderr=workunit.output('stderr'),
            env=env)
        except OSError as e:
          workunit.set_outcome(WorkUnit.FAILURE)
          raise self.BootstrapEnsimeError(
            "Error invoking pants for the ensime-gen binary with command {} from target {}: {}"
            .format(cmd, ensime_binary_target_spec, e),
            e)
        except subprocess.CalledProcessError as e:
          workunit.set_outcome(WorkUnit.FAILURE)
          raise self.BootstrapEnsimeError(
            "Error generating the ensime-gen binary with command {} from target {}. "
            "Exit code was: {}."
            .format(cmd, ensime_binary_target_spec, e.returncode),
            e)

      dist_jar = self._collect_dist_jar(tmpdir)
      jar_fname = os.path.basename(dist_jar)
      cached_jar_path = os.path.join(self.workdir, jar_fname)
      shutil.move(dist_jar, cached_jar_path)

  def execute(self):

    if self.get_options().skip:
      return

    ensime_binary_target_spec = self._binary_tool_target
    ensime_binary_target_address = Address.parse(ensime_binary_target_spec)

    # Scan everything under the target dir, then check whether the binary target has been
    # invalidated. The default target dir is '', meaning scan all BUILD files -- but that's ok since
    # this project is small.
    ensime_scala_root = os.path.join(get_buildroot(), ensime_binary_target_address.spec_path)
    new_build_graph = self.context.scan(ensime_scala_root)
    ensime_binary_target = new_build_graph.get_target_from_spec(ensime_binary_target_spec)

    with self.invalidated([ensime_binary_target], invalidate_dependents=True) as invalidation_check:
      if invalidation_check.invalid_vts:
        self._build_binary(ensime_binary_target_spec)

    built_jar = self._collect_dist_jar(self.workdir)

    self.context.products.register_data(EnsimeGenJar, EnsimeGenJar(built_jar))

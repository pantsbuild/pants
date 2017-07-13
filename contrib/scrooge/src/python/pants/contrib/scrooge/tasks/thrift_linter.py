# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import multiprocessing

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.base.worker_pool import Work, WorkerPool
from pants.base.workunit import WorkUnitLabel
from pants.option.ranked_value import RankedValue

from pants.contrib.scrooge.tasks.thrift_util import calculate_compile_sources


class ThriftLintError(Exception):
  """Raised on a lint failure."""


class ThriftLinter(NailgunTask):
  """Print linter warnings for thrift files."""

  deprecated_options_scope = 'thrift-linter'
  deprecated_options_scope_removal_version = '1.6.0.dev0'

  @staticmethod
  def _is_thrift(target):
    return target.is_thrift

  @classmethod
  def register_options(cls, register):
    super(ThriftLinter, cls).register_options(register)
    register('--skip', type=bool, fingerprint=True, help='Skip thrift linting.')
    register('--strict', type=bool, fingerprint=True,
             help='Fail the goal if thrift linter errors are found: if specified on the '
                  'CLI, overrides the values specified directly on targets.')
    register('--strict-default', default=False, advanced=True, type=bool,
             removal_version='1.6.0.dev0',
             removal_hint='Use the `strict` option directly instead.',
             fingerprint=True,
             help='Sets the default strictness for targets. The `strict` option overrides '
                  'this value if it is set.')
    register('--linter-args', default=['--warnings'], advanced=True, type=list,
             fingerprint=True,
             help='Additional options passed to the linter.')
    register('--worker-count', default=multiprocessing.cpu_count(), advanced=True, type=int,
             help='Maximum number of workers to use for linter parallelization.')
    cls.register_jvm_tool(register, 'scrooge-linter')

  @property
  def cache_target_dirs(self):
    return True

  def _lint(self, target, classpath):
    self.context.log.debug('Linting {0}'.format(target.address.spec))

    config_args = []

    config_args.extend(self.get_options().linter_args)
    if not self.get_options().resolve('strict', target, field='thrift_linter_strict'):
      config_args.append('--disable-strict')

    include_paths , paths = calculate_compile_sources([target], self._is_thrift)
    if target.include_paths:
      include_paths |= set(target.include_paths)
    for p in include_paths:
      config_args.extend(['--include-path', p])

    args = config_args + list(paths)


    # If runjava returns non-zero, this marks the workunit as a
    # FAILURE, and there is no way to wrap this here.
    returncode = self.runjava(classpath=classpath,
                              main='com.twitter.scrooge.linter.Main',
                              args=args,
                              jvm_options=self.get_options().jvm_options,
                              # to let stdout/err through, but don't print tool's label.
                              workunit_labels=[WorkUnitLabel.COMPILER, WorkUnitLabel.SUPPRESS_LABEL])

    if returncode != 0:
      raise ThriftLintError(
        'Lint errors in target {0} for {1}.'.format(target.address.spec, paths))

  def execute(self):
    if self.get_options().skip:
      return

    thrift_targets = self.context.targets(self._is_thrift)
    with self.invalidated(thrift_targets) as invalidation_check:
      if not invalidation_check.invalid_vts:
        return

      with self.context.new_workunit('parallel-thrift-linter') as workunit:
        worker_pool = WorkerPool(workunit.parent,
                                 self.context.run_tracker,
                                 self.get_options().worker_count)

        scrooge_linter_classpath = self.tool_classpath('scrooge-linter')
        results = []
        errors = []
        for vt in invalidation_check.invalid_vts:
          r = worker_pool.submit_async_work(Work(self._lint, [(vt.target, scrooge_linter_classpath)]))
          results.append((r, vt))
        for r, vt in results:
          r.wait()
          # MapResult will raise _value in `get` if the run is not successful.
          try:
            r.get()
          except ThriftLintError as e:
            errors.append(str(e))
          else:
            vt.update()

        if errors:
          raise TaskError('\n'.join(errors))

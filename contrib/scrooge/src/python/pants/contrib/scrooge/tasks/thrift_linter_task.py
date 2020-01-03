# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import multiprocessing

from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.base.worker_pool import Work, WorkerPool
from pants.base.workunit import WorkUnitLabel
from pants.task.lint_task_mixin import LintTaskMixin

from pants.contrib.scrooge.subsystems.scrooge_linter import ScroogeLinter
from pants.contrib.scrooge.tasks.thrift_util import calculate_include_paths


class ThriftLintError(Exception):
  """Raised on a lint failure."""


class ThriftLinterTask(LintTaskMixin, NailgunTask):
  """Print lint warnings for thrift files."""

  def raise_conflicting_option(self, option: str) -> None:
    raise ValueError(
      f"Conflicting options used. You used the new, preferred `--scrooge-linter-{option}`, but also "
      f"used the deprecated `--lint-thrift-{option}`\nPlease use only one of these "
      f"(preferably `--scrooge-linter-{option}`)."
    )

  @staticmethod
  def _is_thrift(target):
    return isinstance(target, JavaThriftLibrary)

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--strict', type=bool, fingerprint=True,
             removal_hint="Use `--scrooge-linter-strict` instead",
             help='Fail the goal if thrift linter errors are found. Overrides the '
                  '`strict-default` option.')
    register('--strict-default', default=False, advanced=True, type=bool,
             fingerprint=True, removal_version="1.27.0.dev0",
             removal_hint="Use `--scrooge-linter-strict-default` instead",
             help='Sets the default strictness for targets. The `strict` option overrides '
                  'this value if it is set.')
    register('--linter-args', default=[], advanced=True, type=list, fingerprint=True,
             removal_version='1.27.0.dev0',
             removal_hint='Use `--scrooge-linter-args` instead. Unlike this argument, you can pass '
                          'all the arguments as one string, e.g. '
                          '`--scrooge-linter-args="--disable-rule Namespaces".',
             help='Additional options passed to the linter.')
    register('--worker-count', default=multiprocessing.cpu_count(), advanced=True, type=int,
             removal_version='1.27.0.dev0',
             removal_hint="Use `--scrooge-linter-worker-count` instead.",
             help='Maximum number of workers to use for linter parallelization.')
    cls.register_jvm_tool(register, 'scrooge-linter')

  @classmethod
  def subsystem_dependencies(cls):
    return super().subsystem_dependencies() + (ScroogeLinter,)

  @classmethod
  def product_types(cls):
    # Declare the product of this goal. Gen depends on thrift-linter.
    return ['thrift-linter']

  @property
  def cache_target_dirs(self):
    return True

  @staticmethod
  def _to_bool(value):
    # Converts boolean and string values to boolean.
    return str(value) == 'True'

  def _is_strict(self, target):
    # The strict value is read from the following, in order:
    # 1. the option --[no-]strict, but only if explicitly set.
    # 2. java_thrift_library target in BUILD file, thrift_linter_strict = False,
    # 3. options, --[no-]strict-default
    task_options = self.get_options()
    subsystem_options = ScroogeLinter.global_instance().options

    task_strict_configured = not task_options.is_default('strict')
    subsystem_strict_configured = not subsystem_options.is_default('strict')
    if task_strict_configured and subsystem_strict_configured:
      self.raise_conflicting_option("strict")
    if subsystem_strict_configured:
      return self._to_bool(subsystem_options.strict)
    if task_strict_configured:
      return self._to_bool(task_options.strict)

    if target.thrift_linter_strict is not None:
      return self._to_bool(target.thrift_linter_strict)

    task_strict_default_configured = not task_options.is_default('strict_default')
    subsystem_strict_default_configured = not subsystem_options.is_default('strict_default')
    if task_strict_default_configured and subsystem_strict_default_configured:
      self.raise_conflicting_option("strict_default")
    if task_strict_configured:
      return self._to_bool(task_options.strict_default)
    return self._to_bool(subsystem_options.strict_default)

  def _lint(self, target, classpath):
    self.context.log.debug(f'Linting {target.address.spec}')

    config_args = []

    config_args.extend(self.get_options().linter_args)
    config_args.extend(ScroogeLinter.global_instance().get_args())

    # N.B. We always set --fatal-warnings to make sure errors like missing-namespace are at least printed.
    # If --no-strict is turned on, the return code will be 0 instead of 1, but the errors/warnings
    # need to always be printed.
    config_args.append('--fatal-warnings')
    if not self._is_strict(target):
      config_args.append('--ignore-errors')

    paths = list(target.sources_relative_to_buildroot())
    include_paths = calculate_include_paths([target], self._is_thrift)
    if target.include_paths:
      include_paths |= set(target.include_paths)
    for p in include_paths:
      config_args.extend(['--include-path', p])

    args = config_args + paths

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
        f'Lint errors in target {target.address.spec} for {paths}.')

  def execute(self):
    thrift_targets = self.get_targets(self._is_thrift)

    task_worker_count_configured = not self.get_options().is_default("worker_count")
    subsystem_worker_count_configured = not ScroogeLinter.global_instance().options.is_default("worker_count")
    if task_worker_count_configured and subsystem_worker_count_configured:
      self.raise_conflicting_option("worker_count")
    worker_count = (
      self.get_options().worker_count
      if task_worker_count_configured
      else ScroogeLinter.global_instance().options.worker_count
    )

    with self.invalidated(thrift_targets) as invalidation_check:
      if not invalidation_check.invalid_vts:
        return

      with self.context.new_workunit('parallel-thrift-linter') as workunit:
        worker_pool = WorkerPool(workunit.parent,
                                 self.context.run_tracker,
                                 worker_count,
                                 workunit.name)

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

# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import multiprocessing

from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.deprecated import resolve_conflicting_options
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

    def _resolve_conflicting_options(self, *, old_option: str, new_option: str):
        return resolve_conflicting_options(
            old_option=old_option,
            new_option=new_option,
            old_scope="lint-thrift",
            new_scope="scrooge-linter",
            old_container=self.get_options(),
            new_container=ScroogeLinter.global_instance().options,
        )

    @staticmethod
    def _is_thrift(target):
        return isinstance(target, JavaThriftLibrary)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--strict",
            type=bool,
            fingerprint=True,
            removal_hint="Use `--scrooge-linter-strict` instead",
            help="Fail the goal if thrift linter errors are found. Overrides the "
            "`strict-default` option.",
        )
        register(
            "--strict-default",
            default=False,
            advanced=True,
            type=bool,
            fingerprint=True,
            removal_version="1.27.0.dev0",
            removal_hint="Use `--scrooge-linter-strict-default` instead",
            help="Sets the default strictness for targets. The `strict` option overrides "
            "this value if it is set.",
        )
        register(
            "--ignore-errors",
            default=False,
            advanced=True,
            type=bool,
            fingerprint=True,
            help="Ignore any error so thrift-linter always exit 0.",
        )
        register(
            "--linter-args",
            default=[],
            advanced=True,
            type=list,
            fingerprint=True,
            removal_version="1.27.0.dev0",
            removal_hint="Use `--scrooge-linter-args` instead. Unlike this argument, you can pass "
            "all the arguments as one string, e.g. "
            '`--scrooge-linter-args="--disable-rule Namespaces".',
            help="Additional options passed to the linter.",
        )
        register(
            "--worker-count",
            default=multiprocessing.cpu_count(),
            advanced=True,
            type=int,
            removal_version="1.27.0.dev0",
            removal_hint="Use `--scrooge-linter-worker-count` instead.",
            help="Maximum number of workers to use for linter parallelization.",
        )
        cls.register_jvm_tool(register, "scrooge-linter")

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (ScroogeLinter,)

    @classmethod
    def product_types(cls):
        # Declare the product of this goal. Gen depends on thrift-linter.
        return ["thrift-linter"]

    @property
    def skip_execution(self):
        return self.resolve_conflicting_skip_options(
            old_scope="thrift-linter",
            new_scope="scrooge-linter",
            subsystem=ScroogeLinter.global_instance(),
        )

    @property
    def cache_target_dirs(self):
        return True

    @staticmethod
    def _to_bool(value):
        # Converts boolean and string values to boolean.
        return str(value) == "True"

    def _is_strict(self, target):
        # The strict value is read from the following, in order:
        # 1. the option --[no-]strict, but only if explicitly set.
        # 2. java_thrift_library target in BUILD file, thrift_linter_strict = False,
        # 3. options, --[no-]strict-default
        task_options = self.get_options()
        subsystem_options = ScroogeLinter.global_instance().options

        # NB: _resolve_conflicting_options() used to assert that both options aren't configured.
        self._resolve_conflicting_options(old_option="strict", new_option="strict")
        if not subsystem_options.is_default("strict"):
            return self._to_bool(subsystem_options.strict)
        if not task_options.is_default("strict"):
            return self._to_bool(task_options.strict)

        if target.thrift_linter_strict is not None:
            return self._to_bool(target.thrift_linter_strict)

        return self._to_bool(
            self._resolve_conflicting_options(
                old_option="strict_default", new_option="strict_default"
            ),
        )

    def _lint(self, target, classpath):
        self.context.log.debug(f"Linting {target.address.spec}")

        config_args = []

        config_args.extend(self.get_options().linter_args)
        config_args.extend(ScroogeLinter.global_instance().options.args)

        if self._is_strict(target):
            config_args.append("--fatal-warnings")
        else:
            # Make sure errors like missing-namespace are at least printed.
            config_args.append("--warnings")

        if self.get_options().ignore_errors:
            config_args.append("--ignore-errors")

        paths = list(target.sources_relative_to_buildroot())
        include_paths = calculate_include_paths([target], self._is_thrift)
        if target.include_paths:
            include_paths |= set(target.include_paths)
        for p in include_paths:
            config_args.extend(["--include-path", p])

        args = config_args + paths

        # If runjava returns non-zero, this marks the workunit as a
        # FAILURE, and there is no way to wrap this here.
        returncode = self.runjava(
            classpath=classpath,
            main="com.twitter.scrooge.linter.Main",
            args=args,
            jvm_options=self.get_options().jvm_options,
            # to let stdout/err through, but don't print tool's label.
            workunit_labels=[WorkUnitLabel.COMPILER, WorkUnitLabel.SUPPRESS_LABEL],
        )

        if returncode != 0:
            raise ThriftLintError(f"Lint errors in target {target.address.spec} for {paths}.")

    def execute(self):
        thrift_targets = self.get_targets(self._is_thrift)
        with self.invalidated(thrift_targets) as invalidation_check:
            if not invalidation_check.invalid_vts:
                return

            with self.context.new_workunit("parallel-thrift-linter") as workunit:
                worker_pool = WorkerPool(
                    workunit.parent,
                    self.context.run_tracker,
                    self._resolve_conflicting_options(
                        old_option="worker_count", new_option="worker_count"
                    ),
                    workunit.name,
                )

                scrooge_linter_classpath = self.tool_classpath("scrooge-linter")
                results = []
                errors = []
                for vt in invalidation_check.invalid_vts:
                    r = worker_pool.submit_async_work(
                        Work(self._lint, [(vt.target, scrooge_linter_classpath)])
                    )
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
                    raise TaskError("\n".join(errors))

# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.subsystems.scalastyle import Scalastyle
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.build_graph.target import Target
from pants.option.custom_types import file_option
from pants.process.xargs import Xargs
from pants.task.lint_task_mixin import LintTaskMixin
from pants.util.dirutil import touch


# TODO: Move somewhere more general?
class FileExcluder:
    def __init__(self, excludes_path, log):
        self.excludes = set()
        if excludes_path:
            if not os.path.exists(excludes_path):
                raise TaskError(f"Excludes file does not exist: {excludes_path}")
            with open(excludes_path, "r") as fh:
                for line in fh.readlines():
                    pattern = line.strip()
                    if pattern and not pattern.startswith("#"):
                        self.excludes.add(re.compile(pattern))
                        log.debug(f"Exclude pattern: {pattern}")
        else:
            log.debug("No excludes file specified. All scala sources will be checked.")

    def should_include(self, source_filename):
        for exclude in self.excludes:
            if exclude.match(source_filename):
                return False
        return True


class ScalastyleTask(LintTaskMixin, NailgunTask):
    """Checks scala source files to ensure they're stylish.

    Scalastyle only checks scala sources in non-synthetic targets.

    :API: public
    """

    class UnspecifiedConfig(TaskError):
        def __init__(self):
            super().__init__("Path to scalastyle config file must be specified.")

    class MissingConfig(TaskError):
        def __init__(self, path):
            super().__init__(f"Scalastyle config file does not exist: {path}.")

    _SCALA_SOURCE_EXTENSION = ".scala"

    _MAIN = "org.scalastyle.Main"

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (ScalaPlatform, Scalastyle)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--excludes",
            type=file_option,
            advanced=True,
            fingerprint=True,
            help="Path to optional scalastyle excludes file. Each line is a regex. (Blank lines "
            "and lines starting with '#' are ignored.) A file is skipped if its path "
            "(relative to the repo root) matches any of these regexes.",
        )
        # TODO: Use the task's log level instead of this separate verbosity knob.
        register("--verbose", type=bool, help="Enable verbose scalastyle output.")

    @classmethod
    def get_non_synthetic_scala_targets(cls, targets):
        return [
            target
            for target in targets
            if isinstance(target, Target)
            and target.has_sources(cls._SCALA_SOURCE_EXTENSION)
            and not target.is_synthetic
        ]

    @classmethod
    def get_non_excluded_scala_sources(cls, scalastyle_excluder, scala_targets):
        # Get all the sources from the targets with the path relative to build root.
        scala_sources = list()
        for target in scala_targets:
            scala_sources.extend(target.sources_relative_to_buildroot())

        # make sure only the sources with the .scala extension stay.
        scala_sources = [
            filename for filename in scala_sources if filename.endswith(cls._SCALA_SOURCE_EXTENSION)
        ]

        # filter out all sources matching exclude patterns, if specified in config.
        scala_sources = [
            source for source in scala_sources if scalastyle_excluder.should_include(source)
        ]

        return scala_sources

    @property
    def skip_execution(self):
        return Scalastyle.global_instance().options.skip

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._results_dir = os.path.join(self.workdir, "results")

    def _create_result_file(self, target):
        result_file = os.path.join(self._results_dir, target.id)
        touch(result_file)
        return result_file

    @property
    def cache_target_dirs(self):
        return True

    def execute(self):
        # Don't even try and validate options if we're irrelevant.
        targets = self.get_non_synthetic_scala_targets(self.get_targets())
        if not targets:
            return

        with self.invalidated(targets) as invalidation_check:
            invalid_targets = [vt.target for vt in invalidation_check.invalid_vts]

            scalastyle_config = self.validate_scalastyle_config()

            scalastyle_verbose = self.get_options().verbose
            scalastyle_quiet = self.get_options().quiet or False
            scalastyle_excluder = self.create_file_excluder()

            self.context.log.debug("Non synthetic scala targets to be checked:")
            for target in invalid_targets:
                self.context.log.debug(f"  {target.address.spec}")

            scala_sources = self.get_non_excluded_scala_sources(
                scalastyle_excluder, invalid_targets
            )
            self.context.log.debug("Non excluded scala sources to be checked:")
            for source in scala_sources:
                self.context.log.debug(f"  {source}")

            if scala_sources:

                def call(srcs):
                    def to_java_boolean(x):
                        return str(x).lower()

                    cp = ScalaPlatform.global_instance().style_classpath(self.context.products)
                    scalastyle_args = [
                        "-c",
                        scalastyle_config,
                        "-v",
                        to_java_boolean(scalastyle_verbose),
                        "-q",
                        to_java_boolean(scalastyle_quiet),
                    ]
                    return self.runjava(
                        classpath=cp,
                        main=self._MAIN,
                        jvm_options=self.get_options().jvm_options,
                        args=scalastyle_args + srcs,
                    )

                result = Xargs(call).execute(scala_sources)
                if result != 0:
                    raise TaskError(f"java {ScalastyleTask._MAIN} ... exited non-zero ({result})")

    def validate_scalastyle_config(self):
        config = Scalastyle.global_instance().options.config
        if not config:
            raise ScalastyleTask.UnspecifiedConfig()
        if not os.path.exists(config):
            raise ScalastyleTask.MissingConfig(config)
        return config

    def create_file_excluder(self):
        return FileExcluder(self.get_options().excludes, self.context.log)

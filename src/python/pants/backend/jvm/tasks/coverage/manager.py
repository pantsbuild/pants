# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import shutil

from pants.backend.jvm.subsystems.scoverage_platform import ScoveragePlatform
from pants.backend.jvm.tasks.coverage.cobertura import Cobertura
from pants.backend.jvm.tasks.coverage.engine import NoCoverage
from pants.backend.jvm.tasks.coverage.jacoco import Jacoco
from pants.backend.jvm.tasks.coverage.scoverage import Scoverage
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import safe_mkdir
from pants.util.strutil import safe_shlex_split

logger = logging.getLogger(__name__)


class CodeCoverageSettings:
    """A class containing settings for code coverage tasks."""

    def __init__(
        self,
        options,
        context,
        workdir,
        tool_classpath,
        confs,
        log,
        copy2=shutil.copy2,
        copytree=shutil.copytree,
        is_file=os.path.isfile,
        safe_md=safe_mkdir,
    ):
        self.options = options
        self.context = context
        self.workdir = workdir
        self.tool_classpath = tool_classpath
        self.confs = confs
        self.log = log

        self.coverage_dir = os.path.join(self.workdir, "coverage")

        self.coverage_jvm_options = []
        for jvm_option in options.coverage_jvm_options:
            self.coverage_jvm_options.extend(safe_shlex_split(jvm_option))

        self.coverage_open = options.coverage_open
        self.coverage_force = options.coverage_force

        # Injecting these methods to make unit testing cleaner.
        self.copy2 = copy2
        self.copytree = copytree
        self.is_file = is_file
        self.safe_makedir = safe_md

    @classmethod
    def from_task(cls, task, workdir=None):
        return cls(
            options=task.get_options(),
            context=task.context,
            workdir=workdir or task.workdir,
            tool_classpath=task.tool_classpath,
            confs=task.confs,
            log=task.context.log,
        )


class CodeCoverage(Subsystem):
    """Manages setup and construction of JVM code coverage engines."""

    options_scope = "coverage"

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (
            Cobertura.Factory,
            Jacoco.Factory,
            Scoverage.Factory,
        )

    # TODO(jtrobec): move these to subsystem scope after deprecating
    @staticmethod
    def register_junit_options(register, register_jvm_tool):
        register("--coverage", type=bool, fingerprint=True, help="Collect code coverage data.")
        register(
            "--coverage-processor",
            advanced=True,
            fingerprint=True,
            choices=["cobertura", "jacoco", "scoverage"],
            default=None,
            help="Which coverage processor to use if --coverage is enabled. If this option is "
            "unset but coverage is enabled implicitly or explicitly, defaults to 'cobertura'. "
            "If this option is explicitly set, implies --coverage. If this option is set to "
            "scoverage, then first scoverage MUST be enabled by passing option "
            "--scoverage-enable-scoverage.",
        )
        # We need to fingerprint this even though it nominally UI-only affecting option since the
        # presence of this option alone can implicitly flag on `--coverage`.
        register(
            "--coverage-open",
            type=bool,
            fingerprint=True,
            help="Open the generated HTML coverage report in a browser. Implies --coverage ",
        )

        register(
            "--coverage-jvm-options",
            advanced=True,
            type=list,
            fingerprint=True,
            help="JVM flags to be added when running the coverage processor. For example: "
            "{flag}=-Xmx4g {flag}=-Xms2g".format(flag="--coverage-jvm-options"),
        )
        register(
            "--coverage-force",
            advanced=True,
            type=bool,
            help="Attempt to run the reporting phase of coverage even if tests failed "
            "(defaults to False, as otherwise the coverage results would be unreliable).",
        )

        # register options for coverage engines
        # TODO(jtrobec): get rid of these calls when engines are dependent subsystems
        Cobertura.register_junit_options(register, register_jvm_tool)

    class InvalidCoverageEngine(Exception):
        """Indicates an invalid coverage engine type was selected."""

    def get_coverage_engine(self, task, output_dir, all_targets, execute_java):
        options = task.get_options()
        enable_scoverage = ScoveragePlatform.global_instance().get_options().enable_scoverage
        processor = options.coverage_processor

        if processor == "scoverage" and not enable_scoverage:
            raise self.InvalidCoverageEngine(
                "Cannot set processor to scoverage without first enabling "
                "scoverage (by passing --scoverage-enable-scoverage option)"
            )

        if enable_scoverage:
            if processor not in (None, "scoverage"):
                raise self.InvalidCoverageEngine(
                    f"Scoverage is enabled. "
                    f"Cannot use {processor} as the engine. Set engine to scoverage "
                    f"(--test-junit-coverage-processor=scoverage)"
                )
            processor = "scoverage"

        if options.coverage or processor or options.is_flagged("coverage_open"):
            settings = CodeCoverageSettings.from_task(task, workdir=output_dir)
            if processor in ("cobertura", None):
                return Cobertura.Factory.global_instance().create(
                    settings, all_targets, execute_java
                )
            elif processor == "jacoco":
                return Jacoco.Factory.global_instance().create(settings, all_targets, execute_java)
            elif processor == "scoverage":
                return Scoverage.Factory.global_instance().create(
                    settings, all_targets, execute_java
                )
            else:
                # NB: We should never get here since the `--coverage-processor` is restricted by `choices`,
                # but for clarity.
                raise self.InvalidCoverageEngine(
                    "Unknown and unexpected coverage processor {!r}!".format(
                        options.coverage_processor
                    )
                )
        else:
            return NoCoverage()

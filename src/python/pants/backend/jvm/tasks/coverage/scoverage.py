# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import os
import re

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.backend.jvm.tasks.coverage.engine import CoverageEngine
from pants.base.exceptions import TaskError
from pants.java.jar.jar_dependency import JarDependency
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import mergetree, safe_mkdir, safe_walk


class Scoverage(CoverageEngine):
    """Class to run coverage tests with scoverage."""

    class Factory(Subsystem, JvmToolMixin):

        # Cannot have the same scope as ScoveragePlatform, i.e they
        # both cannot share the scope `scoverage`.
        options_scope = "scoverage-report"

        @classmethod
        def register_options(cls, register):
            super(Scoverage.Factory, cls).register_options(register)

            def scoverage_jar(name, **kwargs):
                return JarDependency(
                    org="com.twitter.scoverage", name=name, rev="1.0.2-twitter", **kwargs
                )

            def slf4j_jar(name):
                return JarDependency(org="org.slf4j", name=name, rev="1.7.5")

            def scoverage_report_jar(**kwargs):
                return JarDependency(
                    org="org.pantsbuild",
                    name="scoverage-report-generator_2.12",
                    rev="0.0.3",
                    **kwargs,
                )

            # We need to inject report generator at runtime.
            cls.register_jvm_tool(
                register,
                "scoverage-report",
                classpath=[
                    scoverage_report_jar(),
                    JarDependency(org="commons-io", name="commons-io", rev="2.5"),
                    JarDependency(org="com.github.scopt", name="scopt_2.12", rev="3.7.0"),
                    slf4j_jar("slf4j-simple"),
                    slf4j_jar("slf4j-api"),
                    scoverage_jar("scalac-scoverage-plugin_2.12"),
                ],
            )

            register(
                "--target-filters",
                type=list,
                default=[],
                fingerprint=False,
                help="Regex patterns passed to scoverage report generator, specifying which targets "
                "should be "
                "included in reports. All targets matching any of the patterns will be "
                "included when generating reports. If no targets are specified, all "
                'targets are included, which would be the same as specifying ".*" as a '
                "filter.",
            )

            register(
                "--output-as-cobertura",
                type=bool,
                default=False,
                fingerprint=False,
                help="Export cobertura formats which would allow users to merge with cobertura coverage for java targets.",
            )

        def create(self, settings, targets, execute_java_for_targets):
            """
            :param settings: Generic code coverage settings.
            :type settings: :class:`CodeCoverageSettings`
            :param list targets: A list of targets to instrument and record code coverage for.
            :param execute_java_for_targets: A function that accepts a list of targets whose JVM platform
                                             constraints are used to pick a JVM `Distribution`. The
                                             function should also accept `*args` and `**kwargs` compatible
                                             with the remaining parameters accepted by
                                             `pants.java.util.execute_java`.
            """

            report_path = self.tool_classpath_from_products(
                settings.context.products, "scoverage-report", scope="scoverage-report"
            )

            opts = Scoverage.Factory.global_instance().get_options()
            target_filters = opts.target_filters
            output_as_cobertura = opts.output_as_cobertura
            coverage_output_dir = settings.context.options.for_global_scope().pants_distdir

            return Scoverage(
                report_path,
                target_filters,
                settings,
                targets,
                execute_java_for_targets,
                output_as_cobertura,
                coverage_output_dir=coverage_output_dir,
            )

    def __init__(
        self,
        report_path,
        target_filters,
        settings,
        targets,
        execute_java_for_targets,
        output_as_cobertura,
        coverage_output_dir=None,
    ):
        """
        :param settings: Generic code coverage settings.
        :type settings: :class:`CodeCoverageSettings`
        :param list targets: A list of targets to instrument and record code coverage for.
        :param execute_java_for_targets: A function that accepts a list of targets whose JVM platform
                                         constraints are used to pick a JVM `Distribution`. The function
                                         should also accept `*args` and `**kwargs` compatible with the
                                         remaining parameters accepted by
                                         `pants.java.util.execute_java`.
        :param str coverage_output_dir: An optional output directory to copy coverage reports to.
        """
        self._settings = settings
        self._context = settings.context
        self._targets = targets
        self._target_filters = target_filters
        self._execute_java = functools.partial(execute_java_for_targets, targets)
        self._coverage_force = settings.options.coverage_force
        self._report_path = report_path
        self._output_as_cobertura = output_as_cobertura
        self._coverage_output_dir = coverage_output_dir

    #
    def _iter_datafiles(self, output_dir):
        """All scoverage instrument files have the name "scoverage.coverage" and all measurement
        files are called "scoverage.measurements.<Thread ID>".

        This function is used in [instrument(output_dir)] function below to clean up all pre-
        existing scoverage files before generating new ones.
        """
        for root, _, files in safe_walk(output_dir):
            for f in files:
                if f.startswith("scoverage"):
                    yield os.path.join(root, f)

    #
    def _iter_datadirs(self, output_dir):
        """Used below for target filtering.

        Returns the parent directories under which all the scoverage data (for all targets) is
        stored. Currently, since all scoverage data for a test target is stored under
        `scoverage/measurements`, path to `scoverage/measurements` is returned.
        """
        for root, dirs, _ in safe_walk(output_dir):
            for d in dirs:
                if d.startswith("measurements"):
                    yield os.path.join(root, d)
                    break

    def instrument(self, output_dir):
        # Since scoverage does compile time instrumentation, we only need to clean-up existing runs.
        for datafile in self._iter_datafiles(output_dir):
            os.unlink(datafile)

    def run_modifications(self, output_dir):
        measurement_dir = os.path.join(output_dir, "scoverage", "measurements")
        safe_mkdir(measurement_dir, clean=True)
        data_dir_option = f"-Dscoverage_measurement_path={measurement_dir}"

        return self.RunModifications.create(extra_jvm_options=[data_dir_option])

    def report(self, output_dir, execution_failed_exception=None):
        if execution_failed_exception:
            self._settings.log.warn(f"Test failed: {execution_failed_exception}")
            if self._coverage_force:
                self._settings.log.warn(
                    "Generating report even though tests failed, because the"
                    "coverage-force flag is set."
                )
            else:
                return

        main = "org.pantsbuild.scoverage.report.ScoverageReport"
        scoverage_cp = self._report_path
        output_as_cobertura = self._output_as_cobertura
        html_report_path = os.path.join(output_dir, "scoverage", "reports", "html")
        xml_report_path = os.path.join(output_dir, "scoverage", "reports", "xml")
        safe_mkdir(html_report_path, clean=True)
        safe_mkdir(xml_report_path, clean=True)

        final_target_dirs = []
        for parent_measurements_dir in self._iter_datadirs(output_dir):
            final_target_dirs += self.filter_scoverage_targets(parent_measurements_dir)

        args = [
            "--measurementsDirPath",
            f"{output_dir}",
            "--htmlDirPath",
            f"{html_report_path}",
            "--xmlDirPath",
            f"{xml_report_path}",
            "--targetFilters",
            f"{','.join(final_target_dirs)}",
        ]

        if output_as_cobertura:
            args.append("--outputAsCobertura")

        result = self._execute_java(
            classpath=scoverage_cp,
            main=main,
            jvm_options=self._settings.coverage_jvm_options,
            args=args,
            workunit_factory=self._context.new_workunit,
            workunit_name="scoverage-report-generator",
        )

        if result != 0:
            raise TaskError(
                f"java {main} ... exited non-zero ({result}) - failed to scoverage-report-generator"
            )

        self._settings.log.info(f"Scoverage html reports available at {html_report_path}")
        self._settings.log.info(f"Scoverage xml reports available at {xml_report_path}")

        if self._coverage_output_dir:
            self._settings.log.debug(
                f"Scoverage output also written to: {self._coverage_output_dir}!"
            )
            mergetree(output_dir, self._coverage_output_dir)

        if self._settings.coverage_open:
            return os.path.join(html_report_path, "index.html")

    # Returns the directories under [measurements_dir] which need to
    # be passed to the report generator. If no filter is specified,
    # all the directories are returned.
    def filter_scoverage_targets(self, measurements_dir):
        return [d for d in os.listdir(measurements_dir) if self._include_dir(d)]

    def _include_dir(self, dir):
        if len(self._target_filters) == 0:
            return True
        else:
            for filter in self._target_filters:

                # If target filter is specified as an address spec, turn it into
                # target identifier as the scoverage directory names are made out of target identifiers.
                filter = filter.replace("/", ".").replace(":", ".")
                if re.search(filter, dir) is not None:
                    return True
        return False

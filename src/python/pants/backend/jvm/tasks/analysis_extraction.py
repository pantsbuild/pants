# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import io
import json
import os
import re
import subprocess
from contextlib import contextmanager

from pants.backend.jvm.subsystems.dependency_context import DependencyContext
from pants.backend.jvm.subsystems.zinc import Zinc
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants.util.contextutil import temporary_dir
from pants.util.memo import memoized_property


class AnalysisExtraction(NailgunTask):
    """A task that handles extracting product and dependency information from zinc analysis."""

    # The output JSON created by this task is not localized, but is used infrequently enough
    # that re-computing it from the zinc analysis (which _is_ cached) when necessary is fine.
    create_target_dirs = True

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (DependencyContext, Zinc.Factory)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        round_manager.require_data("runtime_classpath")

    @classmethod
    def product_types(cls):
        return ["product_deps_by_target"]

    def _create_products_if_should_run(self):
        """If this task should run, initialize empty products that it will populate.

        Returns true if the task should run.
        """

        should_run = False
        if self.context.products.is_required_data("product_deps_by_target"):
            should_run = True
            self.context.products.safe_create_data("product_deps_by_target", dict)
        return should_run

    @memoized_property
    def _zinc(self):
        return Zinc.Factory.global_instance().create(self.context.products, self.execution_strategy)

    def _jdeps_output_json(self, vt):
        return os.path.join(vt.results_dir, "jdeps_output.json")

    @contextmanager
    def aliased_classpaths(self, classpaths):
        """Create unique names for each classpath entry as symlinks in a temporary directory.
        returns: dict[str -> classpath entry] which maps string paths of symlinks to classpaths.

        ClasspathEntries generally point to a .jar of the .class files generated for java_library
        targets. These jars all have the same basename, z.jar, which confuses the `jdeps` tool.
        Jdeps expects unique, and descriptive, basenames for jars. When all basenames are the same
        the deps collide in the jdeps output, some .class files can't be found and the summary
        output is not complete.
        """
        with temporary_dir() as tempdir:
            aliases = {}
            for i, cp in enumerate(classpaths):
                alias = os.path.join(tempdir, f"{i}.jar" if not os.path.isdir(cp) else f"{i}")
                os.symlink(cp, alias)
                aliases[alias] = cp
            yield aliases

    def execute(self):
        if not self._create_products_if_should_run():
            return

        classpath_product = self.context.products.get_data("runtime_classpath")
        product_deps_by_target = self.context.products.get_data("product_deps_by_target")

        fingerprint_strategy = DependencyContext.global_instance().create_fingerprint_strategy(
            classpath_product
        )

        # classpath fingerprint strategy only works on targets with a classpath.
        targets = [target for target in self.context.targets() if hasattr(target, "strict_deps")]
        with self.invalidated(
            targets, fingerprint_strategy=fingerprint_strategy, invalidate_dependents=True
        ) as invalidation_check:
            for vt in invalidation_check.all_vts:
                # A list of class paths to the artifacts created by the target we are computing deps for.
                target_artifact_classpaths = [
                    path for _, path in classpath_product.get_for_target(vt.target)
                ]
                potential_deps_classpaths = self._zinc.compile_classpath(
                    "runtime_classpath", vt.target
                )

                jdeps_output_json = self._jdeps_output_json(vt)
                if not vt.valid:
                    self._run_jdeps_analysis(
                        vt.target,
                        target_artifact_classpaths,
                        potential_deps_classpaths,
                        jdeps_output_json,
                    )
                self._register_products(vt.target, jdeps_output_json, product_deps_by_target)

    @memoized_property
    def _jdeps_summary_line_regex(self):
        return re.compile(r"^.+\s->\s(.+)$")

    def _run_jdeps_analysis(
        self, target, target_artifact_classpaths, potential_deps_classpaths, jdeps_output_json
    ):
        with self.aliased_classpaths(potential_deps_classpaths) as classpaths_by_alias:
            with open(jdeps_output_json, "w") as f:
                if len(target_artifact_classpaths):
                    jdeps_stdout, jdeps_stderr = self._spawn_jdeps_command(
                        target, target_artifact_classpaths, classpaths_by_alias.keys()
                    ).communicate()
                    deps_classpaths = set()
                    for line in io.StringIO(jdeps_stdout.decode("utf-8")):
                        match = self._jdeps_summary_line_regex.fullmatch(line.strip())
                        if match is not None:
                            dep_name = match.group(1)
                            deps_classpaths.add(classpaths_by_alias.get(dep_name, dep_name))

                else:
                    deps_classpaths = []
                json.dump(list(deps_classpaths), f)

    def _spawn_jdeps_command(self, target, target_artifact_classpaths, potential_deps_classpaths):
        jdk = DistributionLocator.cached(jdk=True)
        tool_classpath = jdk.find_libs(["tools.jar"])
        potential_deps_classpath = ":".join(cp for cp in potential_deps_classpaths)

        args = ["-summary"]
        if potential_deps_classpath:
            args.extend(["-classpath", potential_deps_classpath])

        args.extend(target_artifact_classpaths)

        java_executor = SubprocessExecutor(jdk)
        return java_executor.spawn(
            classpath=tool_classpath,
            main="com.sun.tools.jdeps.Main",
            jvm_options=self.get_options().jvm_options,
            args=args,
            stdout=subprocess.PIPE,
        )

    def _register_products(self, target, jdeps_output_json, product_deps_by_target):
        with open(jdeps_output_json) as f:
            product_deps_by_target[target] = json.load(f)

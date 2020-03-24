# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.jvm.tasks.jvm_compile.rsc.rsc_compile import RscCompile
from pants.util.contextutil import environment_as
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


def ensure_compile_rsc_execution_strategy(workflow, **env_kwargs):
    """A decorator for running an integration test with ivy and coursier as the resolver."""

    def decorator(f):
        def wrapper(self, *args, **kwargs):
            for strategy in RscCompile.ExecutionStrategy:
                with environment_as(
                    HERMETIC_ENV="PANTS_COMPILE_RSC_EXECUTION_STRATEGY",
                    PANTS_COMPILE_RSC_EXECUTION_STRATEGY=strategy.value,
                    PANTS_COMPILE_RSC_WORKFLOW=workflow.value,
                    PANTS_CACHE_COMPILE_RSC_IGNORE="True",
                    **env_kwargs,
                ):
                    f(self, *args, **kwargs)

        return wrapper

    return decorator


class RscCompileIntegrationBase(BaseCompileIT):

    rsc_and_zinc = RscCompile.JvmCompileWorkflowType.rsc_and_zinc
    outline_and_zinc = RscCompile.JvmCompileWorkflowType.outline_and_zinc

    def _testproject_compile(
        self,
        project,
        target,
        clazz,
        *command_args,
        success=True,
        zinc_result=True,
        outline_result=True,
    ):
        testproject_base = "testprojects/src/scala/org/pantsbuild/testproject"
        project_dir = os.path.join(testproject_base, project)
        spec = f"{project_dir}:{target}"

        args = list(command_args) + ["compile", spec]

        with self.do_command_yielding_workdir(*args, success=success) as pants_run:
            results_path = f"compile/rsc/current/testprojects.src.scala.org.pantsbuild.testproject.{project}.{project}/current"
            zinc_compiled_classfile = os.path.join(
                pants_run.workdir,
                results_path,
                f"zinc/classes/org/pantsbuild/testproject/{project}/{clazz}.class",
            )
            outline_jar = os.path.join(pants_run.workdir, results_path, "rsc/m.jar")
            if zinc_result:
                self.assert_is_file(zinc_compiled_classfile)
            else:
                self.assert_is_not_file(zinc_compiled_classfile)

            if outline_result:
                self.assert_is_file(outline_jar)
            else:
                self.assert_is_not_file(outline_jar)

    def _test_hermetic_jvm_options(self, workflow):
        pants_run = self.run_pants(
            ["compile", "examples/src/scala/org/pantsbuild/example/hello/exe"],
            config={
                "cache.compile.rsc": {"ignore": True},
                "jvm-platform": {"compiler": "rsc"},
                "compile.rsc": {"workflow": workflow.value, "execution_strategy": "hermetic"},
                "rsc": {"jvm_options": ["-Djava.security.manager=java.util.Optional"]},
            },
        )
        self.assert_failure(pants_run)
        self.assertIn(
            "Could not create SecurityManager: java.util.Optional",
            pants_run.stdout_data,
            "Pants run is expected to fail and contain error about loading an invalid security "
            "manager class, but it did not.",
        )

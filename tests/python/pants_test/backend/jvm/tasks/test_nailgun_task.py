# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from textwrap import dedent

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.java.nailgun_executor import NailgunProcessGroup
from pants.testutil.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase
from pants.util.contextutil import pushd, temporary_dir
from pants.util.dirutil import safe_mkdir


class NailgunTaskTest(JvmToolTaskTestBase):
    class DetermineJavaCwd(NailgunTask):
        def execute(self):
            cwd_code = os.path.join(self.workdir, "Cwd.java")
            with open(cwd_code, "w") as fp:
                fp.write(
                    dedent(
                        """
                        import java.io.IOException;
                        import java.nio.charset.Charset;
                        import java.nio.file.Files;
                        import java.nio.file.Paths;
                        import java.util.Arrays;

                        import com.martiansoftware.nailgun.NGContext;

                        public class Cwd {
                          public static void nailMain(NGContext context) throws IOException {
                            String comm_file = context.getArgs()[0];
                            String cwd = context.getWorkingDirectory();
                            communicate(comm_file, cwd, "nailMain");
                          }

                          public static void main(String[] args) throws IOException {
                            String comm_file = args[0];
                            String cwd = System.getProperty("user.dir");
                            communicate(comm_file, cwd, "main");
                          }

                          private static void communicate(String comm_file, String cwd, String source)
                              throws IOException {

                            Files.write(Paths.get(comm_file), Arrays.asList(source, cwd), Charset.forName("UTF-8"));
                          }
                        }
                        """
                    )
                )

            javac = self.dist.binary("javac")
            nailgun_cp = self.tool_classpath("nailgun-server")

            classes_dir = os.path.join(self.workdir, "classes")
            safe_mkdir(classes_dir)

            subprocess.check_call(
                [javac, "-cp", os.pathsep.join(nailgun_cp), "-d", classes_dir, "-Werror", cwd_code]
            )

            comm_file = os.path.join(self.workdir, "comm_file")
            with temporary_dir() as python_cwd:
                with pushd(python_cwd):
                    exit_code = self.runjava(nailgun_cp + [classes_dir], "Cwd", args=[comm_file])
                    if exit_code != 0:
                        raise TaskError(exit_code=exit_code)

                    with open(comm_file, "rb") as fp:
                        source, java_cwd = fp.read().strip().decode().splitlines()
                        return source, java_cwd, python_cwd

    @classmethod
    def task_type(cls):
        return cls.DetermineJavaCwd

    def assert_cwd_is_buildroot(self, expected_source):
        task = self.prepare_execute(self.context())
        source, java_cwd, python_cwd = task.execute()

        self.assertEqual(source, expected_source)

        buildroot = os.path.realpath(get_buildroot())
        self.assertEqual(buildroot, os.path.realpath(java_cwd))
        self.assertNotEqual(buildroot, os.path.realpath(python_cwd))

    def test_execution_strategy_nailgun(self):
        self.set_options(execution_strategy=NailgunTask.ExecutionStrategy.nailgun)
        self.addCleanup(
            lambda: NailgunProcessGroup(metadata_base_dir=self.subprocess_dir).killall()
        )

        self.assert_cwd_is_buildroot(expected_source="nailMain")

    def test_execution_strategy_subprocess(self):
        self.set_options(execution_strategy=NailgunTask.ExecutionStrategy.subprocess)

        self.assert_cwd_is_buildroot(expected_source="main")

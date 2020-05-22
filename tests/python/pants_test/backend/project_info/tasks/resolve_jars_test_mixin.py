# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from textwrap import dedent

from pants.util.contextutil import temporary_dir


class ResolveJarsTestMixin:
    """Mixin for evaluating tasks which resolve their own source and javadoc jars (such as
    Export)."""

    def evaluate_subtask(self, targets, workdir, load_extra_confs, extra_args, expected_jars):
        """Evaluate the underlying task with the given address specs.

        :param targets: the list of targets.
        :param string workdir: the working directory to execute in.
        :param bool load_extra_confs: whether to attempt to download sources and javadocs.
        :param list extra_args: extra args to pass to the task.
        :param list expected_jars: list of jars that were expected to be resolved.
        """
        raise NotImplementedError()

    def _test_jar_lib_with_url(self, load_all):
        with self.temporary_workdir() as workdir:
            with self.temporary_sourcedir() as source_dir:
                with temporary_dir() as dist_dir:
                    os.makedirs(os.path.join(source_dir, "src"))
                    with open(os.path.join(source_dir, "src", "BUILD.one"), "w+") as f:
                        f.write(
                            dedent(
                                """
                                jvm_binary(name='synthetic',
                                  sources=['Main.java'],
                                )
                                """
                            )
                        )
                    with open(os.path.join(source_dir, "src", "Main.java"), "w+") as f:
                        f.write(
                            dedent(
                                """
                                public class Main {
                                  public static void main(String[] args) {
                                    System.out.println("Hello.");
                                  }
                                }
                                """
                            )
                        )
                    with open(os.path.join(source_dir, "src", "Foo.java"), "w+") as f:
                        f.write(
                            dedent(
                                """
                                public class Foo {
                                  public static void main(String[] args) {
                                    Main.main(args);
                                  }
                                }
                                """
                            )
                        )

                    binary_target = f"{os.path.join(source_dir, 'src')}:synthetic"
                    pants_run = self.run_pants_with_workdir(
                        ["binary", binary_target, f"--pants-distdir={dist_dir}"], workdir
                    )
                    self.assert_success(pants_run)
                    jar_path = os.path.realpath(os.path.join(dist_dir, "synthetic.jar"))
                    self.assertTrue(os.path.exists(jar_path), "Synthetic binary was not created!")
                    jar_url = f"file://{os.path.abspath(jar_path)}"

                    with open(os.path.join(source_dir, "src", "BUILD.two"), "w+") as f:
                        f.write(
                            dedent(
                                """
                                jar_library(name='lib_with_url',
                                  jars=[
                                    jar(org='org.pantsbuild', name='synthetic-test-jar', rev='1.2.3',
                                    url='{jar_url}')
                                  ],
                                )

                                java_library(name='src',
                                  sources=['Foo.java'],
                                  dependencies=[':lib_with_url'],
                                )
                                """
                            ).format(jar_url=jar_url)
                        )

                    spec_names = ["lib_with_url", "src"]

                    targets = [f"{os.path.join(source_dir, 'src')}:{name}" for name in spec_names]

                    self.evaluate_subtask(
                        targets,
                        workdir,
                        load_all,
                        extra_args=[],
                        expected_jars=["org.pantsbuild:synthetic-test-jar:1.2.3"],
                    )

    def test_jar_lib_with_url_resolve_default(self):
        self._test_jar_lib_with_url(False)

    def test_jar_lib_with_url_resolve_all(self):
        self._test_jar_lib_with_url(True)

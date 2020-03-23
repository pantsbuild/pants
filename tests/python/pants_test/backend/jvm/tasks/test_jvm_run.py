# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
from contextlib import contextmanager

from pants.backend.jvm.subsystems.jvm import JVM
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.jvm_run import JvmRun
from pants.testutil.jvm.jvm_task_test_base import JvmTaskTestBase
from pants.util.contextutil import pushd, temporary_dir


class JvmRunTest(JvmTaskTestBase):
    @classmethod
    def task_type(cls):
        return JvmRun

    @contextmanager
    def setup_cmdline_run(self, extra_jvm_options=None, **options):
        """Run the JvmRun task in command line only mode  with the specified extra options.

        :returns: the command line string
        """
        # NB: We must set `--run-args=[]` because the unit test does not properly set up the
        # `RunOptions(GoalSubsystem)`.
        self.set_options(only_write_cmd_line="a", args=[], **options)
        jvm_binary = self.make_target(
            "src/java/org/pantsbuild:binary",
            JvmBinary,
            main="org.pantsbuild.Binary",
            extra_jvm_options=extra_jvm_options,
        )
        context = self.context(target_roots=[jvm_binary])
        jvm_run = self.create_task(context)
        self._cmdline_classpath = [os.path.join(self.pants_workdir, c) for c in ["bob", "fred"]]
        self.populate_runtime_classpath(context=jvm_run.context, classpath=self._cmdline_classpath)
        with temporary_dir() as pwd:
            with pushd(pwd):
                cmdline_file = os.path.join(pwd, "a")
                self.assertFalse(os.path.exists(cmdline_file))
                jvm_run.execute()
                self.assertTrue(os.path.exists(cmdline_file))
                with open(cmdline_file, "r") as fp:
                    contents = fp.read()
                    yield contents

    def test_cmdline_only(self):
        main_entry = "org.pantsbuild.Binary"
        with self.setup_cmdline_run(main=main_entry) as cmdline:
            self.assertTrue(self._match_cmdline_regex(cmdline, main_entry))

    def test_opt_main(self):
        main_entry = "org.pantsbuild.OptMain"
        with self.setup_cmdline_run(main=main_entry) as cmdline:
            self.assertTrue(self._match_cmdline_regex(cmdline, main_entry))

    def test_extra_jvm_option(self):
        options = ["-Dexample.property1=1", "-Dexample.property2=1"]
        with self.setup_cmdline_run(extra_jvm_options=options) as cmdline:
            for option in options:
                self.assertIn(option, cmdline)

    def _match_cmdline_regex(self, cmdline, main):
        # Original classpath is embedded in the manifest file of a synthetic jar, just verify
        # classpath is a singleton jar here.
        if JVM.options_default:
            opts_str = " ".join(JVM.options_default) + " "
        else:
            opts_str = ""
        m = re.search(r"java {}-cp [^:]*\.jar {}".format(opts_str, main), cmdline)
        return m is not None

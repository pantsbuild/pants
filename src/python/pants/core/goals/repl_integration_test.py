# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.target_types import ProtobufLibrary
from pants.backend.python.rules import ancestor_files, pex, pex_from_targets, python_sources
from pants.backend.python.rules import repl as python_repl
from pants.backend.python.rules.pex import PexProcess
from pants.backend.python.target_types import PythonLibrary
from pants.core.goals.repl import Repl
from pants.core.goals.repl import rules as repl_rules
from pants.core.util_rules import archive, external_tool, stripped_source_files
from pants.testutil.test_base import TestBase
from pants.engine.process import Process
from pants.engine.rules import QueryRule
from pants.option.options_bootstrapper import OptionsBootstrapper


class ReplTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *repl_rules(),
            *python_repl.rules(),
            *pex.rules(),
            *archive.rules(),
            *external_tool.rules(),
            *python_sources.rules(),
            *pex_from_targets.rules(),
            *stripped_source_files.rules(),
            *ancestor_files.rules(),
            QueryRule(Process, (PexProcess, OptionsBootstrapper)),
        )

    @classmethod
    def target_types(cls):
        return [ProtobufLibrary, PythonLibrary]

    def setup_sources(self) -> None:
        self.add_to_build_file("src/python", "protobuf_library(name='proto')\n")
        self.add_to_build_file("src/python", "python_library(dependencies=[':proto'])\n")
        self.create_file("src/python/foo.proto", 'syntax = "proto3";message Foo {}')
        self.create_file("src/python/lib.py", "from foo import Foo\nclass SomeClass:\n  pass\n")

    def test_repl_with_targets(self) -> None:
        # TODO(#9108): A mock InteractiveRunner that allows us to actually run code in
        #  the repl and verify that, e.g., the generated protobuf code is available.
        #  Right now this test prepares for that by including generated code, but cannot
        #  actually verify it.
        self.setup_sources()
        result = self.run_goal_rule(
            Repl,
            global_args=[
                "--backend-packages=pants.backend.python",
                "--backend-packages=pants.backend.codegen.protobuf.python",
            ],
            args=["src/python/lib.py"],
        )
        assert result.exit_code == 0

    def test_repl_ipython(self) -> None:
        self.setup_sources()
        result = self.run_goal_rule(
            Repl,
            global_args=[
                "--backend-packages=pants.backend.python",
                "--backend-packages=pants.backend.codegen.protobuf.python",
            ],
            args=["--shell=ipython", "src/python/lib.py"],
        )
        assert result.exit_code == 0

    def test_repl_bogus_repl_name(self) -> None:
        self.setup_sources()
        result = self.run_goal_rule(
            Repl,
            global_args=["--backend-packages=pants.backend.python"],
            args=["--shell=bogus-repl", "src/python/lib.py"],
        )
        assert result.exit_code == -1
        assert "'bogus-repl' is not a registered REPL. Available REPLs" in result.stderr

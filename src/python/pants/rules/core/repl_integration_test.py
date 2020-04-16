# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules import (
    download_pex_bin,
    importable_python_sources,
    pex,
    pex_from_targets,
    repl,
)
from pants.backend.python.rules.repl import PythonRepl
from pants.backend.python.rules.targets import PythonLibrary
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.targets.python_library import PythonLibrary as PythonLibraryV1
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.fs import FileContent
from pants.engine.interactive_runner import InteractiveRunner
from pants.engine.rules import RootRule
from pants.rules.core import strip_source_roots
from pants.rules.core.repl import Repl, run_repl
from pants.testutil.goal_rule_test_base import GoalRuleTestBase


class ReplTest(GoalRuleTestBase):
    goal_cls = Repl

    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *repl.rules(),
            run_repl,
            *pex.rules(),
            *download_pex_bin.rules(),
            *importable_python_sources.rules(),
            *pex_from_targets.rules(),
            *python_native_code.rules(),
            *strip_source_roots.rules(),
            *subprocess_environment.rules(),
            RootRule(PythonRepl),
        )

    @classmethod
    def alias_groups(cls) -> BuildFileAliases:
        return BuildFileAliases(targets={"python_library": PythonLibraryV1})

    @classmethod
    def target_types(cls):
        return [PythonLibrary]

    def setup_python_library(self) -> None:
        library_source = FileContent(path="some_lib.py", content=b"class SomeClass:\n  pass\n")
        self.create_library(
            name="some_lib",
            target_type="python_library",
            path="src/python",
            sources=["some_lib.py"],
        )

        self.create_file(
            relpath="src/python/some_lib.py", contents=library_source.content.decode(),
        )

    def test_repl_with_targets(self) -> None:
        self.setup_python_library()
        output = self.execute_rule(
            global_args=["--backend-packages2=pants.backend.python"],
            args=["src/python:some_lib"],
            additional_params=[InteractiveRunner(self.scheduler)],
        )
        assert output == "REPL exited successfully."

    def test_repl_ipython(self) -> None:
        self.setup_python_library()
        output = self.execute_rule(
            global_args=["--backend-packages2=pants.backend.python"],
            args=["--shell=ipython", "src/python:some_lib"],
            additional_params=[InteractiveRunner(self.scheduler)],
        )
        assert output == "REPL exited successfully."

    def test_repl_bogus_repl_name(self) -> None:
        self.setup_python_library()
        output = self.execute_rule(
            global_args=["--backend-packages2=pants.backend.python"],
            args=["--shell=bogus-repl", "src/python:some_lib"],
            additional_params=[InteractiveRunner(self.scheduler)],
            exit_code=-1,
        )

        assert "bogus-repl is not an installed REPL program. Available REPLs:" in output

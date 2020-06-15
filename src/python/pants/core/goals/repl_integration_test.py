# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules import (
    download_pex_bin,
    importable_python_sources,
    pex,
    pex_from_targets,
)
from pants.backend.python.rules import repl as python_repl
from pants.backend.python.rules.repl import PythonRepl
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.target_types import PythonLibrary
from pants.core.goals.repl import Repl
from pants.core.goals.repl import rules as repl_rules
from pants.core.util_rules import archive, external_tool, strip_source_roots
from pants.engine.interactive_process import InteractiveRunner
from pants.engine.rules import RootRule
from pants.testutil.goal_rule_test_base import GoalRuleTestBase


class ReplTest(GoalRuleTestBase):
    goal_cls = Repl

    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *repl_rules(),
            *python_repl.rules(),
            *pex.rules(),
            *download_pex_bin.rules(),
            *archive.rules(),
            *external_tool.rules(),
            *importable_python_sources.rules(),
            *pex_from_targets.rules(),
            *python_native_code.rules(),
            *strip_source_roots.rules(),
            *subprocess_environment.rules(),
            RootRule(PythonRepl),
        )

    @classmethod
    def target_types(cls):
        return [PythonLibrary]

    def setup_python_library(self) -> None:
        self.add_to_build_file("src/python", "python_library()")
        self.create_file("src/python/lib.py", "class SomeClass:\n  pass\n")

    def test_repl_with_targets(self) -> None:
        self.setup_python_library()
        self.execute_rule(
            global_args=[
                "--backend-packages2=pants.backend.python",
                "--source-root-patterns=src/python",
            ],
            args=["src/python/lib.py"],
            additional_params=[InteractiveRunner(self.scheduler)],
        )

    def test_repl_ipython(self) -> None:
        self.setup_python_library()
        self.execute_rule(
            global_args=[
                "--backend-packages2=pants.backend.python",
                "--source-root-patterns=src/python",
            ],
            args=["--shell=ipython", "src/python/lib.py"],
            additional_params=[InteractiveRunner(self.scheduler)],
        )

    def test_repl_bogus_repl_name(self) -> None:
        self.setup_python_library()
        result = self.execute_rule(
            global_args=[
                "--backend-packages2=pants.backend.python",
                "--source-root-patterns=src/python",
            ],
            args=["--shell=bogus-repl", "src/python/lib.py"],
            additional_params=[InteractiveRunner(self.scheduler)],
            exit_code=-1,
        )
        assert "'bogus-repl' is not a registered REPL. Available REPLs" in result.stderr

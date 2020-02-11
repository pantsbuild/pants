# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules import (
  download_pex_bin,
  inject_init,
  pex,
  pex_from_target_closure,
  prepare_chrooted_python_sources,
  repl,
)
from pants.backend.python.rules.repl import PythonRepl
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.targets.python_library import PythonLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.fs import FileContent
from pants.engine.interactive_runner import InteractiveRunner
from pants.engine.rules import RootRule
from pants.rules.core import strip_source_root
from pants.testutil.goal_rule_test_base import GoalRuleTestBase
from pants.testutil.subsystem.util import init_subsystems


class PythonReplTest(GoalRuleTestBase):
  goal_cls = PythonRepl

  def setUp(self):
    super().setUp()
    init_subsystems([download_pex_bin.DownloadedPexBin.Factory])

  @classmethod
  def rules(cls):
    return (
      *super().rules(),
      *repl.rules(),
      *inject_init.rules(),
      *pex.rules(),
      download_pex_bin.download_pex_bin,
      *pex_from_target_closure.rules(),
      *prepare_chrooted_python_sources.rules(),
      *python_native_code.rules(),
      *strip_source_root.rules(),
      *subprocess_environment.rules(),
      RootRule(download_pex_bin.DownloadedPexBin.Factory),
    )

  @classmethod
  def alias_groups(cls) -> BuildFileAliases:
    return BuildFileAliases(
      targets={
        "python_library": PythonLibrary,
      }
    )

  def test_repl_with_targets(self):
    library_source = FileContent(path="some_lib.py", content=b"class SomeClass:\n  pass\n")
    self.create_library(
      name="some_lib",
      target_type="python_library",
      path="src/python",
      sources=["some_lib.py"]
    )

    self.create_file(
      relpath="src/python/some_lib.py",
      contents=library_source.content.decode(),
    )

    additional_params = [
      InteractiveRunner(self.scheduler),
      download_pex_bin.DownloadedPexBin.Factory.global_instance(),
    ]

    output = self.execute_rule(args=["src/python:some_lib"], additional_params=additional_params)
    assert output == "REPL exited successfully."

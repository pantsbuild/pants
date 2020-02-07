# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from typing import List, Optional

import pytest

from pants.backend.python.lint.pylint.rules import PylintTarget
from pants.backend.python.lint.pylint.rules import rules as pylint_rules
from pants.backend.python.rules import (
  download_pex_bin,
  inject_init,
  pex,
  prepare_chrooted_python_sources,
)
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.targets.python_library import PythonLibrary
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.fs import FileContent, InputFilesContent, Snapshot
from pants.engine.legacy.structs import PythonTargetAdaptor
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.rules.core import strip_source_root
from pants.rules.core.lint import LintResult
from pants.source.wrapped_globs import EagerFilesetWithSpec
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class PylintIntegrationTest(TestBase):
  source_root = "test"
  good_source = FileContent(path="good.py", content=b"'''docstring'''\nVAR = 42\n")
  bad_source = FileContent(path="bad.py", content=b"VAR = 42\n")

  def write_file(self, file_content: FileContent) -> None:
    self.create_file(
      relpath=str(PurePath(self.source_root, file_content.path)),
      contents=file_content.content.decode(),
    )

  @classmethod
  def alias_groups(cls) -> BuildFileAliases:
    return BuildFileAliases(targets={'python_library': PythonLibrary})

  @classmethod
  def rules(cls):
    return (
      *super().rules(),
      *pylint_rules(),
      *download_pex_bin.rules(),
      *inject_init.rules(),
      *pex.rules(),
      *prepare_chrooted_python_sources.rules(),
      *strip_source_root.rules(),
      *python_native_code.rules(),
      *subprocess_environment.rules(),
      RootRule(PylintTarget),
    )

  def run_pylint(
    self,
    source_files: List[FileContent],
    *,
    config: Optional[str] = None,
    passthrough_args: Optional[str] = None,
    interpreter_constraints: Optional[str] = None,
    skip: bool = False,
  ) -> LintResult:
    args = ["--backend-packages2=pants.backend.python.lint.pylint"]
    if config:
      # TODO: figure out how to get this file to exist...
      self.create_file(relpath="pylintrc", contents=config)
      args.append("--pylint-config=pylintrc")
    if passthrough_args:
      args.append(f"--pylint-args='{passthrough_args}'")
    if skip:
      args.append(f"--pylint-skip")
    input_snapshot = self.request_single_product(Snapshot, InputFilesContent(source_files))
    target = PylintTarget(
      PythonTargetAdaptor(
        sources=EagerFilesetWithSpec(self.source_root, {'globs': []}, snapshot=input_snapshot),
        address=Address.parse(f"{self.source_root}:target"),
        compatibility=[interpreter_constraints] if interpreter_constraints else None,
      )
    )
    return self.request_single_product(
      LintResult, Params(target, create_options_bootstrapper(args=args)),
    )

  def test_single_passing_source(self) -> None:
    self.create_library(path=self.source_root, target_type="python_library", name="target")
    self.write_file(self.good_source)
    result = self.run_pylint([self.good_source])
    assert result.exit_code == 0
    assert "Your code has been rated at 10.00/10" in result.stdout.strip()

  def test_single_failing_source(self) -> None:
    self.create_library(path=self.source_root, target_type="python_library", name="target")
    self.write_file(self.bad_source)
    result = self.run_pylint([self.bad_source])
    assert result.exit_code == 16
    assert "bad.py:1:0: C0114" in result.stdout

  def test_mixed_sources(self) -> None:
    self.create_library(path=self.source_root, target_type="python_library", name="target")
    self.write_file(self.good_source)
    self.write_file(self.bad_source)
    result = self.run_pylint([self.good_source, self.bad_source])
    assert result.exit_code == 16
    assert "good.py" not in result.stdout
    assert "bad.py:1:0: C0114" in result.stdout

  @pytest.mark.skip(reason="Get config file creation to work with options parsing")
  def test_respects_config_file(self) -> None:
    self.create_library(path=self.source_root, target_type="python_library", name="target")
    self.write_file(self.bad_source)
    result = self.run_pylint([self.bad_source], config="[pylint]\disable = C0114\n")
    assert result.exit_code == 0
    assert result.stdout.strip() == ""

  def test_respects_passthrough_args(self) -> None:
    self.create_library(path=self.source_root, target_type="python_library", name="target")
    self.write_file(self.bad_source)
    result = self.run_pylint([self.bad_source], passthrough_args="--disable=C0114")
    assert result.exit_code == 0
    assert "Your code has been rated at 10.00/10" in result.stdout.strip()

  def test_skip(self) -> None:
    result = self.run_pylint([self.bad_source], skip=True)
    assert result == LintResult.noop()

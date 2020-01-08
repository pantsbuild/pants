# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional

from pants.backend.python.lint.flake8.rules import Flake8Target
from pants.backend.python.lint.flake8.rules import rules as flake8_rules
from pants.backend.python.lint.flake8.subsystem import Flake8
from pants.backend.python.rules import download_pex_bin, pex
from pants.backend.python.rules.pex import CreatePex
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.subsystems.python_native_code import PythonNativeCode
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEnvironment
from pants.backend.python.targets.python_library import PythonLibrary
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.fs import FileContent, InputFilesContent, Snapshot
from pants.engine.legacy.structs import PythonTargetAdaptor
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.rules.core.lint import LintResult
from pants.source.wrapped_globs import EagerFilesetWithSpec
from pants.testutil.interpreter_selection_utils import skip_unless_python27_and_python3_present
from pants.testutil.subsystem.util import global_subsystem_instance, init_subsystems
from pants.testutil.test_base import TestBase


class Flake8IntegrationTest(TestBase):
  good_source = FileContent(path="test/good.py", content=b"print('Nothing suspicious here..')\n")
  bad_source = FileContent(path="test/bad.py", content=b"import typing\n")  # unused import
  py3_only_source = FileContent(path="test/py3.py", content=b"version: str = 'Py3 > Py2'\n")

  @classmethod
  def alias_groups(cls) -> BuildFileAliases:
    return BuildFileAliases(targets={'python_library': PythonLibrary})

  @classmethod
  def rules(cls):
    return (
      *super().rules(),
      *flake8_rules(),
      *download_pex_bin.rules(),
      *pex.rules(),
      *python_native_code.rules(),
      *subprocess_environment.rules(),
      RootRule(CreatePex),
      RootRule(Flake8),
      RootRule(Flake8Target),
      RootRule(PythonSetup),
      RootRule(PythonNativeCode),
      RootRule(SubprocessEnvironment),
    )

  def setUp(self):
    super().setUp()
    init_subsystems([Flake8, PythonSetup, PythonNativeCode, SubprocessEnvironment])

  def run_flake8(
    self,
    source_files: List[FileContent],
    *,
    config: Optional[str] = None,
    passthrough_args: Optional[str] = None,
    interpreter_constraints: Optional[str] = None,
    skip: bool = False,
  ) -> LintResult:
    if config is not None:
      self.create_file(relpath=".flake8", contents=config)
    input_snapshot = self.request_single_product(Snapshot, InputFilesContent(source_files))
    target = Flake8Target(
      PythonTargetAdaptor(
        sources=EagerFilesetWithSpec('test', {'globs': []}, snapshot=input_snapshot),
        address=Address.parse("test:target"),
        compatibility=[interpreter_constraints] if interpreter_constraints else None,
      )
    )
    flake8_subsystem = global_subsystem_instance(
      Flake8, options={Flake8.options_scope: {
        "config": ".flake8" if config else None,
        "args": [passthrough_args] if passthrough_args else [],
        "skip": skip,
      }}
    )
    return self.request_single_product(
      LintResult,
      Params(
        target,
        flake8_subsystem,
        PythonNativeCode.global_instance(),
        PythonSetup.global_instance(),
        SubprocessEnvironment.global_instance()
      )
    )

  def test_single_passing_source(self) -> None:
    result = self.run_flake8([self.good_source])
    assert result.exit_code == 0
    assert result.stdout.strip() == ""

  def test_single_failing_source(self) -> None:
    result = self.run_flake8([self.bad_source])
    assert result.exit_code == 1
    assert "test/bad.py:1:1: F401" in result.stdout

  def test_mixed_sources(self) -> None:
    result = self.run_flake8([self.good_source, self.bad_source])
    assert result.exit_code == 1
    assert "test/good.py" not in result.stdout
    assert "test/bad.py:1:1: F401" in result.stdout

  @skip_unless_python27_and_python3_present
  def test_uses_correct_python_version(self) -> None:
    py2_result = self.run_flake8([self.py3_only_source], interpreter_constraints='CPython==2.7.*')
    assert py2_result.exit_code == 1
    assert "test/py3.py:1:8: E999 SyntaxError" in py2_result.stdout
    py3_result = self.run_flake8([self.py3_only_source], interpreter_constraints='CPython>=3.6')
    assert py3_result.exit_code == 0
    assert py3_result.stdout.strip() == ""

  def test_respects_config_file(self) -> None:
    result = self.run_flake8([self.bad_source], config="[flake8]\nignore = F401\n")
    assert result.exit_code == 0
    assert result.stdout.strip() == ""

  def test_respects_passthrough_args(self) -> None:
    result = self.run_flake8([self.bad_source], passthrough_args="--ignore=F401")
    assert result.exit_code == 0
    assert result.stdout.strip() == ""

  def test_skip(self) -> None:
    result = self.run_flake8([self.bad_source], skip=True)
    assert result == LintResult.noop()

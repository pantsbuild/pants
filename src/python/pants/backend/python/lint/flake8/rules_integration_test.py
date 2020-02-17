# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional

import pytest

from pants.backend.python.lint.flake8.rules import Flake8Target
from pants.backend.python.lint.flake8.rules import rules as flake8_rules
from pants.backend.python.rules import download_pex_bin
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.specs import FilesystemLiteralSpec, OriginSpec, SingleAddress
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.fs import FileContent, InputFilesContent, Snapshot
from pants.engine.legacy.structs import PythonTargetAdaptor, PythonTargetAdaptorWithOrigin
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.rules.core.lint import LintResult
from pants.source.wrapped_globs import EagerFilesetWithSpec
from pants.testutil.interpreter_selection_utils import skip_unless_python27_and_python3_present
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.subsystem.util import init_subsystems
from pants.testutil.test_base import TestBase


class Flake8IntegrationTest(TestBase):

  def setUp(self):
    super().setUp()
    init_subsystems([download_pex_bin.DownloadedPexBin.Factory])

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
      download_pex_bin.download_pex_bin,
      RootRule(Flake8Target),
      RootRule(download_pex_bin.DownloadedPexBin.Factory),
    )

  def run_flake8(
    self,
    source_files: List[FileContent],
    *,
    config: Optional[str] = None,
    passthrough_args: Optional[str] = None,
    interpreter_constraints: Optional[str] = None,
    skip: bool = False,
    origin: Optional[OriginSpec] = None,
  ) -> LintResult:
    args = ["--backend-packages2=pants.backend.python.lint.flake8"]
    if config:
      # TODO: figure out how to get this file to exist...
      self.create_file(relpath=".flake8", contents=config)
      args.append("--flake8-config=.flake8")
    if passthrough_args:
      args.append(f"--flake8-args='{passthrough_args}'")
    if skip:
      args.append(f"--flake8-skip")
    input_snapshot = self.request_single_product(Snapshot, InputFilesContent(source_files))
    adaptor = PythonTargetAdaptor(
      sources=EagerFilesetWithSpec('test', {'globs': []}, snapshot=input_snapshot),
      address=Address.parse("test:target"),
      compatibility=[interpreter_constraints] if interpreter_constraints else None,
    )
    if origin is None:
      origin = SingleAddress(directory="test", name="target")
    target = Flake8Target(PythonTargetAdaptorWithOrigin(adaptor, origin))
    return self.request_single_product(
      LintResult, Params(
        target,
        create_options_bootstrapper(args=args),
        download_pex_bin.DownloadedPexBin.Factory.global_instance(),
      ),
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

  def test_precise_file_args(self) -> None:
    file_arg = FilesystemLiteralSpec(self.good_source.path)
    result = self.run_flake8([self.good_source, self.bad_source], origin=file_arg)
    assert result.exit_code == 0
    assert result.stdout.strip() == ""

  @skip_unless_python27_and_python3_present
  def test_uses_correct_python_version(self) -> None:
    py2_result = self.run_flake8([self.py3_only_source], interpreter_constraints='CPython==2.7.*')
    assert py2_result.exit_code == 1
    assert "test/py3.py:1:8: E999 SyntaxError" in py2_result.stdout
    py3_result = self.run_flake8([self.py3_only_source], interpreter_constraints='CPython>=3.6')
    assert py3_result.exit_code == 0
    assert py3_result.stdout.strip() == ""

  @pytest.mark.skip(reason="Get config file creation to work with options parsing")
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

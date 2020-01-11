# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, Sequence

from pants.backend.python.lint.bandit.rules import BanditTarget
from pants.backend.python.lint.bandit.rules import rules as bandit_rules
from pants.backend.python.lint.bandit.subsystem import Bandit
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
from pants.testutil.subsystem.util import global_subsystem_instance, init_subsystems
from pants.testutil.test_base import TestBase


class BanditIntegrationTest(TestBase):
  good_source = FileContent(path="test/good.py", content=b"hashlib.sha256()\n")
  bad_source = FileContent(path="test/bad.py", content=b"hashlib.md5()\n")
  # MD5 is a insecure hashing function

  @classmethod
  def alias_groups(cls) -> BuildFileAliases:
    return BuildFileAliases(targets={'python_library': PythonLibrary})

  @classmethod
  def rules(cls):
    return (
      *super().rules(),
      *bandit_rules(),
      *download_pex_bin.rules(),
      *pex.rules(),
      *python_native_code.rules(),
      *subprocess_environment.rules(),
      RootRule(CreatePex),
      RootRule(Bandit),
      RootRule(BanditTarget),
      RootRule(PythonSetup),
      RootRule(PythonNativeCode),
      RootRule(SubprocessEnvironment),
    )

  def setUp(self):
    super().setUp()
    init_subsystems([Bandit, PythonSetup, PythonNativeCode, SubprocessEnvironment])

  def run_bandit(
    self,
    source_files: List[FileContent],
    *,
    config: Optional[str] = None,
    passthrough_args: Optional[Sequence[str]] = None,
    interpreter_constraints: Optional[Sequence[str]] = None,
    skip: bool = False,
  ) -> LintResult:
    if config is not None:
      self.create_file(relpath="bandit.yaml", contents=config)
    input_snapshot = self.request_single_product(Snapshot, InputFilesContent(source_files))
    target = BanditTarget(
      PythonTargetAdaptor(
        sources=EagerFilesetWithSpec('test', {'globs': []}, snapshot=input_snapshot),
        address=Address.parse("test:target"),
        compatibility=interpreter_constraints,
      )
    )
    bandit_subsystem = global_subsystem_instance(
      Bandit, options={Bandit.options_scope: {
        "config": "bandit.yaml" if config else None,
        "args": passthrough_args or [],
        "skip": skip,
      }}
    )
    return self.request_single_product(
      LintResult,
      Params(
        target,
        bandit_subsystem,
        PythonNativeCode.global_instance(),
        PythonSetup.global_instance(),
        SubprocessEnvironment.global_instance()
      )
    )

  def test_single_passing_source(self) -> None:
    result = self.run_bandit([self.good_source])
    assert result.exit_code == 0
    assert "No issues identified." in result.stdout.strip()

  def test_single_failing_source(self) -> None:
    result = self.run_bandit([self.bad_source])
    assert result.exit_code == 1
    assert "Issue: [B303:blacklist] Use of insecure MD2, MD4, MD5" in result.stdout

  def test_mixed_sources(self) -> None:
    result = self.run_bandit([self.good_source, self.bad_source])
    assert result.exit_code == 1
    assert "test/good.py" not in result.stdout
    assert "Issue: [B303:blacklist] Use of insecure MD2, MD4, MD5" in result.stdout

  def test_respects_config_file(self) -> None:
    result = self.run_bandit([self.bad_source], config="skips: ['B303']\n")
    assert result.exit_code == 0
    assert "No issues identified." in result.stdout.strip()

  def test_respects_passthrough_args(self) -> None:
    result = self.run_bandit([self.bad_source], passthrough_args="--skip B303")
    assert result.exit_code == 0
    assert "No issues identified." in result.stdout.strip()

  def test_skip(self) -> None:
    result = self.run_bandit([self.bad_source], skip=True)
    assert result == LintResult.noop()

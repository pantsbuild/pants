# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, Tuple

from pants.backend.python.lint.isort.rules import IsortSetup, fmt, lint, setup_isort
from pants.backend.python.lint.isort.subsystem import Isort
from pants.backend.python.rules.download_pex_bin import download_pex_bin
from pants.backend.python.rules.pex import CreatePex, create_pex
from pants.backend.python.subsystems.python_native_code import (
  PythonNativeCode,
  create_pex_native_build_environment,
)
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import (
  SubprocessEnvironment,
  create_subprocess_encoding_environment,
)
from pants.backend.python.targets.formattable_python_target import FormattablePythonTarget
from pants.build_graph.address import Address
from pants.engine.fs import Digest, FileContent, InputFilesContent, Snapshot
from pants.engine.legacy.structs import TargetAdaptor
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.rules.core.fmt import FmtResult
from pants.rules.core.lint import LintResult
from pants.source.wrapped_globs import EagerFilesetWithSpec
from pants.testutil.subsystem.util import global_subsystem_instance, init_subsystems
from pants.testutil.test_base import TestBase


class IsortIntegrationTest(TestBase):

  good_source = FileContent(path="test/good.py", content=b'from colors import blue, green\n')
  bad_source = FileContent(path="test/bad.py", content=b'from colors import green, blue\n')
  fixed_bad_source = FileContent(path="test/bad.py", content=b'from colors import blue, green\n')

  @classmethod
  def rules(cls):
    return (
      *super().rules(),
      fmt,
      lint,
      setup_isort,
      create_pex,
      create_subprocess_encoding_environment,
      create_pex_native_build_environment,
      download_pex_bin,
      RootRule(CreatePex),
      RootRule(FormattablePythonTarget),
      RootRule(Isort),
      RootRule(IsortSetup),
      RootRule(PythonSetup),
      RootRule(PythonNativeCode),
      RootRule(SubprocessEnvironment),
    )

  def setUp(self):
    super().setUp()
    init_subsystems([Isort, PythonSetup, PythonNativeCode, SubprocessEnvironment])

  def run_isort(
    self, source_files: List[FileContent], *, config: Optional[str] = None
  ) -> Tuple[LintResult, FmtResult]:
    if config is not None:
      self.create_file(relpath=".isort.cfg", contents=config)
    input_snapshot = self.request_single_product(Snapshot, InputFilesContent(source_files))
    target = FormattablePythonTarget(
      TargetAdaptor(
        sources=EagerFilesetWithSpec('test', {'globs': []}, snapshot=input_snapshot),
        address=Address.parse("test:target"),
      )
    )
    isort_subsystem = global_subsystem_instance(
      Isort, options={Isort.options_scope: {"config": ".isort.cfg" if config else None}}
    )
    isort_setup = self.request_single_product(
      IsortSetup,
      Params(
        target,
        isort_subsystem,
        PythonNativeCode.global_instance(),
        PythonSetup.global_instance(),
        SubprocessEnvironment.global_instance(),
      )
    )
    fmt_and_lint_params = Params(
      target, isort_setup, PythonSetup.global_instance(), SubprocessEnvironment.global_instance()
    )
    lint_result = self.request_single_product(LintResult, fmt_and_lint_params)
    fmt_result = self.request_single_product(FmtResult, fmt_and_lint_params)
    return lint_result, fmt_result

  def get_digest(self, source_files: List[FileContent]) -> Digest:
    return self.request_single_product(Digest, InputFilesContent(source_files))

  def test_single_passing_source(self) -> None:
    lint_result, fmt_result = self.run_isort([self.good_source])
    assert lint_result.exit_code == 0
    assert lint_result.stdout == ""
    assert fmt_result.stdout == ""
    assert fmt_result.digest == self.get_digest([self.good_source])

  def test_single_failing_source(self) -> None:
    lint_result, fmt_result = self.run_isort([self.bad_source])
    assert lint_result.exit_code == 1
    assert "test/bad.py Imports are incorrectly sorted" in lint_result.stdout
    assert "Fixing" in fmt_result.stdout
    assert "test/bad.py" in fmt_result.stdout
    assert fmt_result.digest == self.get_digest([self.fixed_bad_source])

  def test_multiple_mixed_sources(self) -> None:
    lint_result, fmt_result = self.run_isort([self.good_source, self.bad_source])
    assert lint_result.exit_code == 1
    assert "test/bad.py Imports are incorrectly sorted" in lint_result.stdout
    assert "test/good.py" not in lint_result.stdout
    assert "Fixing" in fmt_result.stdout and "test/bad.py" in fmt_result.stdout
    assert "test/good.py" not in fmt_result.stdout
    assert fmt_result.digest == self.get_digest([self.good_source, self.fixed_bad_source])

  def test_respects_config_file(self) -> None:
    # Normally isort wants "as imports" on a new line, so `source` should not be formatted with a
    # default isort run. We configure our settings to instead combine the two lines. If the config
    # is picked up, then `source` should be reformatted by isort.
    source = FileContent(
      path="test/config.py",
      content=b"from colors import blue\nfrom colors import green as verde"
    )
    fixed_source = FileContent(
      path="test/config.py",
      content=b"from colors import blue, green as verde\n"
    )
    lint_result, fmt_result = self.run_isort(
      [source], config="[settings]\ncombine_as_imports=True\n"
    )
    assert lint_result.exit_code == 1
    assert "test/config.py Imports are incorrectly sorted" in lint_result.stdout
    assert "Fixing" in fmt_result.stdout
    assert "test/config.py" in fmt_result.stdout
    assert fmt_result.digest == self.get_digest([fixed_source])

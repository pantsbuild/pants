# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, Tuple

from pants.backend.python.lint.black.rules import BlackSetup, fmt, lint, setup_black
from pants.backend.python.lint.black.subsystem import Black
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


class BlackIntegrationTest(TestBase):

  good_source = FileContent(path="test/good.py", content=b'name = "Anakin"\n')
  bad_source = FileContent(path="test/bad.py", content=b'name=    "Anakin"\n')
  fixed_bad_source = FileContent(path="test/bad.py", content=b'name = "Anakin"\n')

  @classmethod
  def rules(cls):
    return (
      *super().rules(),
      fmt,
      lint,
      setup_black,
      create_pex,
      create_subprocess_encoding_environment,
      create_pex_native_build_environment,
      download_pex_bin,
      RootRule(CreatePex),
      RootRule(FormattablePythonTarget),
      RootRule(Black),
      RootRule(BlackSetup),
      RootRule(PythonSetup),
      RootRule(PythonNativeCode),
      RootRule(SubprocessEnvironment),
    )

  def setUp(self):
    super().setUp()
    init_subsystems([Black, PythonSetup, PythonNativeCode, SubprocessEnvironment])

  def run_black(
    self, source_files: List[FileContent], *, config: Optional[str] = None
  ) -> Tuple[LintResult, FmtResult]:
    if config is not None:
      self.create_file(relpath="pyproject.toml", contents=config)
    input_snapshot = self.request_single_product(Snapshot, InputFilesContent(source_files))
    target = FormattablePythonTarget(
      TargetAdaptor(
        sources=EagerFilesetWithSpec('test', {'globs': []}, snapshot=input_snapshot),
        address=Address.parse("test:target"),
      )
    )
    black_subsystem = global_subsystem_instance(
      Black, options={Black.options_scope: {"config": "pyproject.toml" if config else None}}
    )
    black_setup = self.request_single_product(
      BlackSetup,
      Params(
        target,
        black_subsystem,
        PythonNativeCode.global_instance(),
        PythonSetup.global_instance(),
        SubprocessEnvironment.global_instance(),
      )
    )
    fmt_and_lint_params = Params(
      target, black_setup, PythonSetup.global_instance(), SubprocessEnvironment.global_instance()
    )
    lint_result = self.request_single_product(LintResult, fmt_and_lint_params)
    fmt_result = self.request_single_product(FmtResult, fmt_and_lint_params)
    return lint_result, fmt_result

  def get_digest(self, source_files: List[FileContent]) -> Digest:
    return self.request_single_product(Digest, InputFilesContent(source_files))

  def test_single_passing_source(self) -> None:
    lint_result, fmt_result = self.run_black([self.good_source])
    self.assertEqual(lint_result.exit_code, 0)
    self.assertIn("1 file would be left unchanged", lint_result.stderr)
    self.assertIn("1 file left unchanged", fmt_result.stderr)
    self.assertEqual(fmt_result.digest, self.get_digest([self.good_source]))

  def test_single_failing_source(self) -> None:
    lint_result, fmt_result = self.run_black([self.bad_source])
    self.assertEqual(lint_result.exit_code, 1)
    self.assertIn("1 file would be reformatted", lint_result.stderr)
    self.assertIn("1 file reformatted", fmt_result.stderr)
    self.assertEqual(fmt_result.digest, self.get_digest([self.fixed_bad_source]))

  def test_multiple_mixed_sources(self) -> None:
    lint_result, fmt_result = self.run_black([self.good_source, self.bad_source])
    self.assertEqual(lint_result.exit_code, 1)
    self.assertIn("1 file would be reformatted, 1 file would be left unchanged", lint_result.stderr)
    self.assertIn("1 file reformatted, 1 file left unchanged", fmt_result.stderr)
    self.assertEqual(fmt_result.digest, self.get_digest([self.good_source, self.fixed_bad_source]))

  def test_respects_config_file(self) -> None:
    # Note the single quotes, which Black does not like by default.
    source = FileContent(path="test/good.py", content=b"name = 'Anakin'\n")
    lint_result, fmt_result = self.run_black(
      [source], config="[tool.black]\nskip-string-normalization = 'true'\n"
    )
    self.assertEqual(lint_result.exit_code, 0)
    self.assertIn("1 file would be left unchanged", lint_result.stderr)
    self.assertIn("1 file left unchanged", fmt_result.stderr)
    self.assertEqual(fmt_result.digest, self.get_digest([source]))

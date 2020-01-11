# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, Tuple

from pants.backend.python.lint.black.rules import BlackTarget
from pants.backend.python.lint.black.rules import rules as black_rules
from pants.backend.python.rules import download_pex_bin, pex
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.build_graph.address import Address
from pants.engine.fs import Digest, FileContent, InputFilesContent, Snapshot
from pants.engine.legacy.structs import TargetAdaptor
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.rules.core.fmt import FmtResult
from pants.rules.core.lint import LintResult
from pants.source.wrapped_globs import EagerFilesetWithSpec
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class BlackIntegrationTest(TestBase):

  good_source = FileContent(path="test/good.py", content=b'animal = "Koala"\n')
  bad_source = FileContent(path="test/bad.py", content=b'name=    "Anakin"\n')
  fixed_bad_source = FileContent(path="test/bad.py", content=b'name = "Anakin"\n')
  # Note the single quotes, which Black does not like by default. To get Black to pass, it will
  # need to successfully read our config/CLI args.
  needs_config_source = FileContent(path="test/config.py", content=b"animal = 'Koala'\n")

  @classmethod
  def rules(cls):
    return (
      *super().rules(),
      *black_rules(),
      *download_pex_bin.rules(),
      *pex.rules(),
      *python_native_code.rules(),
      *subprocess_environment.rules(),
      RootRule(BlackTarget),
    )

  def run_black(
    self,
    source_files: List[FileContent],
    *,
    config: Optional[str] = None,
    passthrough_args: Optional[str] = None,
    skip: bool = False,
  ) -> Tuple[LintResult, FmtResult]:
    args = ["--backend-packages2=pants.backend.python.lint.black"]
    if config is not None:
      self.create_file(relpath="pyproject.toml", contents=config)
      args.append("--black-config=pyproject.toml")
    if passthrough_args:
      args.append(f"--black-args='{passthrough_args}'")
    if skip:
      args.append(f"--black-skip")
    input_snapshot = self.request_single_product(Snapshot, InputFilesContent(source_files))
    target_adaptor = TargetAdaptor(
      sources=EagerFilesetWithSpec('test', {'globs': []}, snapshot=input_snapshot),
      address=Address.parse("test:target"),
    )
    lint_target = BlackTarget(target_adaptor)
    fmt_target = BlackTarget(target_adaptor, prior_formatter_result_digest=input_snapshot.directory_digest)
    options_bootstrapper = create_options_bootstrapper(args=args)
    lint_result = self.request_single_product(LintResult, Params(lint_target, options_bootstrapper))
    fmt_result = self.request_single_product(FmtResult, Params(fmt_target, options_bootstrapper))
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
    lint_result, fmt_result = self.run_black(
      [self.needs_config_source], config="[tool.black]\nskip-string-normalization = 'true'\n",
    )
    self.assertEqual(lint_result.exit_code, 0)
    self.assertIn("1 file would be left unchanged", lint_result.stderr)
    self.assertIn("1 file left unchanged", fmt_result.stderr)
    self.assertEqual(fmt_result.digest, self.get_digest([self.needs_config_source]))

  def test_respects_passthrough_args(self) -> None:
    lint_result, fmt_result = self.run_black(
      [self.needs_config_source], passthrough_args="--skip-string-normalization",
    )
    assert lint_result.exit_code == 0
    assert "1 file would be left unchanged" in lint_result.stderr
    assert "1 file left unchanged" in fmt_result.stderr
    assert fmt_result.digest == self.get_digest([self.needs_config_source])

  def test_skip(self) -> None:
    lint_result, fmt_result = self.run_black([self.bad_source], skip=True)
    assert lint_result == LintResult.noop()
    assert fmt_result == FmtResult.noop()

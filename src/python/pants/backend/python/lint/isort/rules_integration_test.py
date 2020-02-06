# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, Tuple

from pants.backend.python.lint.isort.rules import IsortTarget
from pants.backend.python.lint.isort.rules import rules as isort_rules
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


class IsortIntegrationTest(TestBase):

  good_source = FileContent(path="test/good.py", content=b'from animals import cat, dog\n')
  bad_source = FileContent(path="test/bad.py", content=b'from colors import green, blue\n')
  fixed_bad_source = FileContent(path="test/bad.py", content=b'from colors import blue, green\n')
  # Note the as import. Isort by default keeps as imports on a new line, so this wouldn't be
  # reformatted by default. If we set the config/CLI args correctly, isort will combine the two
  # imports into one line.
  needs_config_source = FileContent(
    path="test/config.py",
    content=b"from colors import blue\nfrom colors import green as verde\n"
  )
  fixed_needs_config_source = FileContent(
    path="test/config.py",
    content=b"from colors import blue, green as verde\n"
  )

  @classmethod
  def rules(cls):
    return (*super().rules(), *isort_rules(), RootRule(IsortTarget))

  def run_isort(
    self,
    source_files: List[FileContent],
    *,
    config: Optional[str] = None,
    passthrough_args: Optional[str] = None,
    skip: bool = False,
  ) -> Tuple[LintResult, FmtResult]:
    args = ["--backend-packages2=pants.backend.python.lint.isort"]
    if config is not None:
      self.create_file(relpath=".isort.cfg", contents=config)
      args.append("--isort-config=.isort.cfg")
    if passthrough_args:
      args.append(f"--isort-args='{passthrough_args}'")
    if skip:
      args.append(f"--isort-skip")
    input_snapshot = self.request_single_product(Snapshot, InputFilesContent(source_files))
    target_adaptor = TargetAdaptor(
      sources=EagerFilesetWithSpec('test', {'globs': []}, snapshot=input_snapshot),
      address=Address.parse("test:target"),
    )
    lint_target = IsortTarget(target_adaptor)
    fmt_target = IsortTarget(
      target_adaptor, prior_formatter_result_digest=input_snapshot.directory_digest,
    )
    options_bootstrapper = create_options_bootstrapper(args=args)
    lint_result = self.request_single_product(LintResult, Params(lint_target, options_bootstrapper))
    fmt_result = self.request_single_product(FmtResult, Params(fmt_target, options_bootstrapper))
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
    lint_result, fmt_result = self.run_isort(
      [self.needs_config_source], config="[settings]\ncombine_as_imports=True\n",
    )
    assert lint_result.exit_code == 1
    assert "test/config.py Imports are incorrectly sorted" in lint_result.stdout
    assert "Fixing" in fmt_result.stdout
    assert "test/config.py" in fmt_result.stdout
    assert fmt_result.digest == self.get_digest([self.fixed_needs_config_source])

  def test_respects_passthrough_args(self) -> None:
    lint_result, fmt_result = self.run_isort(
      [self.needs_config_source], passthrough_args="--combine-as",
    )
    assert lint_result.exit_code == 1
    assert "test/config.py Imports are incorrectly sorted" in lint_result.stdout
    assert "Fixing" in fmt_result.stdout
    assert "test/config.py" in fmt_result.stdout
    assert fmt_result.digest == self.get_digest([self.fixed_needs_config_source])

  def test_skip(self) -> None:
    lint_result, fmt_result = self.run_isort([self.bad_source], skip=True)
    assert lint_result == LintResult.noop()
    assert fmt_result == FmtResult.noop()

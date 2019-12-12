# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from typing import List, Tuple, Type

from pants.engine.fs import (
  EMPTY_DIRECTORY_DIGEST,
  Digest,
  DirectoriesToMerge,
  FileContent,
  InputFilesContent,
  Snapshot,
  Workspace,
)
from pants.engine.legacy.graph import HydratedTarget, HydratedTargets
from pants.engine.legacy.structs import JvmAppAdaptor, PythonTargetAdaptor, TargetAdaptor
from pants.engine.rules import UnionMembership
from pants.rules.core.fmt import Fmt, FmtResult, FormatTarget, fmt
from pants.source.wrapped_globs import EagerFilesetWithSpec
from pants.testutil.engine.util import MockConsole, MockGet, run_rule
from pants.testutil.test_base import TestBase


class FmtTest(TestBase):

  formatted_file = Path("formatted.txt")
  formatted_content = "I'm so pretty now!\n"

  @staticmethod
  def make_hydrated_target(
    *,
    name: str = "target",
    adaptor_type: Type[TargetAdaptor] = PythonTargetAdaptor,
    include_sources: bool = True,
  ) -> HydratedTarget:
    mocked_snapshot = Snapshot(
      # TODO: this is not robust to set as an empty digest. Add a test util that provides
      #  some premade snapshots and possibly a generalized make_hydrated_target function.
      directory_digest=EMPTY_DIRECTORY_DIGEST,
      files=("formatted.txt", "fake.txt") if include_sources else (),
      dirs=()
    )
    return HydratedTarget(
      address=f"src/{name}",
      adaptor=adaptor_type(
        sources=EagerFilesetWithSpec("src", {"globs": []}, snapshot=mocked_snapshot),
        name=name,
      ),
      dependencies=()
    )

  def run_fmt_rule(self, *, targets: List[HydratedTarget]) -> Tuple[Fmt, str]:
    result_digest = self.request_single_product(
      Digest,
      InputFilesContent([
        FileContent(path=str(self.formatted_file), content=self.formatted_content.encode())
      ])
    )
    console = MockConsole(use_colors=False)
    result: Fmt = run_rule(
      fmt,
      rule_args=[
        console,
        HydratedTargets(targets),
        Workspace(self.scheduler),
        UnionMembership(union_rules={FormatTarget: [PythonTargetAdaptor]})
      ],
      mock_gets=[
        MockGet(
          product_type=FmtResult,
          subject_type=PythonTargetAdaptor,
          mock=lambda adaptor: FmtResult(
            digest=result_digest, stdout=f"Formatted target `{adaptor.name}`", stderr=""
          )
        ),
        MockGet(product_type=Digest, subject_type=DirectoriesToMerge, mock=lambda _: result_digest),
      ],
    )
    return result, console.stdout.getvalue()

  def assert_workspace_modified(self, modified: bool = True) -> None:
    formatted_file = Path(self.build_root, self.formatted_file)
    if not modified:
      assert not formatted_file.is_file()
      return
    assert formatted_file.is_file()
    assert formatted_file.read_text() == self.formatted_content

  def test_non_union_member_noops(self) -> None:
    result, stdout = self.run_fmt_rule(
      targets=[self.make_hydrated_target(adaptor_type=JvmAppAdaptor)]
    )
    assert result.exit_code == 0
    assert stdout.strip() == ""
    self.assert_workspace_modified(modified=False)

  def test_empty_target_noops(self) -> None:
    result, stdout = self.run_fmt_rule(
      targets=[self.make_hydrated_target(include_sources=False)]
    )
    assert result.exit_code == 0
    assert stdout.strip() == ""
    self.assert_workspace_modified(modified=False)

  def test_single_target(self) -> None:
    result, stdout = self.run_fmt_rule(targets=[self.make_hydrated_target()])
    assert result.exit_code == 0
    assert stdout.strip() == "Formatted target `target`"
    self.assert_workspace_modified()

  def test_multiple_targets(self) -> None:
    # NB: we do not test the case where FmtResults have conflicting changes, as that logic
    # is handled by DirectoriesToMerge.
    result, stdout = self.run_fmt_rule(
      targets=[self.make_hydrated_target(name="t1"), self.make_hydrated_target(name="t2")]
    )
    assert result.exit_code == 0
    assert stdout.splitlines() == ["Formatted target `t1`", "Formatted target `t2`"]
    self.assert_workspace_modified()

# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Callable, List, Tuple, Type

from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, Digest, FilesContent
from pants.engine.legacy.graph import HydratedTarget, HydratedTargets
from pants.engine.legacy.structs import JvmAppAdaptor, PythonTargetAdaptor, TargetAdaptor
from pants.engine.rules import UnionMembership
from pants.rules.core.fmt import Fmt, FmtResult, TargetWithSources, fmt
from pants.testutil.engine.util import MockConsole, MockGet, run_rule


def make_target(
  *, name: str = "target", adaptor_type: Type[TargetAdaptor] = PythonTargetAdaptor
) -> HydratedTarget:
  return HydratedTarget(
    address=f"src/{name}",
    adaptor=adaptor_type(sources=(), name=name),
    dependencies=()
  )


def run_fmt_rule(
  *,
  targets: List[HydratedTarget],
  mock_formatter: Callable[[PythonTargetAdaptor], FmtResult],
) -> Tuple[Fmt, MockConsole]:
  console = MockConsole(use_colors=False)
  result: Fmt = run_rule(
    fmt,
    rule_args=[
      console,
      HydratedTargets(targets),
      UnionMembership(union_rules={TargetWithSources: [PythonTargetAdaptor]})
    ],
    mock_gets=[
      MockGet(product_type=FmtResult, subject_type=PythonTargetAdaptor, mock=mock_formatter),
      MockGet(product_type=FilesContent, subject_type=Digest, mock=lambda _: FilesContent([]))
    ],
  )
  return result, console


def test_non_union_member_noops() -> None:
  result, console = run_fmt_rule(
    targets=[make_target(adaptor_type=JvmAppAdaptor)],
    mock_formatter=lambda adaptor: FmtResult(
      digest=EMPTY_DIRECTORY_DIGEST, stdout=f"Formatted target `{adaptor.name}`", stderr=""
    ),
  )
  assert result.exit_code == 0
  assert console.stdout.getvalue().strip() == ""

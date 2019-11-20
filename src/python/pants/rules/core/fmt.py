# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import Path

from pants.base.build_environment import get_buildroot
from pants.engine.console import Console
from pants.engine.fs import Digest, FilesContent
from pants.engine.goal import Goal
from pants.engine.legacy.graph import TransitiveHydratedTargets
from pants.engine.rules import UnionMembership, console_rule, union
from pants.engine.selectors import Get


@dataclass(frozen=True)
class FmtResult:
  digest: Digest
  stdout: str
  stderr: str


@union
class TargetWithSources:
  """A union for registration of a formattable target type."""


class Fmt(Goal):
  """Autoformat source code."""

  # TODO: make this "fmt"
  # Blocked on https://github.com/pantsbuild/pants/issues/8351
  name = 'fmt-v2'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--transitive', type=bool, default=True,
             help="If false, act only on the targets directly specified on the command line. "
                  "If true, act on the transitive dependency closure of those targets.")


@console_rule
def fmt(
  console: Console,
  fmt_options: Fmt.Options,
  transitive_targets: TransitiveHydratedTargets,
  union_membership: UnionMembership
) -> Fmt:

  transitive = fmt_options.values.transitive

  targets = transitive_targets.closure if transitive else transitive_targets.roots

  results = yield [
    Get(FmtResult, TargetWithSources, target.adaptor)
    for target in targets
    # TODO: make TargetAdaptor return a 'sources' field with an empty snapshot instead of
    # raising to remove the hasattr() checks here!
    if union_membership.is_member(TargetWithSources, target.adaptor) and hasattr(target.adaptor, "sources")
  ]

  for result in results:
    files_content = yield Get(FilesContent, Digest, result.digest)
    # TODO: This is hacky and inefficient, and should be replaced by using the Workspace type
    # once that is available on master.
    # Blocked on: https://github.com/pantsbuild/pants/pull/8329
    for file_content in files_content:
      with Path(get_buildroot(), file_content.path).open('wb') as f:
        f.write(file_content.content)

    if result.stdout:
      console.print_stdout(result.stdout)
    if result.stderr:
      console.print_stderr(result.stderr)

  # Since we ran an ExecuteRequest, any failure would already have interrupted our flow
  exit_code = 0
  yield Fmt(exit_code)


def rules():
  return [
    fmt,
  ]

# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.base.build_environment import get_buildroot
from pants.engine.console import Console
from pants.engine.fs import Digest, FilesContent
from pants.engine.goal import Goal
from pants.engine.legacy.graph import HydratedTargets
from pants.engine.legacy.structs import (
  PythonAppAdaptor,
  PythonBinaryAdaptor,
  PythonTargetAdaptor,
  PythonTestsAdaptor,
)
from pants.engine.rules import console_rule, union
from pants.engine.selectors import Get
from pants.util.objects import datatype


class FmtResult(datatype([
  ('digest', Digest),
  ('stdout', str),
  ('stderr', str),
])):

  pass


@union
class FmtTarget:
  """A union for registration of a testable target type."""


class Fmt(Goal):
  """Autoformat source code."""

  name = 'fmt_v2'


@console_rule
def fmt(console: Console, targets: HydratedTargets) -> Fmt:
  results = yield [
          Get(FmtResult, FmtTarget, target.adaptor)
          for target in targets
          if isinstance(target.adaptor, (PythonAppAdaptor, PythonTargetAdaptor, PythonTestsAdaptor, PythonBinaryAdaptor)) and hasattr(target.adaptor, "sources")
          ]

  for result in results:
    files_content = yield Get(FilesContent, Digest, result.digest)
    for file_content in files_content:
      with open(os.path.join(get_buildroot(), file_content.path), "wb") as f:
        f.write(file_content.content)

    console.print_stdout(result.stdout)
    console.print_stderr(result.stderr)

  # workspace.materialize_directories(tuple(digests))
  # Since we ran an ExecuteRequest, any failure would already have interrupted our flow
  exit_code = 0
  yield Fmt(exit_code)


def rules():
  return [
      fmt,
    ]

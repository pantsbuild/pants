# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.console import Console
from pants.engine.goal import Goal
from pants.engine.rules import console_rule


class ExportClasspath(Goal):
  """???"""
  name = 'fast-export-classpath'


@console_rule
def fast_export_classpath(console: Console) -> ExportClasspath:
  console.print_stdout('wow!')
  return ExportClasspath(exit_code=0)


def rules():
  return [
    fast_export_classpath,
  ]

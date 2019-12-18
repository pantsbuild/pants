# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.engine.console import Console
from pants.engine.fs import (
  Digest,
  DirectoryToMaterialize,
  FileContent,
  InputFilesContent,
  PathGlobs,
  Snapshot,
  Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import console_rule
from pants.engine.selectors import Get
from pants.version import VERSION as pants_version


class GeneratePantsIniOptions(GoalSubsystem):
  """Generate pants.ini with sensible defaults."""
  name = 'generate-pants-ini'


class GeneratePantsIni(Goal):
  subsystem_cls = GeneratePantsIniOptions


@console_rule
async def generate_pants_ini(console: Console, workspace: Workspace) -> GeneratePantsIni:
  pants_ini_content = dedent(f"""\
    [GLOBAL]
    pants_version: {pants_version}
    """)

  preexisting_snapshot = await Get[Snapshot](PathGlobs(include=('pants.ini',)))
  if preexisting_snapshot.files:
    console.print_stderr(
      "./pants.ini already exists. This goal is only meant to be run the first time you run Pants "
      "in a project.\n\nTo update config values, please directly modify the file."
    )
    return GeneratePantsIni(exit_code=1)

  console.print_stdout(dedent(f"""\
    Adding sensible defaults to ./pants.ini:
      * Pinning `pants_version` to `{pants_version}`.
    """))

  digest = await Get[Digest](InputFilesContent([
    FileContent(path='pants.ini', content=pants_ini_content.encode())
  ]))
  workspace.materialize_directory(DirectoryToMaterialize(digest))

  console.print_stdout(
    "You may modify these values directly in the file at any time. The ./pants script will detect "
    "any changes the next time you run it.\n\nYou are now ready to use Pants!"
  )
  return GeneratePantsIni(exit_code=0)


def rules():
  return [generate_pants_ini]

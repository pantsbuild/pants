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
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get
from pants.version import VERSION


class GeneratePantsIniOptions(GoalSubsystem):
  """Generate pants.ini with sensible defaults."""
  name = 'generate-pants-ini'

  @classmethod
  def register_options(cls, register) -> None:
    super().register_options(register)
    register('--v2-only', type=bool, fingerprint=True, default=False,
             help='Support only v2 rules. If unspecified, this repo will also run v1 tasks.')


class GeneratePantsIni(Goal):
  subsystem_cls = GeneratePantsIniOptions


@goal_rule
async def generate_pants_ini(console: Console, workspace: Workspace,
                             options: GeneratePantsIniOptions) -> GeneratePantsIni:
  pants_ini_content = dedent(f"""\
    [GLOBAL]
    pants_version: {VERSION}
    v1: {'False' if options.values.v2_only else 'True'}
    v2: {'True' if options.values.v2_only else 'False'}
    v2_ui: {'True' if options.values.v2_only else 'False'}
    
    backend_packages: [
        # 'pants.backend.graph_info',
        # 'pants.backend.project_info',
        # 'pants.backend.python',
        # 'pants.backend.jvm',
        # 'pants.backend.native',
      ]
    
    plugins: []
    
    backend_packages2: [
        # 'pants.backend.project_info',
        # 'pants.backend.python',
        # 'pants.backend.python.lint.flake8',
        # 'pants.backend.python.lint.isort',
      ]
    
    plugins2: []
    """)

  preexisting_snapshot = await Get[Snapshot](PathGlobs(include=('pants.ini',)))
  if preexisting_snapshot.files:
    console.print_stderr(
      "./pants.ini already exists. This goal is only meant to be run to set up Pants "
      "in a repo for the first time.\n\nTo update config values, please directly modify the file."
    )
    return GeneratePantsIni(exit_code=1)

  enabled = {'v2' if options.values.v2_only else 'v1'}
  disabled = {'v1' if options.values.v2_only else 'v2'}

  console.print_stdout(dedent(f"""\
      Setting sensible defaults in ./pants.ini:
      * Pinning `pants_version` to `{VERSION}`.
      * Enabling the {enabled} engine and disabling the {disabled} engine.
      * Setting empty v1 and v2 `plugins` and `backend_packages` so you can opt in to the functionality you need.
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

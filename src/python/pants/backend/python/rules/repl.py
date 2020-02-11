# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from pathlib import PurePath

from pants.backend.python.rules.pex import Pex
from pants.backend.python.rules.pex_from_target_closure import CreatePexFromTargetClosure
from pants.base.build_root import BuildRoot
from pants.engine.addressable import Addresses
from pants.engine.console import Console
from pants.engine.fs import DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.legacy.graph import TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonTargetAdaptor
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get
from pants.option.global_options import GlobalOptions
from pants.util.contextutil import temporary_dir


logger = logging.getLogger(__name__)


class PythonReplOptions(GoalSubsystem):
  """Opens a REPL."""
  name = 'repl2-python'


class PythonRepl(Goal):
  subsystem_cls = PythonReplOptions


@goal_rule
async def run_python_repl(
    console: Console,
    workspace: Workspace,
    runner: InteractiveRunner,
    targets: TransitiveHydratedTargets,
    build_root: BuildRoot,
    global_options: GlobalOptions) -> PythonRepl:

  # NOTE -  when Eric's changes pertaining to BuildFileAddresses are merged  in https://github.com/pantsbuild/pants/pull/9100, the
  # .to_address() call will no longer be necessary.
  python_addresses = Addresses(
    ht.address.to_address() for ht in targets.closure if isinstance(ht.adaptor, PythonTargetAdaptor)
  )

  create_pex = CreatePexFromTargetClosure(
    addresses=python_addresses,
    output_filename="python-repl.pex",
  )

  repl_pex = await Get[Pex](CreatePexFromTargetClosure, create_pex)

  with temporary_dir(root_dir=global_options.pants_workdir, cleanup=False) as tmpdir:
    path_relative_to_build_root = PurePath(tmpdir).relative_to(build_root.path).as_posix()
    workspace.materialize_directory(
      DirectoryToMaterialize(repl_pex.directory_digest, path_prefix=path_relative_to_build_root)
    )

    full_path = PurePath(tmpdir, repl_pex.output_filename).as_posix()
    run_request = InteractiveProcessRequest(
      argv=(full_path,),
      run_in_workspace=True,
    )
  result = runner.run_local_interactive_process(run_request)
  exit_code = result.process_exit_code

  if exit_code == 0:
    console.write_stdout("REPL exited successfully.")
  else:
    console.write_stdout(f"REPL exited with error: {exit_code}.")
  return PythonRepl(exit_code)


def rules():
  return [
    run_python_repl,
  ]

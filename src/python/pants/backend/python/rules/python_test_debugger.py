# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

from pants.backend.python.rules.inject_init import InjectedInitDigest
from pants.backend.python.rules.pex import (
  CreatePex,
  Pex,
  PexInterpreterConstraints,
  PexRequirements,
)
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.base.build_root import BuildRoot
from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryToMaterialize, Workspace
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.legacy.graph import HydratedTarget, TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonTestsAdaptor
from pants.engine.rules import rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.core_test_model import TestDebugResult
from pants.rules.core.strip_source_root import SourceRootStrippedSources
from pants.util.contextutil import temporary_dir


@rule(name="Run pytest in an interactive process")
async def debug_python_test(
  test_target: PythonTestsAdaptor,
  pytest: PyTest,
  python_setup: PythonSetup,
  build_root: BuildRoot,
  runner: InteractiveRunner,
  workspace: Workspace,
) -> TestDebugResult:

  transitive_hydrated_targets = await Get[TransitiveHydratedTargets](
    BuildFileAddresses((test_target.address,))
  )
  all_targets = transitive_hydrated_targets.closure
  all_target_adaptors = [t.adaptor for t in all_targets]

  interpreter_constraints = PexInterpreterConstraints.create_from_adaptors(
    adaptors=tuple(all_target_adaptors),
    python_setup=python_setup
  )

  requirements = PexRequirements.create_from_adaptors(
    adaptors=all_target_adaptors,
    additional_requirements=pytest.get_requirement_strings()
  )

  source_root_stripped_test_target_sources = await Get[SourceRootStrippedSources](
    Address, test_target.address.to_address()
  )

  source_root_stripped_sources = await MultiGet(
    Get[SourceRootStrippedSources](HydratedTarget, hydrated_target)
    for hydrated_target in all_targets
  )

  stripped_sources_digests = tuple(
    stripped_sources.snapshot.directory_digest for stripped_sources in source_root_stripped_sources
  )
  sources_digest = await Get[Digest](DirectoriesToMerge(directories=stripped_sources_digests))

  output_pytest_requirements_pex = 'pytest-with-requirements.pex'

  resolved_requirements_pex = await Get[Pex](
    CreatePex(
      output_filename=f'./{output_pytest_requirements_pex}',
      requirements=requirements,
      interpreter_constraints=interpreter_constraints,
      entry_point="pytest:main",
    )
  )

  inits_digest = await Get[InjectedInitDigest](Digest, sources_digest)

  merged_input_files = await Get[Digest](
    DirectoriesToMerge(
      directories=(
        sources_digest,
        inits_digest.directory_digest,
        resolved_requirements_pex.directory_digest,
      )
    ),
  )

  with temporary_dir(root_dir=str(Path(build_root.path, ".pants.d")), cleanup=True) as tmpdir:
    path_relative_to_build_root = str(Path(tmpdir).relative_to(build_root.path))
    test_target_sources_file_names = sorted(
      f'{path_relative_to_build_root}/{snapshot_file}'
      for snapshot_file
      in source_root_stripped_test_target_sources.snapshot.files
    )
    pex_args = (*pytest.get_args(), *test_target_sources_file_names)

    workspace.materialize_directory(
      DirectoryToMaterialize(merged_input_files, path_prefix=path_relative_to_build_root)
    )

    request_args = (f'{path_relative_to_build_root}/{output_pytest_requirements_pex}', *pex_args)
    run_request = InteractiveProcessRequest(argv=request_args, run_in_workspace=True)

    result = runner.run_local_interactive_process(run_request)

    return TestDebugResult(result.process_exit_code)


def rules():
  return [
    debug_python_test,
  ]

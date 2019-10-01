# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.inject_init import InjectedInitDigest
from pants.backend.python.rules.interpreter_constraints import (
  BuildConstraintsForAdaptors,
  PexInterpreterContraints,
)
from pants.backend.python.rules.pex import CreatePex, RunnablePex
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_binary import PythonBinary
from pants.engine.fs import Digest, DirectoriesToMerge
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.legacy.graph import BuildFileAddresses, HydratedTarget, TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonBinaryAdaptor
from pants.engine.rules import UnionRule, rule
from pants.engine.selectors import Get
from pants.rules.core.run import RunResult, RunTarget
from pants.rules.core.strip_source_root import SourceRootStrippedSources


@rule
def run_python_binary(python_binary_target: PythonBinaryAdaptor,
  python_setup: PythonSetup) -> RunResult:

  transitive_hydrated_targets = yield Get(
    TransitiveHydratedTargets, BuildFileAddresses((python_binary_target.address,))
  )
  all_targets = transitive_hydrated_targets.closure
  all_target_adaptors = [t.adaptor for t in all_targets]


  interpreter_constraints = yield Get(PexInterpreterContraints,
      BuildConstraintsForAdaptors(adaptors=tuple(all_target_adaptors)))

  source_root_stripped_sources = yield [
    Get(SourceRootStrippedSources, HydratedTarget, target_adaptor)
    for target_adaptor in all_targets
  ]

  #TODO This way of calculating the entry point works but is a bit hackish.
  entry_point = None
  if hasattr(python_binary_target, 'entry_point'):
    entry_point = python_binary_target.entry_point
  else:
    sources_snapshot = python_binary_target.sources.snapshot
    if len(sources_snapshot.files) == 1:
      target = transitive_hydrated_targets.roots[0]
      output = yield Get(SourceRootStrippedSources, HydratedTarget, target)
      root_filename = output.snapshot.files[0]
      entry_point = PythonBinary.translate_source_path_to_py_module_specifier(root_filename)

  stripped_sources_digests = [stripped_sources.snapshot.directory_digest for stripped_sources in source_root_stripped_sources]
  sources_digest = yield Get(Digest, DirectoriesToMerge(directories=tuple(stripped_sources_digests)))
  inits_digest = yield Get(InjectedInitDigest, Digest, sources_digest)
  all_input_digests = [sources_digest, inits_digest.directory_digest]
  merged_input_files = yield Get(Digest, DirectoriesToMerge, DirectoriesToMerge(directories=tuple(all_input_digests)))

  #TODO This chunk of code should be made into an @rule and used both here and in
  # python_test_runner.py.
  # Produce a pex containing pytest and all transitive 3rdparty requirements.
  output_thirdparty_requirements_pex_filename = '3rdparty-requirements.pex'
  all_target_requirements = []
  for maybe_python_req_lib in all_target_adaptors:
    # This is a python_requirement()-like target.
    if hasattr(maybe_python_req_lib, 'requirement'):
      all_target_requirements.append(str(maybe_python_req_lib.requirement))
    # This is a python_requirement_library()-like target.
    if hasattr(maybe_python_req_lib, 'requirements'):
      for py_req in maybe_python_req_lib.requirements:
        all_target_requirements.append(str(py_req.requirement))

  all_requirements = all_target_requirements
  create_requirements_pex = CreatePex(
    output_filename=output_thirdparty_requirements_pex_filename,
    requirements=tuple(sorted(all_requirements)),
    interpreter_constraints=interpreter_constraints,
    entry_point=entry_point,
    input_files_digest=merged_input_files,
  )

  exec_request = yield Get(ExecuteProcessRequest, RunnablePex(pex=create_requirements_pex))
  result = yield Get(FallibleExecuteProcessResult, ExecuteProcessRequest, exec_request)

  yield RunResult(
    status=result.exit_code,
    stdout=result.stdout.decode(),
    stderr=result.stderr.decode(),
  )


def rules():
  return [
    run_python_binary,
    UnionRule(RunTarget, PythonBinaryAdaptor),
  ]

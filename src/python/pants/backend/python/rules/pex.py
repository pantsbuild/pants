# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from pants.backend.python.rules.download_pex_bin import DownloadedPexBin
from pants.backend.python.rules.hermetic_pex import HermeticPex
from pants.backend.python.rules.inject_init import InjectedInitDigest
from pants.backend.python.subsystems.python_native_code import PexBuildEnvironment
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.addressable import BuildFileAddresses
from pants.engine.fs import (
  EMPTY_DIRECTORY_DIGEST,
  Digest,
  DirectoriesToMerge,
  DirectoryWithPrefixToAdd,
)
from pants.engine.isolated_process import ExecuteProcessResult, MultiPlatformExecuteProcessRequest
from pants.engine.legacy.graph import HydratedTarget, TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonTargetAdaptor, TargetAdaptor
from pants.engine.platform import Platform, PlatformConstraint
from pants.engine.rules import optionable_rule, rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.strip_source_root import SourceRootStrippedSources


@dataclass(frozen=True)
class PexRequirements:
  requirements: Tuple[str, ...] = ()

  @classmethod
  def create_from_adaptors(
    cls, adaptors: Iterable[TargetAdaptor], additional_requirements: Iterable[str] = ()
  ) -> 'PexRequirements':
    all_target_requirements = set()
    for maybe_python_req_lib in adaptors:
      # This is a python_requirement()-like target.
      if hasattr(maybe_python_req_lib, 'requirement'):
        all_target_requirements.add(str(maybe_python_req_lib.requirement))
      # This is a python_requirement_library()-like target.
      if hasattr(maybe_python_req_lib, 'requirements'):
        for py_req in maybe_python_req_lib.requirements:
          all_target_requirements.add(str(py_req.requirement))
    all_target_requirements.update(additional_requirements)
    return PexRequirements(requirements=tuple(sorted(all_target_requirements)))


@dataclass(frozen=True)
class PexInterpreterConstraints:
  constraint_set: Tuple[str, ...] = ()

  def generate_pex_arg_list(self) -> List[str]:
    args = []
    for constraint in sorted(self.constraint_set):
      args.extend(["--interpreter-constraint", constraint])
    return args

  @classmethod
  def create_from_adaptors(cls, adaptors: Iterable[PythonTargetAdaptor], python_setup: PythonSetup) -> 'PexInterpreterConstraints':
    interpreter_constraints = {
      constraint
      for target_adaptor in adaptors
      for constraint in python_setup.compatibility_or_constraints(
        getattr(target_adaptor, 'compatibility', None)
      )
    }
    return PexInterpreterConstraints(constraint_set=tuple(sorted(interpreter_constraints)))


@dataclass(frozen=True)
class CreatePex:
  """Represents a generic request to create a PEX from its inputs."""
  output_filename: str
  requirements: PexRequirements = PexRequirements()
  interpreter_constraints: PexInterpreterConstraints = PexInterpreterConstraints()
  entry_point: Optional[str] = None
  input_files_digest: Optional[Digest] = None


@dataclass(frozen=True)
class CreatePexFromTargetClosure:
  """Represents a request to create a PEX from the closure of a set of targets."""
  build_file_addresses: BuildFileAddresses
  output_filename: str
  entry_point: Optional[str] = None


@dataclass(frozen=True)
class Pex(HermeticPex):
  """Wrapper for a digest containing a pex file created with some filename."""
  directory_digest: Digest
  output_filename: str


# TODO: This is non-hermetic because the requirements will be resolved on the fly by
# pex, where it should be hermetically provided in some way.
@rule(name="Create PEX")
async def create_pex(
    request: CreatePex,
    pex_bin: DownloadedPexBin,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
    pex_build_environment: PexBuildEnvironment,
    platform: Platform
) -> Pex:
  """Returns a PEX with the given requirements, optional entry point, and optional
  interpreter constraints."""

  argv = ["--output-file", request.output_filename]
  if request.entry_point is not None:
    argv.extend(["--entry-point", request.entry_point])
  argv.extend(request.interpreter_constraints.generate_pex_arg_list())
  argv.extend(request.requirements.requirements)

  source_dir_name = 'source_files'

  argv.append(f'--sources-directory={source_dir_name}')
  sources_digest = request.input_files_digest if request.input_files_digest else EMPTY_DIRECTORY_DIGEST
  sources_digest_as_subdir = await Get[Digest](DirectoryWithPrefixToAdd(sources_digest, source_dir_name))
  all_inputs = (pex_bin.directory_digest, sources_digest_as_subdir,)
  merged_digest = await Get[Digest](DirectoriesToMerge(directories=all_inputs))

  # NB: PEX outputs are platform dependent so in order to get a PEX that we can use locally, without
  # cross-building, we specify that out PEX command be run on the current local platform. When we
  # support cross-building through CLI flags we can configure requests that build a PEX for out
  # local platform that are able to execute on a different platform, but for now in order to
  # guarantee correct build we need to restrict this command to execute on the same platform type
  # that the output is intended for. The correct way to interpret the keys
  # (execution_platform_constraint, target_platform_constraint) of this dictionary is "The output of
  # this command is intended for `target_platform_constraint` iff it is run on `execution_platform
  # constraint`".
  execute_process_request = MultiPlatformExecuteProcessRequest(
    {
      (PlatformConstraint(platform.value), PlatformConstraint(platform.value)):
        pex_bin.create_execute_request(
          python_setup=python_setup,
          subprocess_encoding_environment=subprocess_encoding_environment,
          pex_build_environment=pex_build_environment,
          pex_args=argv,
          input_files=merged_digest,
          description=f"Create a requirements PEX: {', '.join(request.requirements.requirements)}",
          output_files=(request.output_filename,)
        )
    }
  )

  result = await Get[ExecuteProcessResult](
    MultiPlatformExecuteProcessRequest,
    execute_process_request
  )
  return Pex(directory_digest=result.output_directory_digest, output_filename=request.output_filename)


@rule(name="Create PEX from targets")
async def create_pex_from_target_closure(request: CreatePexFromTargetClosure,
                                         python_setup: PythonSetup) -> Pex:
  transitive_hydrated_targets = await Get[TransitiveHydratedTargets](BuildFileAddresses,
                                                                     request.build_file_addresses)
  all_targets = transitive_hydrated_targets.closure
  all_target_adaptors = [t.adaptor for t in all_targets]

  interpreter_constraints = PexInterpreterConstraints.create_from_adaptors(
    adaptors=tuple(all_targets),
    python_setup=python_setup
  )

  source_root_stripped_sources = await MultiGet(
    Get[SourceRootStrippedSources](HydratedTarget, target_adaptor)
    for target_adaptor in all_targets
  )

  stripped_sources_digests = [stripped_sources.snapshot.directory_digest
                              for stripped_sources in source_root_stripped_sources]
  sources_digest = await Get[Digest](DirectoriesToMerge(directories=tuple(stripped_sources_digests)))
  inits_digest = await Get[InjectedInitDigest](Digest, sources_digest)
  all_input_digests = [sources_digest, inits_digest.directory_digest]
  merged_input_files = await Get[Digest](DirectoriesToMerge,
                                         DirectoriesToMerge(directories=tuple(all_input_digests)))
  requirements = PexRequirements.create_from_adaptors(all_target_adaptors)

  create_pex_request = CreatePex(
    output_filename=request.output_filename,
    requirements=requirements,
    interpreter_constraints=interpreter_constraints,
    entry_point=request.entry_point,
    input_files_digest=merged_input_files,
  )

  pex = await Get[Pex](CreatePex, create_pex_request)
  return pex


def rules():
  return [
    create_pex,
    create_pex_from_target_closure,
    optionable_rule(PythonSetup),
  ]

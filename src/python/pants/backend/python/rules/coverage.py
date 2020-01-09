# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from textwrap import dedent

from pants.backend.python.rules.inject_init import InjectedInitDigest
from pants.backend.python.rules.pex import (
  CreatePex,
  Pex,
  PexInterpreterConstraints,
  PexRequirements,
)
from pants.backend.python.subsystems.coverage import CoverageToolBase
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.base.specs import Specs
from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses
from pants.engine.fs import (
  Digest,
  DirectoriesToMerge,
  DirectoryWithPrefixToAdd,
  FileContent,
  InputFilesContent,
)
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.legacy.graph import HydratedTarget, TransitiveHydratedTargets
from pants.engine.rules import console_rule, optionable_rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.strip_source_root import SourceRootStrippedSources
from pants.rules.core.test import AddressAndTestResult
from pants.source.source_root import SourceRootConfig


class CoverageOptions(LineOriented, GoalSubsystem):
  name = 'coverage2'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register(
      '--transitive',
      default=True,
      type=bool,
      help='Run dependencies against transitive dependencies of targets specified on the command line.',
    )


class Coverage(Goal):
  subsystem_cls = CoverageOptions


@dataclass
class MergedCoverageData:
  coverage_data: Digest


DEFAULT_COVERAGE_CONFIG = dedent(f"""
  [run]
  branch = True
  timid = False
  relative_files = True
  """)


def get_coveragerc_input(coveragerc_content: bytes):
  return InputFilesContent(
    [
      FileContent(
        path='.coveragerc',
        content=coveragerc_content,
        is_executable=False,
      ),
    ]
  )


def get_file_names(all_target_adaptors):
  def iter_files():
    for adaptor in all_target_adaptors:
      if hasattr(adaptor, 'sources'):
        for file in adaptor.sources.snapshot.files:
          if file.endswith('.py'):
            yield file

  return list(iter_files())


@console_rule(name="Merge coverage reports")
async def merge_coverage_reports(
  addresses: BuildFileAddresses,
  specs: Specs,
  pytest: PyTest,
  python_setup: PythonSetup,
  coverage: CoverageToolBase,
  source_root_config: SourceRootConfig,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,

) -> Coverage:
  """Takes all python test results and generates a single coverage report in dist/coverage."""
  output_pex_filename = "coverage.pex"
  requirements_pex = await Get[Pex](
    CreatePex(
      output_filename=output_pex_filename,
      requirements=PexRequirements(requirements=tuple(coverage.get_requirement_specs())),
      interpreter_constraints=PexInterpreterConstraints(
        constraint_set=tuple(coverage.default_interpreter_constraints)
      ),
      entry_point=coverage.get_entry_point(),
    )
  )

  transitive_targets = await Get[TransitiveHydratedTargets](Specs, specs)
  python_targets = [
    target for target in transitive_targets.closure
    if target.adaptor.type_alias == 'python_library' or target.adaptor.type_alias == 'python_tests'
  ]

  results = await MultiGet(Get[AddressAndTestResult](Address, addr.to_address()) for addr in addresses)
  test_results = [
    (x.address.to_address().path_safe_spec, x.test_result.coverage_digest) for x in results if x.test_result is not None]

  coveragerc_digest = await Get[Digest](InputFilesContent, get_coveragerc_input(DEFAULT_COVERAGE_CONFIG.encode()))

  coverage_directory_digests = await MultiGet(
    Get(
      Digest,
      DirectoryWithPrefixToAdd(
        directory_digest=coverage_file_digest,
        prefix=prefix
      )
    )
    for prefix, coverage_file_digest in test_results
  )
  source_root_stripped_sources = await MultiGet(
    Get[SourceRootStrippedSources](HydratedTarget, hydrated_target)
    for hydrated_target in python_targets
  )
  stripped_sources_digests = tuple(
    stripped_sources.snapshot.directory_digest for stripped_sources in source_root_stripped_sources
  )
  sources_digest = await Get[Digest](DirectoriesToMerge(directories=stripped_sources_digests))
  inits_digest = await Get[InjectedInitDigest](Digest, sources_digest)
  merged_input_files = await Get(
    Digest,
    DirectoriesToMerge(directories=(
      *coverage_directory_digests,
      coveragerc_digest,
      requirements_pex.directory_digest,
      sources_digest,
      inits_digest.directory_digest,
    )),
  )
  import pdb; pdb.set_trace()

  prefixes = [f'{prefix}/.coverage' for prefix, _ in test_results]
  coverage_args = ['combine', *prefixes]
  print(coverage_args)
  request = requirements_pex.create_execute_request(
    python_setup=python_setup,
    subprocess_encoding_environment=subprocess_encoding_environment,
    pex_path=f'./{output_pex_filename}',
    pex_args=coverage_args,
    input_files=merged_input_files,
    output_files=('.coverage',),
    description=f'Merge coverage reports.',
  )

  result = await Get[FallibleExecuteProcessResult](
    ExecuteProcessRequest,
    request
  )
  return MergedCoverageData(coverage_data=result.output_directory_digest)


def rules():
  return [
    optionable_rule(CoverageToolBase),
    merge_coverage_reports,
  ]

# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import configparser
import json
from dataclasses import dataclass
from io import StringIO
from typing import Dict, Tuple
import itertools

import pkg_resources

from pants.backend.python.rules.inject_init import InjectedInitDigest
from pants.backend.python.rules.pex import (
  CreatePex,
  Pex,
  PexInterpreterConstraints,
  PexRequirements,
)
from pants.backend.python.rules.prepare_chrooted_python_sources import ChrootedPythonSources

from pants.backend.python.rules.python_test_runner import (
  DEFAULT_COVERAGE_CONFIG,
  get_coveragerc_input,
)
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.base.specs import AddressSpecs
from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses
from pants.engine.fs import (
  Digest,
  DirectoriesToMerge,
  DirectoryWithPrefixToAdd,
  FileContent,
  FilesContent,
  InputFilesContent,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.legacy.graph import HydratedTarget, TransitiveHydratedTargets, HydratedTargets
from pants.engine.rules import goal_rule, rule, subsystem_rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.strip_source_root import SourceRootStrippedSources
from pants.rules.core.test import AddressAndTestResult, AddressAndTestResults, CoverageReport
from pants.source.source_root import SourceRootConfig


class CoverageToolBase(PythonToolBase):
  options_scope = 'merge-coverage'
  default_version = 'coverage==5.0.0'
  default_entry_point = 'coverage'
  default_interpreter_constraints = ["CPython>=3.6"]


@dataclass(frozen=True)
class CoverageSetup:
  requirements_pex: Pex
  filename: str


@rule
async def setup_coverage(
  coverage: CoverageToolBase,
) -> CoverageSetup:
  plugin_file_digest: Digest = await Get[Digest](InputFilesContent, get_coverage_plugin_input())
  output_pex_filename = "coverage.pex"
  requirements_pex = await Get[Pex](
    CreatePex(
      output_filename=output_pex_filename,
      requirements=PexRequirements(requirements=tuple(coverage.get_requirement_specs())),
      interpreter_constraints=PexInterpreterConstraints(
        constraint_set=tuple(coverage.default_interpreter_constraints)
      ),
      entry_point=coverage.get_entry_point(),
      input_files_digest=plugin_file_digest,
    )
  )
  return CoverageSetup(requirements_pex, output_pex_filename)


@rule
async def create_coverage_request(
  coverage_setup: CoverageSetup,
  python_setup: PythonSetup,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> ExecuteProcessRequest:
  pass


@dataclass(frozen=True)
class MergedCoverageData:
  coverage_data: Digest

@rule(name="Merge coverage reports")
async def merge_coverage_reports(
  test_results: AddressAndTestResults,
  addresses: BuildFileAddresses,
  address_specs: AddressSpecs,
  transitive_targets: TransitiveHydratedTargets,
  python_setup: PythonSetup,
  coverage: CoverageToolBase,
  coverage_setup: CoverageSetup,
  source_root_config: SourceRootConfig,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> MergedCoverageData:
  """Takes all python test results and merges their coverage data into a single sql file."""

  coveragerc_digest = await Get[Digest](InputFilesContent, get_coveragerc_input(DEFAULT_COVERAGE_CONFIG))

  coverage_directory_digests: Tuple[Digest, ...] = await MultiGet(
    Get(
      Digest,
      DirectoryWithPrefixToAdd(
        directory_digest=test_result._python_sqlite_coverage_file,
        prefix=address.to_address().path_safe_spec,
      )
    )
    for address, test_result in test_results if test_result._python_sqlite_coverage_file is not None
  )

  chrooted_sources = await Get[ChrootedPythonSources](HydratedTargets(transitive_targets.closure))

  merged_input_files: Digest = await Get(
    Digest,
    DirectoriesToMerge(directories=(
      *coverage_directory_digests,
      coveragerc_digest,
      coverage_setup.requirements_pex.directory_digest,
      chrooted_sources.digest
    )),
  )

  prefixes = [f'{prefix}/.coverage' for prefix, _ in test_results]
  coverage_args = ['combine', *prefixes]
  request = coverage_setup.requirements_pex.create_execute_request(
    python_setup=python_setup,
    subprocess_encoding_environment=subprocess_encoding_environment,
    pex_path=f'./{coverage_setup.filename}',
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


COVERAGE_PLUGIN_MODULE_NAME = '__coverage_coverage_plugin__'


def get_coverage_plugin_input():
  return InputFilesContent(
    FilesContent(
      (
        FileContent(
          path=f'{COVERAGE_PLUGIN_MODULE_NAME}.py',
          content=pkg_resources.resource_string(__name__, 'coverage/plugin.py'),
          is_executable=False,
        ),
      )
    )
  )


def ensure_section(config_parser: configparser.ConfigParser, section: str) -> None:
  """Ensure a section exists in a ConfigParser."""
  if not config_parser.has_section(section):
    config_parser.add_section(section)


def construct_coverage_config(
  src_to_target_base: Dict
) -> str:
  config_parser = configparser.ConfigParser()
  config_parser.read_file(StringIO(DEFAULT_COVERAGE_CONFIG))
  ensure_section(config_parser, 'run')
  config_parser.set('run', 'plugins', COVERAGE_PLUGIN_MODULE_NAME)
  config_parser.add_section(COVERAGE_PLUGIN_MODULE_NAME)
  config_parser.set(COVERAGE_PLUGIN_MODULE_NAME, 'src_to_target_base', json.dumps(src_to_target_base))
  config = StringIO()
  config_parser.write(config)
  return config.getvalue()


def get_file_names(all_target_adaptors):
  def iter_files():
    for adaptor in all_target_adaptors:
      if hasattr(adaptor, 'sources'):
        for file in adaptor.sources.snapshot.files:
          if file.endswith('.py'):
            yield file

  return list(iter_files())



@rule(name="Generate coverage report")
async def generate_coverage_report(
  test_results: AddressAndTestResults,
  transitive_targets: TransitiveHydratedTargets,
  python_setup: PythonSetup,
  coverage_setup: CoverageSetup,
  source_root_config: SourceRootConfig,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> CoverageReport:
  """Takes all python test results and generates a single coverage report in dist/coverage."""
  requirements_pex = coverage_setup.requirements_pex
  merged_coverage_data = await Get[MergedCoverageData](AddressAndTestResults, test_results)
  python_targets = [
    target for target in transitive_targets.closure
    if target.adaptor.type_alias == 'python_library' or target.adaptor.type_alias == 'python_tests'
  ]

  python_files = frozenset(itertools.chain.from_iterable(
    target.adaptor.sources.snapshot.files for target in python_targets
  ))
  # A map from source root stripped source to its source root. eg:
  #  {'pants/testutil/subsystem/util.py': 'src/python'}
  # This is so coverage reports referencing /chroot/path/pants/testutil/subsystem/util.py can be mapped
  # back to the actual sources they reference when merging coverage reports.
  source_roots_and_source_root_stripped_sources: Dict[str, str] = {}
  # for filename in python_files:
  #   for source_root in source_root_config:
  #     if filename.startswith(source_root):
  #       source_roots_and_source_root_stripped_sources[filename[len(source_root)+1:]] = source_root

  # results = await MultiGet(Get[AddressAndTestResult](Address, addr.to_address()) for addr in addresses)
  # test_results = [
  #   (x.address.to_address().path_safe_spec, x.test_result.coverage_digest)
  #   for x in results if x.test_result is not None
  # ]

  coverage_config_content = construct_coverage_config(source_roots_and_source_root_stripped_sources)
  coveragerc_digest = await Get[Digest](InputFilesContent, get_coveragerc_input(coverage_config_content))
  source_root_stripped_sources = await MultiGet(
    Get[SourceRootStrippedSources](HydratedTarget, hydrated_target)
    for hydrated_target in python_targets
  )
  stripped_sources_digests = tuple(
    stripped_sources.snapshot.directory_digest for stripped_sources in source_root_stripped_sources
  )
  sources_digest = await Get[Digest](DirectoriesToMerge(directories=stripped_sources_digests))
  inits_digest = await Get[InjectedInitDigest](Digest, sources_digest)
  merged_input_files: Digest = await Get(
    Digest,
    DirectoriesToMerge(directories=(
      merged_coverage_data.coverage_data,
      coveragerc_digest,
      requirements_pex.directory_digest,
      sources_digest,
      inits_digest.directory_digest,
    )),
  )

  coverage_args = ['html'] # TODO: Respect the option of html or xml reports.
  request = requirements_pex.create_execute_request(
    python_setup=python_setup,
    subprocess_encoding_environment=subprocess_encoding_environment,
    pex_path=f'./{coverage_setup.filename}',
    pex_args=coverage_args,
    input_files=merged_input_files,
    output_directories=('htmlcov',), # TODO: Respect the xml option.
    description=f'Generate coverage report.',
  )

  result = await Get[FallibleExecuteProcessResult](
    ExecuteProcessRequest,
    request
  )
  print(result)
  return CoverageReport(result.output_directory_digest, 'coverage/python') # TODO Get this from an option.


def rules():
  return [
    subsystem_rule(CoverageToolBase),
    generate_coverage_report,
    merge_coverage_reports,
    setup_coverage,
  ]

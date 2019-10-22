# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.inject_init import InjectedInitDigest
from pants.backend.python.rules.pex import CreatePex, Pex, PexInterpreterContraints, PexRequirements
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.build_graph.address import Address
from pants.engine.fs import Digest, DirectoriesToMerge
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.legacy.graph import BuildFileAddresses, HydratedTarget, TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonTestsAdaptor
from pants.engine.rules import UnionRule, optionable_rule, rule
from pants.engine.selectors import Get
from pants.rules.core.core_test_model import Status, TestResult, TestTarget
from pants.rules.core.strip_source_root import SourceRootStrippedSources


@rule
def run_python_test(
  test_target: PythonTestsAdaptor,
  pytest: PyTest,
  python_setup: PythonSetup,
  subprocess_encoding_environment: SubprocessEncodingEnvironment
) -> TestResult:
  """Runs pytest for one target."""

  # TODO(7726): replace this with a proper API to get the `closure` for a
  # TransitiveHydratedTarget.
  transitive_hydrated_targets = yield Get(
    TransitiveHydratedTargets, BuildFileAddresses((test_target.address,))
  )
  all_targets = transitive_hydrated_targets.closure
  all_target_adaptors = tuple(t.adaptor for t in all_targets)

  interpreter_constraints = PexInterpreterContraints.create_from_adaptors(
    adaptors=tuple(all_target_adaptors),
    python_setup=python_setup
  )

  # Produce a pex containing pytest and all transitive 3rdparty requirements.
  output_pytest_requirements_pex_filename = 'pytest-with-requirements.pex'
  requirements = PexRequirements.create_from_adaptors(
    adaptors=all_target_adaptors,
    additional_requirements=pytest.get_requirement_strings()
  )

  resolved_requirements_pex = yield Get(
    Pex, CreatePex(
      output_filename=output_pytest_requirements_pex_filename,
      requirements=requirements,
      interpreter_constraints=interpreter_constraints,
      entry_point="pytest:main",
    )
  )

  # Get the file names for the test_target, adjusted for the source root. This allows us to
  # specify to Pytest which files to test and thus to avoid the test auto-discovery defined by
  # https://pytest.org/en/latest/goodpractices.html#test-discovery. In addition to a performance
  # optimization, this ensures that any transitive sources, such as a test project file named
  # test_fail.py, do not unintentionally end up being run as tests.

  source_root_stripped_test_target_sources = yield Get(
      SourceRootStrippedSources, Address, test_target.address.to_address()
    )

  source_root_stripped_sources = yield [
    Get(SourceRootStrippedSources, HydratedTarget, target_adaptor)
    for target_adaptor in all_targets
  ]

  stripped_sources_digests = [stripped_sources.snapshot.directory_digest for stripped_sources in source_root_stripped_sources]
  sources_digest = yield Get(
    Digest, DirectoriesToMerge(directories=tuple(stripped_sources_digests)),
  )

  inits_digest = yield Get(InjectedInitDigest, Digest, sources_digest)

  all_input_digests = [
    sources_digest,
    inits_digest.directory_digest,
    resolved_requirements_pex.directory_digest,
  ]
  merged_input_files = yield Get(
    Digest,
    DirectoriesToMerge,
    DirectoriesToMerge(directories=tuple(all_input_digests)),
  )

  test_target_sources_file_names = sorted(source_root_stripped_test_target_sources.snapshot.files)
  # NB: we use the hardcoded and generic bin name `python`, rather than something dynamic like
  # `sys.executable`, to ensure that the interpreter may be discovered both locally and in remote
  # execution (so long as `env` is populated with a `PATH` env var and `python` is discoverable
  # somewhere on that PATH). This is only used to run the downloaded PEX tool; it is not
  # necessarily the interpreter that PEX will use to execute the generated .pex file.
  request = resolved_requirements_pex.create_execute_request(
    python_setup=python_setup,
    subprocess_encoding_environment=subprocess_encoding_environment,
    pex_path=f'./{output_pytest_requirements_pex_filename}',
    pex_args=test_target_sources_file_names,
    input_files=merged_input_files,
    description=f'Run Pytest for {test_target.address.reference()}',
  )

  result = yield Get(FallibleExecuteProcessResult, ExecuteProcessRequest, request)
  status = Status.SUCCESS if result.exit_code == 0 else Status.FAILURE

  yield TestResult(
    status=status,
    stdout=result.stdout.decode(),
    stderr=result.stderr.decode(),
  )


def rules():
  return [
    run_python_test,
    UnionRule(TestTarget, PythonTestsAdaptor),
    optionable_rule(PyTest),
    optionable_rule(PythonSetup),
  ]

# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Dict, Optional

from pants.backend.python.rules.create_requirements_pex import (RequirementsPex,
                                                                RequirementsPexRequest)
from pants.backend.python.rules.inject_init import InjectedInitDigest
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.build_graph.files import Files
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryWithPrefixToStrip
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.legacy.graph import BuildFileAddresses, TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonTestsAdaptor
from pants.engine.rules import UnionRule, optionable_rule, rule
from pants.engine.selectors import Get
from pants.rules.core.core_test_model import Status, TestResult, TestTarget
from pants.source.source_root import SourceRoot, SourceRootConfig
from pants.util.strutil import create_path_env_var, strip_prefix


# TODO(7697): Use a dedicated rule for removing the source root prefix, so that this rule
# does not have to depend on SourceRootConfig.
@rule(TestResult, [PythonTestsAdaptor, PyTest, PythonSetup, SourceRootConfig, SubprocessEncodingEnvironment])
def run_python_test(test_target, pytest, python_setup, source_root_config, subprocess_encoding_environment):
  """Runs pytest for one target."""

  # TODO(7726): replace this with a proper API to get the `closure` for a
  # TransitiveHydratedTarget.
  transitive_hydrated_targets = yield Get(
    TransitiveHydratedTargets, BuildFileAddresses((test_target.address,))
  )
  all_targets = [t.adaptor for t in transitive_hydrated_targets.closure]

  interpreter_constraints = {
    constraint
    for target_adaptor in all_targets
    for constraint in python_setup.compatibility_or_constraints(
      getattr(target_adaptor, 'compatibility', None)
    )
  }

  # Produce a pex containing pytest and all transitive 3rdparty requirements.
  output_pytest_requirements_pex_filename = 'pytest-with-requirements.pex'
  all_target_requirements = []
  for maybe_python_req_lib in all_targets:
    # This is a python_requirement()-like target.
    if hasattr(maybe_python_req_lib, 'requirement'):
      all_target_requirements.append(str(maybe_python_req_lib.requirement))
    # This is a python_requirement_library()-like target.
    if hasattr(maybe_python_req_lib, 'requirements'):
      for py_req in maybe_python_req_lib.requirements:
        all_target_requirements.append(str(py_req.requirement))
  all_requirements = all_target_requirements + list(pytest.get_requirement_strings())
  resolved_requirements_pex = yield Get(
    RequirementsPex, RequirementsPexRequest(
      output_filename=output_pytest_requirements_pex_filename,
      requirements=tuple(sorted(all_requirements)),
      interpreter_constraints=tuple(sorted(interpreter_constraints)),
      entry_point="pytest:main",
    )
  )

  # Get the file names for the test_target, adjusted for the source root. This allows us to
  # specify to Pytest which files to test and thus to avoid the test auto-discovery defined by
  # https://pytest.org/en/latest/goodpractices.html#test-discovery. In addition to a performance
  # optimization, this ensures that any transitive sources, such as a test project file named
  # test_fail.py, do not unintentionally end up being run as tests.
  source_roots = source_root_config.get_source_roots()
  test_target_sources_file_names = []
  for source_target_filename in test_target.sources.files_relative_to_buildroot:
    source_root = source_roots.find_by_path(source_target_filename)
    test_target_sources_file_names.append(
      strip_prefix(source_target_filename, prefix=f"{source_root.path}/")
    )

  # Gather sources and adjust for source roots.
  # TODO: make TargetAdaptor return a 'sources' field with an empty snapshot instead of raising to
  # simplify the hasattr() checks here!
  sources_digest_to_source_roots: Dict[Digest, Optional[SourceRoot]] = {}
  for maybe_source_target in all_targets:
    if not hasattr(maybe_source_target, 'sources'):
      continue
    digest = maybe_source_target.sources.snapshot.directory_digest
    source_root = source_roots.find_by_path(maybe_source_target.address.spec_path)
    if maybe_source_target.type_alias == Files.alias():
      # Loose `Files`, as opposed to `Resources` or `PythonTarget`s, have no (implied) package
      # structure and so we do not remove their source root like we normally do, so that Python
      # filesystem APIs may still access the files. See pex_build_util.py's `_create_source_dumper`.
      source_root = None
    sources_digest_to_source_roots[digest] = source_root.path if source_root else ""

  stripped_sources_digests = yield [
    Get(Digest, DirectoryWithPrefixToStrip(directory_digest=digest, prefix=source_root))
    for digest, source_root in sources_digest_to_source_roots.items()
  ]

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

  interpreter_search_paths = create_path_env_var(python_setup.interpreter_search_paths)
  pex_exe_env = {
    'PATH': interpreter_search_paths,
    **subprocess_encoding_environment.invocation_environment_dict
  }

  # NB: we use the hardcoded and generic bin name `python`, rather than something dynamic like
  # `sys.executable`, to ensure that the interpreter may be discovered both locally and in remote
  # execution (so long as `env` is populated with a `PATH` env var and `python` is discoverable
  # somewhere on that PATH). This is only used to run the downloaded PEX tool; it is not
  # necessarily the interpreter that PEX will use to execute the generated .pex file.
  request = ExecuteProcessRequest(
    argv=(
      "python",
      f'./{output_pytest_requirements_pex_filename}',
      *sorted(test_target_sources_file_names)
    ),
    env=pex_exe_env,
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
    optionable_rule(SourceRootConfig),
  ]

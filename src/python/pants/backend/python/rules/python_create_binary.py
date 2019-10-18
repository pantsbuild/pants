# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.inject_init import InjectedInitDigest
from pants.backend.python.rules.pex import CreatePex, Pex, PexInterpreterContraints, PexRequirements
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_binary import PythonBinary
from pants.engine.fs import Digest, DirectoriesToMerge
from pants.engine.legacy.graph import BuildFileAddresses, HydratedTarget, TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonBinaryAdaptor
from pants.engine.rules import UnionRule, rule
from pants.engine.selectors import Get
from pants.rules.core.binary import BinaryTarget, CreatedBinary
from pants.rules.core.strip_source_root import SourceRootStrippedSources


@rule
def create_python_binary(python_binary_adaptor: PythonBinaryAdaptor,
  python_setup: PythonSetup) -> CreatedBinary:
  transitive_hydrated_targets = yield Get(
    TransitiveHydratedTargets, BuildFileAddresses((python_binary_adaptor.address,))
  )
  all_targets = transitive_hydrated_targets.closure
  all_target_adaptors = [t.adaptor for t in all_targets]


  interpreter_constraints = PexInterpreterContraints.create_from_adaptors(
    adaptors=tuple(all_targets),
    python_setup=python_setup
  )

  source_root_stripped_sources = yield [
    Get(SourceRootStrippedSources, HydratedTarget, target_adaptor)
    for target_adaptor in all_targets
  ]

  #TODO(#8420) This way of calculating the entry point works but is a bit hackish.
  entry_point = None
  if hasattr(python_binary_adaptor, 'entry_point'):
    entry_point = python_binary_adaptor.entry_point
  else:
    sources_snapshot = python_binary_adaptor.sources.snapshot
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

  requirements = PexRequirements.create_from_adaptors(all_target_adaptors)
  output_filename = f"{python_binary_adaptor.address.target_name}.pex"

  create_requirements_pex = CreatePex(
    output_filename=output_filename,
    requirements=requirements,
    interpreter_constraints=interpreter_constraints,
    entry_point=entry_point,
    input_files_digest=merged_input_files,
  )

  pex = yield Get(Pex, CreatePex, create_requirements_pex)
  yield CreatedBinary(digest=pex.directory_digest)


def rules():
  return [
    UnionRule(BinaryTarget, PythonBinaryAdaptor),
    create_python_binary,
  ]

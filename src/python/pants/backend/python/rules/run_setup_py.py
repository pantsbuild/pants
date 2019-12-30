# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
from dataclasses import dataclass
from typing import List, Set, Tuple

from pants.backend.python.rules.pex import (
  CreatePex,
  Pex,
  PexInterpreterConstraints,
  PexRequirements,
)
from pants.backend.python.rules.setup_py_util import (
  PackageDatum,
  distutils_repr,
  find_packages,
  source_root_or_raise,
)
from pants.backend.python.rules.setuptools import Setuptools
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.base.specs import AscendantAddresses, Specs
from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.fs import (
  Digest,
  DirectoriesToMerge,
  DirectoryToMaterialize,
  DirectoryWithPrefixToAdd,
  DirectoryWithPrefixToStrip,
  FileContent,
  InputFilesContent,
  PathGlobs,
  Snapshot,
  Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.legacy.graph import HydratedTarget, HydratedTargets, TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonBinaryAdaptor, PythonTargetAdaptor, ResourcesAdaptor
from pants.engine.objects import Collection
from pants.engine.rules import console_rule, optionable_rule, rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.distdir import DistDir
from pants.rules.core.strip_source_root import SourceRootStrippedSources
from pants.source.source_root import SourceRootConfig


class NoOwnerError(Exception):
  """Indicates an exportable target has no owning exported target."""


class AmbiguousOwnerError(Exception):
  """Indicates an exportable target has more than one owning exported target."""


@dataclass(frozen=True)
class ExportedTarget:
  """A target that explicitly exports an artifact, using a `provides=` stanza.

  The code provided by this artifact can be from this target or from any targets it owns.
  """
  hydrated_target: HydratedTarget


@dataclass(frozen=True)
class DependencyOwner:
  """An ExportedTarget in its role as an owner of other targets.

  We need this type to prevent rule ambiguities when computing the list of targets
  owned by an ExportedTarget (which involves going from ExportedTarget -> dep -> owner (which
  is itself an ExportedTarget) and checking if owner is this the original ExportedTarget.
  """
  exported_target: ExportedTarget


@dataclass(frozen=True)
class OwnedDependency:
  """A target that is owned by some ExportedTarget.

  Code in this target is published in the owner's artifact.

  The owner of a target T is T's closest filesystem ancestor among the exported targets
  that directly or indirectly depend on it (including T itself).
  """
  hydrated_target: HydratedTarget


class OwnedDependencies(Collection[OwnedDependency]):
  pass


@dataclass(frozen=True)
class ExportedTargetRequirements:
  """The requirements of an ExportedTarget.

  Includes:
  - The "normal" 3rdparty requirements of the ExportedTarget and all targets it owns.
  - The published versions of any other ExportedTargets it depends on.
  """
  requirement_strs: Tuple[str, ...]


@dataclass(frozen=True)
class AncestorInitPyFiles:
  """__init__.py files in enclosing packages of the exported code."""
  digests: Tuple[Digest, ...]  # The files stripped of their source roots.


@dataclass(frozen=True)
class SetupPySourcesRequest:
  hydrated_targets: HydratedTargets


@dataclass(frozen=True)
class SetupPySources:
  """The sources required by a setup.py command.

  Includes some information derived from analyzing the source, namely the packages,
  namespace packages and resource files in the source.
  """
  digest: Digest
  packages: Tuple[str, ...]
  namespace_packages: Tuple[str, ...]
  package_data: Tuple[PackageDatum, ...]


@dataclass(frozen=True)
class SetuptoolsSetup:
  """The setuptools tool."""
  requirements_pex: Pex


@rule
async def get_sources(request: SetupPySourcesRequest,
                      source_root_config: SourceRootConfig) -> SetupPySources:
  targets = request.hydrated_targets
  stripped_srcs_list = await MultiGet(
    Get[SourceRootStrippedSources](HydratedTarget, target) for target in targets)

  # Create a chroot with all the sources, and any ancestor __init__.py files that might be needed
  # for imports to work.  Note that if a repo has multiple exported targets under a single ancestor
  # package, then that package must be a namespace package, which in Python 3 means it must not
  # have an __init__.py. We don't validate this here, because it would require inspecting *all*
  # targets, whether or not they are in the target set for this run - basically the entire repo.
  # So it's the repo owners' responsibility to ensure __init__.py hygiene.
  stripped_srcs_digests = [stripped_sources.snapshot.directory_digest
                           for stripped_sources in stripped_srcs_list]
  ancestor_init_pys = await Get[AncestorInitPyFiles](HydratedTargets, targets)
  sources_digest = await Get[Digest](
    DirectoriesToMerge(directories=tuple([*stripped_srcs_digests, *ancestor_init_pys.digests])))
  sources_snapshot = await Get[Snapshot](Digest, sources_digest)
  packages, namespace_packages, package_data = find_packages(
    source_root_config.get_source_roots(), zip(targets, stripped_srcs_list), sources_snapshot)
  return SetupPySources(digest=sources_digest, packages=packages,
                        namespace_packages=namespace_packages, package_data=package_data)


@rule
async def get_ancestor_init_py(
    targets: HydratedTargets,
    source_root_config: SourceRootConfig
) -> AncestorInitPyFiles:
  """Find any ancestor __init__.py files for the given targets.

  Includes sibling __init__.py files. Returns the files stripped of their source roots.
  """
  source_roots = source_root_config.get_source_roots()
  # Find the ancestors of all dirs containing .py files, including those dirs themselves.
  source_dir_ancestors: Set[Tuple[str, str]] = set()  # Items are (src_root, path incl. src_root).
  sources_snapshots = await MultiGet(
    Get[Snapshot](Digest, target.adaptor.sources.snapshot.directory_digest)
    for target in targets if isinstance(target.adaptor, PythonTargetAdaptor)
  )
  for sources_snapshot in sources_snapshots:
    for file in sources_snapshot.files:
      source_dir_ancestor = os.path.dirname(file)
      source_root = source_root_or_raise(source_roots, file)
      # Do not allow the repository root to leak (i.e., '.' should not be a package in setup.py).
      while source_dir_ancestor != source_root:
        source_dir_ancestors.add((source_root, source_dir_ancestor))
        source_dir_ancestor = os.path.dirname(source_dir_ancestor)

  source_dir_ancestors_list = list(source_dir_ancestors)  # To force a consistent order.

  # Note that we must MultiGet single globs instead of a a single Get for all the globs, because
  # we match each result to its originating glob (see use of zip below).
  ancestor_init_py_snapshots = await MultiGet[Snapshot](
    Get[Snapshot](PathGlobs,
                  PathGlobs(include=(os.path.join(source_dir_ancestor[1], '__init__.py'),)))
    for source_dir_ancestor in source_dir_ancestors_list
  )

  source_root_stripped_ancestor_init_pys = await MultiGet[Digest](
    Get[Digest](DirectoryWithPrefixToStrip(
      directory_digest=snapshot.directory_digest, prefix=source_dir_ancestor[0])
  ) for snapshot, source_dir_ancestor in zip(ancestor_init_py_snapshots, source_dir_ancestors_list))

  return AncestorInitPyFiles(source_root_stripped_ancestor_init_pys)


def _is_exported(target: HydratedTarget) -> bool:
  return getattr(target.adaptor, 'provides', None) is not None


@rule(name="Get requirements")
async def get_requirements(dep_owner: DependencyOwner) -> ExportedTargetRequirements:
  tht = await Get[TransitiveHydratedTargets](
    BuildFileAddresses([dep_owner.exported_target.hydrated_target.address]))

  ownable_tgts = [tgt for tgt in tht.closure
                  if isinstance(tgt.adaptor, (PythonTargetAdaptor, ResourcesAdaptor))]
  owners = await MultiGet(Get[ExportedTarget](OwnedDependency(ht)) for ht in ownable_tgts)
  owned_by_us = set()
  owned_by_others = set()
  for tgt, owner in zip(ownable_tgts, owners):
    (owned_by_us if owner == dep_owner.exported_target else owned_by_others).add(tgt)

  # Get all 3rdparty deps of our owned deps.
  #
  # Note that we need only consider requirements that are direct dependencies of our owned deps:
  # If T depends on R indirectly, then it must be via some direct deps U1, U2, ... For each such U,
  # if U is in the owned deps then we'll pick up R through U. And if U is not in the owned deps
  # then it's owned by an exported target ET, and so R will be in the requirements for ET, and we
  # will require ET.
  #
  # TODO: Note that this logic doesn't account for indirection via dep aggregator targets, of type
  #  `target`. But we don't have those in v2 (yet) anyway. Plus, as we move towards buildgen and/or
  #  stricter build graph hygiene, it makes sense to require that targets directly declare their
  #  true dependencies. Plus, in the specific realm of setup-py, since we must exclude indirect
  #  deps across exported target boundaries, it's not a big stretch to just insist that
  #  requirements must be direct deps.
  direct_deps_addrs = tuple({dep for ht in owned_by_us for dep in ht.dependencies})
  direct_deps_tgts = await MultiGet(Get[HydratedTarget](Address, a) for a in direct_deps_addrs)
  reqs = PexRequirements.create_from_adaptors(tgt.adaptor for tgt in direct_deps_tgts)
  req_strs = list(reqs.requirements)

  # Add the requirements on any exported targets on which we depend.
  exported_targets_we_depend_on = await MultiGet(
    Get[ExportedTarget](OwnedDependency(ht)) for ht in owned_by_others)
  req_strs.extend(et.hydrated_target.adaptor.provides.key
                  for et in set(exported_targets_we_depend_on))

  return ExportedTargetRequirements(tuple(sorted(req_strs)))


@rule(name="Get owned targets")
async def get_owned_dependencies(dependency_owner: DependencyOwner) -> OwnedDependencies:
  """Find the dependencies of dependency_owner that are owned by it.

  Includes dependency_owner itself.
  """
  tht = await Get[TransitiveHydratedTargets](
    BuildFileAddresses([dependency_owner.exported_target.hydrated_target.address]))
  all_tgts = list(tht.closure)
  ownable_targets = [tgt for tgt in all_tgts
                     if isinstance(tgt.adaptor, (PythonTargetAdaptor, ResourcesAdaptor))]
  owners = await MultiGet(Get[ExportedTarget](OwnedDependency(ht)) for ht in ownable_targets)
  owned_dependencies = [tgt for owner, tgt in zip(owners, ownable_targets)
                        if owner == dependency_owner.exported_target]
  return OwnedDependencies(OwnedDependency(t) for t in owned_dependencies)


@rule(name="Get exporting owner for target")
async def get_exporting_owner(owned_dependency: OwnedDependency) -> ExportedTarget:
  """Find the exported target that owns the given target (and therefore exports it).

  The owner of T (i.e., the exported target in whose artifact T's code is published) is:

   1. An exported target that depends on T (or is T itself).
   2. Is T's closest filesystem ancestor among those satisfying 1.

  If there are multiple such exported targets at the same degree of ancestry, the ownership
  is ambiguous and an error is raised. If there is no exported target that depends on T
  and is its ancestor, then there is no owner and an error is raised.
  """
  hydrated_target = owned_dependency.hydrated_target
  ancestor_addrs = AscendantAddresses(hydrated_target.address.spec_path)
  ancestor_tgts = await Get[HydratedTargets](Specs, Specs((ancestor_addrs,)))
  # Note that addresses sort by (spec_path, target_name), and all these targets are
  # ancestors of the given target, i.e., their spec_paths are all prefixes. So sorting by
  # address will effectively sort by closeness of ancestry to the given target.
  exported_ancestor_tgts = sorted(
    [t for t in ancestor_tgts if _is_exported(t)], key=lambda t: t.address, reverse=True)
  exported_ancestor_iter = iter(exported_ancestor_tgts)
  for exported_ancestor in exported_ancestor_iter:
    tht = await Get[TransitiveHydratedTargets](BuildFileAddresses([exported_ancestor.address]))
    if hydrated_target in tht.closure:
      owner = exported_ancestor
      # Find any exported siblings of owner that also depend on hydrated_target. They have the
      # same spec_path as it, so they must immediately follow it in ancestor_iter.
      sibling_owners = []
      sibling = next(exported_ancestor_iter, None)
      while sibling and sibling.address.spec_path == owner.address.spec_path:
        tht = await Get[TransitiveHydratedTargets](BuildFileAddresses([sibling.address]))
        if hydrated_target in tht.closure:
          sibling_owners.append(sibling)
        sibling = next(exported_ancestor_iter, None)
      if sibling_owners:
        raise AmbiguousOwnerError(
          f'Exporting owners for {hydrated_target.address.reference()} are ambiguous. Found '
          f'{exported_ancestor.address.reference()} and {len(sibling_owners)} others: '
          f'{", ".join(so.address.reference() for so in sibling_owners)}')
      return ExportedTarget(owner)
  raise NoOwnerError(f'No exported target owner found for {hydrated_target.address.reference()}')


@rule(name="Set up setuptools")
async def setup_setuptools(setuptools: Setuptools) -> SetuptoolsSetup:
  requirements_pex = await Get[Pex](
    CreatePex(
      output_filename="setuptools.pex",
      requirements=PexRequirements(requirements=tuple(setuptools.get_requirement_specs())),
      interpreter_constraints=PexInterpreterConstraints(
        constraint_set=tuple(setuptools.default_interpreter_constraints)
      ),
      entry_point=setuptools.get_entry_point(),
    )
  )
  return SetuptoolsSetup(
    requirements_pex=requirements_pex,
  )

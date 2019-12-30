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
class SetuptoolsSetup:
  """The setuptools tool."""
  requirements_pex: Pex


def _is_exported(target: HydratedTarget) -> bool:
  return getattr(target.adaptor, 'provides', None) is not None


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


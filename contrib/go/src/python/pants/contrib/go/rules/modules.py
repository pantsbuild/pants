# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddress, BuildFileAddresses
from pants.engine.fs import Snapshot
from pants.engine.graph import HydratedTarget
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.legacy.structs import TargetAdaptor
from pants.engine.objects import Collection
from pants.engine.rules import UnionRule, optionable_rule, rule
from pants.engine.selectors import Get
from pants.rules.core.core_test_model import Status, TestResult, TestTarget
from pants.source.source_root import AllSourceRoots, SourceRoot

from pants.contrib.go.subsystems.go_distribution import GoDistribution
from pants.contrib.go.targets.go_module import GoModule


@dataclass(frozen=True)
class GoModuleInfo:
  address: Address
  sources: Snapshot
  source_root: SourceRoot


GoModuleInfos = Collection.of(GoModuleInfo)


@rule
def get_go_module_infos(bfa: BuildFileAddresses, all_source_roots: AllSourceRoots) -> GoModuleInfos:
  go_source_roots = [
    r.path for r in all_source_roots if 'go' in r.langs
  ]
  def find_matching_source_root(t: HydratedTarget) -> SourceRoot:
    return next(
      r for r in go_source_roots
      if t.address.spec_path.startswith(r)
    )

  hydrated_targets = [yield Get(HydratedTarget, BuildFileAddress, a) for a in bfa]
  go_module_targets = [t for t in hydrated_targets if t.adaptor.type_alias == GoModule.alias()]

  infos = [
    GoModuleInfo(t.address, t.adaptor.sources, find_matching_source_root(t))
    for t in go_module_targets
  ]

  yield GoModuleInfos(infos)


@rule
def test_go_module(info: GoModuleInfo, go_dist: GoDistribution) -> TestResult:



def rules():
  return [
    optionable_rule(GoDistribution),
  ]

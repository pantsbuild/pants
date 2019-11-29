# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import FrozenSet, Tuple

from pants.engine.fs import Snapshot
from pants.engine.legacy.graph import HydratedTarget, TransitiveHydratedTargets
from pants.engine.rules import rule
from pants.util.memo import memoized_classproperty


@dataclass(frozen=True)
class ThriftableTargets:
  targets: Tuple[HydratedTarget, ...]

  @memoized_classproperty
  def known_build_file_aliases(cls) -> FrozenSet[str]:
    # FIXME: copied from register.py!
    return frozenset([
      'java_antlr_library',
      'java_protobuf_library',
      'java_ragel_library',
      'java_thrift_library',
      'java_wire_library',
      'python_antlr_library',
      'python_thrift_library',
      'python_grpcio_library',
      'jaxb_library',
    ])


@rule
def collect_thriftable_targets(thts: TransitiveHydratedTargets) -> ThriftableTargets:
  return ThriftableTargets(
    hydrated_target
    for hydrated_target in thts.closure
    if hydrated_target.adaptor.type_alias in ThriftableTargets.known_build_file_aliases
  )


@dataclass(frozen=True)
class ThriftedTarget:
  original: HydratedTarget
  output: Snapshot


@dataclass(frozen=True)
class ThriftResults:
  thrifted_targets: Tuple[ThriftedTarget, ...]


@rule
def fast_thrift_gen(thriftable_targets: ThriftableTargets) -> ThriftResults:
  # TODO: jvm process execution!!!
  return None


def rules():
  return [
    collect_thriftable_targets,
    fast_thrift_gen,
  ]

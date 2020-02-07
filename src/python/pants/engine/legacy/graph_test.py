# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from typing import Dict, Tuple

import pytest

from pants.engine.legacy.graph import HydratedTarget, topo_sort
from pants.engine.legacy.structs import TargetAdaptor


def make_graph(name_to_deps: Dict[str, Tuple[str, ...]]) -> Dict[str, HydratedTarget]:
  name_to_ht: Dict[str, HydratedTarget] = {}

  def make_ht(nm: str) -> HydratedTarget:
    if nm not in name_to_ht:
      dep_hts = tuple(make_ht(dep) for dep in name_to_deps[nm])
      name_to_ht[nm] = HydratedTarget(
        address=nm, adaptor=TargetAdaptor(), dependencies=dep_hts,  # type: ignore[arg-type]
      )
    return name_to_ht[nm]

  for name in name_to_deps:
    make_ht(name)
  return name_to_ht


@pytest.mark.parametrize(['name_to_deps', 'expected_order'], [
  [{}, ()],
  [{'A': ()}, ('A',)],
  [{'A': (), 'B': ('A',)}, ('A', 'B')],
  [{'A': (), 'B': ('A',), 'C': ('B',), 'D': ('A',), 'E': ('C', 'D')},
   ('A', 'B', 'C', 'D', 'E')],
  [{'A': (), 'B': (), 'C': ('A', 'B'), 'D': ('A', 'F'), 'E': ('C',), 'F': ('B',)},
   ('A', 'B', 'C', 'F', 'D', 'E')],
])
def test_topo_sort(name_to_deps: Dict[str, Tuple[str, ...]],
                   expected_order: Tuple[str, ...]) -> None:
  name_to_ht: Dict[str, HydratedTarget] = make_graph(name_to_deps)
  hts = list(name_to_ht.values())

  # Note that here we check not just for a valid topo sort, but for a specific one from amongst
  # all valid ones. This is therefore implementation- and input order-dependent.
  assert expected_order == tuple(ht.address for ht in topo_sort(hts))  # type: ignore[comparison-overlap]

  # Now we do a more general check for validity of the result, but for every possible input order.
  def assert_is_topo_order(ordered_hts):
    name_to_idx = {ht.address: idx for idx, ht in enumerate(ordered_hts)}
    for name, deps in name_to_deps.items():
      for dep in deps:
        assert name_to_idx[dep] < name_to_idx[name]

  for perm in itertools.permutations(hts):
    assert_is_topo_order(topo_sort(perm))


def test_topo_sort_filtered() -> None:
  # Test that we don't return targets not in the input set.
  name_to_deps: Dict[str, Tuple[str, ...]] = {'A': (), 'B': ('A',), 'C': ('B',), 'D': ('A',), 'E': ('C', 'D')}
  name_to_ht: Dict[str, HydratedTarget] = make_graph(name_to_deps)
  filtered_hts = [name_to_ht['E'], name_to_ht['A'], name_to_ht['B']]
  assert ('A', 'B', 'E') == tuple(ht.address for ht in topo_sort(filtered_hts))  # type: ignore[comparison-overlap]

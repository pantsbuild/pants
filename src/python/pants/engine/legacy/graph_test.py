# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from typing import Tuple, Dict

import pytest

from pants.engine.legacy.graph import HydratedTarget, topo_sort


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
  name_to_ht: Dict[str, HydratedTarget] = {}

  def make_ht(name: str) -> HydratedTarget:
    if name not in name_to_ht:
      dep_hts = tuple(make_ht(dep) for dep in name_to_deps[name])
      name_to_ht[name] = HydratedTarget(address=name, adaptor=None, dependencies=dep_hts)
    return name_to_ht[name]

  hts = tuple(make_ht(name) for name in name_to_deps)
  # Note that here we check not just for a valid topo sort, but for a specific one from amongst
  # all valid ones. This is therefore implementation- and input order-dependent.
  assert expected_order == tuple(ht.address for ht in topo_sort(hts))

  # Now we do a more general check for validity of the result, but for every possible input order.
  def assert_is_topo_order(ordered_hts):
    name_to_idx = {ht.address: idx for idx, ht in enumerate(ordered_hts)}
    for name, deps in name_to_deps.items():
      for dep in deps:
        assert name_to_idx[dep] < name_to_idx[name]

  for perm in itertools.permutations(hts):
    assert_is_topo_order(topo_sort(perm))

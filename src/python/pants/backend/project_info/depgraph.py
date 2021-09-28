# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import collections.abc
import itertools
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, is_dataclass
from json import JSONEncoder
from typing import Iterable

from pkg_resources import Requirement

from pants.engine.addresses import Addresses
from pants.engine.internals.selectors import MultiGet
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    Target,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
    UnexpandedTargets,
)
from pants.util.frozendict import FrozenDict
from pants.util.meta import frozen_after_init


@frozen_after_init
@dataclass(unsafe_hash=True)
class Vertex:
    id: str
    data: FrozenDict

    def __init__(self, _id: str, data: dict):
        self.id = _id
        self.data = FrozenDict(data)


@frozen_after_init
@dataclass(unsafe_hash=True)
class Edge:
    src_id: str
    dep_id: str
    data: FrozenDict

    def __init__(self, src_id: str, dep_id: str, data: dict):
        self.src_id = src_id
        self.dep_id = dep_id
        self.data = FrozenDict(data)


@frozen_after_init
@dataclass(unsafe_hash=True)
class DependencyGraph:
    """A somewhat generic representation of a dependency graph.

    A vertex can represent a BUILD target, a (file, BUILD target) pair, or (in the future) some
    other granularity. The data attached to each vertex may depend on what it represents.
    The set of vertices may or may not be transitively closed, depending on what was requested at
    its construction. So in the general case this data structure represents some useful subset
    of all possible targets and dependencies in the repo.

    A vertex is identified by an opaque id. These ids are not guaranteed to be stable
    across multiple runs of the graph creation code.  There are useful member functions
    that query the graph in terms of Vertex objects alone, so that callers don't have to
    directly handle ids.

    An edge V1->V2 indicates that V1 depends on V2. An edge may have data attached to it.
    """

    vertices: tuple[Vertex, ...]
    edges: tuple[Edge, ...]

    # Redundant data structures useful for querying the graph.
    vertices_by_id: FrozenDict[str, Vertex]
    edges_by_src: FrozenDict[str, tuple[Edge, ...]]
    edges_by_dep: FrozenDict[str, tuple[Edge, ...]]

    def __init__(self, vertices: Iterable[Vertex], edges: Iterable[Edge]):
        self.vertices = tuple(vertices)
        self.edges = tuple(edges)
        self.vertices_by_id = FrozenDict({v.id: v for v in self.vertices})
        edges_by_src = defaultdict(list)
        edges_by_dep = defaultdict(list)
        for edge in self.edges:
            edges_by_src[edge.src_id].append(edge)
            edges_by_dep[edge.dep_id].append(edge)
        self.edges_by_src = FrozenDict({k: tuple(v) for k, v in edges_by_src.items()})
        self.edges_by_dep = FrozenDict({k: tuple(v) for k, v in edges_by_dep.items()})

    def get_dependencies(self, v: Vertex) -> tuple[Vertex, ...]:
        return tuple(self.vertices_by_id[edge.dep_id] for edge in self.edges_by_src.get(v.id, []))

    def get_dependees(self, v: Vertex) -> tuple[Vertex, ...]:
        return tuple(self.vertices_by_id[edge.src_id] for edge in self.edges_by_dep.get(v.id, []))

    def to_json(self) -> str:
        """A full representation from which this object can be parsed."""
        return json.dumps(self, cls=DependencyGraphJSONEncoder, indent=2)

    def to_dependencies_json(self) -> str:
        """A simplified representation where the dependencies are inlined onto the src vertex."""
        return json.dumps(
            [
                {
                    **vertex.data,
                    "dependencies": [v.data["address"] for v in self.get_dependencies(vertex)],
                }
                for vertex in self.vertices
            ],
            indent=2,
        )


class DependencyGraphJSONEncoder(JSONEncoder):
    safe_to_str_types = (Requirement,)

    def default(self, o):
        if isinstance(o, DependencyGraph):
            return {"vertices": o.vertices, "edges": o.edges}
        if isinstance(o, Vertex):
            return {"id": o.id, "data": o.data}
        if isinstance(o, Edge):
            return {"src_id": o.src_id, "dep_id": o.dep_id, "data": o.data}
        if isinstance(o, FrozenDict):
            return dict(o)  # Unfortunately, FrozenDict is not JSON serializable.
        if is_dataclass(o):
            return asdict(o)
        if isinstance(o, collections.abc.Mapping):
            return dict(o)
        if isinstance(o, collections.abc.Sequence):
            return list(o)
        try:
            return super().default(o)
        except TypeError:
            return str(o)


@dataclass(frozen=True)
class DependencyGraphRequest:
    addresses: Addresses
    transitive: bool
    exclude_defaults: bool  # Whether to omit data values that match their defaults.


_nothing = object()


@rule
async def generate_graph(request: DependencyGraphRequest) -> DependencyGraph:
    def target_sorter(tgts_to_sort: Iterable[Target]) -> list[Target]:
        return sorted(tgts_to_sort, key=lambda t: t.address)

    if request.transitive:
        transitive_targets = await Get(
            TransitiveTargets,
            TransitiveTargetsRequest(request.addresses, include_special_cased_deps=True),
        )
        targets = set(transitive_targets.closure)
    else:
        unexpanded_targets = await Get(UnexpandedTargets, Addresses, request.addresses)
        targets = set(unexpanded_targets)

    sorted_targets = target_sorter(targets)

    dependencies_per_target = await MultiGet(
        Get(
            Targets,
            DependenciesRequest(tgt.get(Dependencies), include_special_cased_deps=True),
        )
        for tgt in sorted_targets
    )

    id_seq = 0
    vertices = []
    vertices_by_tgt = {}
    # Make sure we create vertices for the dependencies, even in non-transitive mode.
    vertex_targets = target_sorter(
        targets | set(itertools.chain.from_iterable(dependencies_per_target))
    )
    for tgt in vertex_targets:
        tgt_id = str(id_seq)
        id_seq += 1
        addr = tgt.address
        vertex_data: dict = {
            "address": addr.spec,
            "target_type": tgt.alias,
            **{
                k.alias: v.value
                for k, v in tgt.field_values.items()
                if not (request.exclude_defaults and getattr(k, "default", _nothing) == v.value)
            },
        }
        vertex = Vertex(tgt_id, vertex_data)
        vertices.append(vertex)
        vertices_by_tgt[tgt] = vertex

    edges: list[Edge] = []
    for src_tgt, deps in zip(sorted_targets, dependencies_per_target):
        src_id = vertices_by_tgt[src_tgt].id
        sorted_deps = target_sorter(deps)
        # TODO: It would be useful to add to the edge data whether that dep is explicit or inferred.
        edge_data: dict = {}
        edges.extend(
            Edge(src_id, vertices_by_tgt[dep_tgt].id, edge_data) for dep_tgt in sorted_deps
        )

    return DependencyGraph(vertices, edges)


def rules():
    return collect_rules()

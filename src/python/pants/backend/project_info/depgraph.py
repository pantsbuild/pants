# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import json
from collections import defaultdict
from dataclasses import dataclass
from json import JSONEncoder
from typing import Iterable

from pants.backend.python.target_types import PythonRequirementsField
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
        return json.dumps(self, cls=DependencyGraphJSONEncoder, indent=2)


class DependencyGraphJSONEncoder(JSONEncoder):
    def default(self, o):
        if isinstance(o, DependencyGraph):
            return {"vertices": o.vertices, "edges": o.edges}
        elif isinstance(o, Vertex):
            return {"id": o.id, "data": o.data}
        elif isinstance(o, Edge):
            return {"src_id": o.src_id, "dep_id": o.dep_id, "data": o.data}
        elif isinstance(o, FrozenDict):
            return dict(o)  # Unfortunately, FrozenDict is not JSON serializable.
        return super().default(o)


@dataclass(frozen=True)
class DependencyGraphRequest:
    addresses: Addresses
    transitive: bool


@rule
async def generate_graph(request: DependencyGraphRequest) -> DependencyGraph:
    def target_sorter(tgts_to_sort: Iterable[Target]) -> list[Target]:
        return sorted(tgts_to_sort, key=lambda t: t.address)

    if request.transitive:
        transitive_targets = await Get(
            TransitiveTargets,
            TransitiveTargetsRequest(request.addresses, include_special_cased_deps=True),
        )
        targets = set(transitive_targets.roots) | set(transitive_targets.dependencies)
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
            "type": tgt.alias,
        }
        # TODO: Code in project_info shouldn't import from, or know about, Python-specific fields.
        #  We need a generic way to express "this target represents these 3rdparty dep coordinates".
        if tgt.has_field(PythonRequirementsField):
            vertex_data["requirements"] = tuple(
                str(python_req) for python_req in tgt[PythonRequirementsField].value
            )

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

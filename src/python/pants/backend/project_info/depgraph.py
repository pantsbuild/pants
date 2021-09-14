# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from json import JSONEncoder
from typing import Iterable, cast

from pants.backend.python.target_types import PythonRequirementsField
from pants.base.specs import AddressSpecs, MaybeEmptyDescendantAddresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.internals.selectors import MultiGet
from pants.engine.rules import Get, collect_rules, goal_rule, rule
from pants.engine.target import Dependencies, DependenciesRequest, Targets
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


class Granularity(Enum):
    FILE = "file"
    TARGET = "target"
    DIRECTORY = "directory"


class GraphFormat(Enum):
    JSON = "json"
    DOT = "dot"


class DepGraphSubsystem(LineOriented, GoalSubsystem):
    name = "depgraph"
    help = "Emit a dependency graph for the entire repo."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--granularity",
            type=Granularity,
            default=Granularity.FILE,
            help="Emit the graph at this level of granularity",
        )
        register(
            "--format",
            type=GraphFormat,
            default=GraphFormat.JSON,
            help="Emit the graph in this format.",
        )

    @property
    def format(self) -> GraphFormat:
        return cast(GraphFormat, self.options.format)

    @property
    def granularity(self) -> Granularity:
        return cast(Granularity, self.options.granularity)


class DepGraphGoal(Goal):
    subsystem_cls = DepGraphSubsystem


@dataclass(frozen=True)
class Vertex:
    id: str
    data: dict

    def to_dict(self) -> dict:
        return {"id": self.id, "data": self.data}


@dataclass(frozen=True)
class Edge:
    src_id: str
    dep_id: str
    data: dict

    def to_dict(self) -> dict:
        return {"src_id": self.src_id, "dep_id": self.dep_id, "data": self.data}


@frozen_after_init
@dataclass(unsafe_hash=True)
class DependencyGraph:
    """A somewhat generic representation of a dependency graph.

    A vertex can represent a BUILD target, a (file, BUILD target) pair, or (in the future) some
    other granularity. The data attached to each vertex may depend on what it represents.

    A vertex is identified by an opaque id. These ids are not guaranteed to be stable
    across multiple runs of the graph creation code.

    An edge V1->V2 indicates that V1 depends on V2. An edge may have data attached to it.
    """

    granularity: Granularity
    vertices: tuple[Vertex, ...]
    edges: tuple[Edge, ...]

    def __init__(self, granularity: Granularity, vertices: Iterable[Vertex], edges: Iterable[Edge]):
        self.granularity = granularity
        self.vertices = tuple(vertices)
        self.edges = tuple(edges)

    def to_dict(self) -> dict:
        return {
            "granularity": self.granularity.name,
            "vertices": self.vertices,
            "edges": self.edges,
        }

    def to_json(self) -> str:
        return json.dumps(self, cls=DependencyGraphJSONEncoder, indent=2)


class DependencyGraphJSONEncoder(JSONEncoder):
    def default(self, o):
        if isinstance(o, (Vertex, Edge, DependencyGraph)):
            return o.to_dict()


@dataclass(frozen=True)
class DependencyGraphRequest:
    granularity: Granularity


@rule
async def generate_graph(request: DependencyGraphRequest) -> DependencyGraph:
    id_seq = 0
    all_tgts = await Get(Targets, AddressSpecs([MaybeEmptyDescendantAddresses("")]))
    sorted_all_tgts = sorted(all_tgts, key=lambda t: t.address)
    vertices_by_tgt = {}
    for tgt in sorted_all_tgts:
        tgt_id = str(id_seq)
        id_seq += 1
        addr = tgt.address
        vertex_data: dict = {
            "path": addr.filename if addr.is_file_target else None,
            "target": addr.maybe_convert_to_build_target().spec,
            "type": tgt.alias,
        }
        # TODO: Code in project_info shouldn't import from, or know about, Python-specific fields.
        #  We need a generic way to express "this target represents these 3rdparty dep coordinates"
        #  (This goes for the dependencies goal as well).
        if tgt.has_field(PythonRequirementsField):
            vertex_data["requirements"] = [
                str(python_req) for python_req in tgt[PythonRequirementsField].value
            ]

        vertex = Vertex(tgt_id, vertex_data)
        vertices_by_tgt[tgt] = vertex

    vertices = tuple(sorted(vertices_by_tgt.values(), key=lambda x: x.id))

    edges: list[Edge] = []
    dependencies_per_tgt = await MultiGet(
        Get(
            Targets,
            DependenciesRequest(tgt.get(Dependencies), include_special_cased_deps=True),
        )
        for tgt in sorted_all_tgts
    )
    for src_tgt, deps in zip(sorted_all_tgts, dependencies_per_tgt):
        src_id = vertices_by_tgt[src_tgt].id
        sorted_deps = sorted(deps, key=lambda t: t.address)
        # TODO: It would be useful to add to the edge data whether that dep is explicit or inferred.
        edge_data: dict = {}
        edges.extend(
            Edge(src_id, vertices_by_tgt[dep_tgt].id, edge_data) for dep_tgt in sorted_deps
        )

    return DependencyGraph(request.granularity, vertices, edges)


@goal_rule
async def graph(console: Console, depgraph_subsystem: DepGraphSubsystem) -> DepGraphGoal:
    if depgraph_subsystem.granularity != Granularity.FILE:
        raise NotImplementedError("Granularity other than file not supported yet.")
    if depgraph_subsystem.format != GraphFormat.JSON:
        raise NotImplementedError("Output format other than json not supported yet.")

    dep_graph = await Get(DependencyGraph, DependencyGraphRequest(depgraph_subsystem.granularity))
    console.print_stdout(dep_graph.to_json())

    logger.info(
        f"Emitted dependency graph at {dep_graph.granularity} granilarity with "
        f"{len(dep_graph.vertices)} vertices and {len(dep_graph.edges)} edges."
    )

    return DepGraphGoal(exit_code=0)


def rules():
    return collect_rules()

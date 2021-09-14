# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent

import pytest

from pants.backend.project_info.depgraph import (
    DependencyGraph,
    DependencyGraphRequest,
    Edge,
    Granularity,
    Vertex,
    rules,
)
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
from pants.engine.rules import QueryRule
from pants.engine.target import SpecialCasedDependencies, Target
from pants.testutil.rule_runner import RuleRunner


# We verify that any subclasses of `SpecialCasedDependencies` will show up with the `dependencies`
# goal by creating a mock target.
class SpecialDepsField(SpecialCasedDependencies):
    alias = "special_deps"


class SpecialDepsTarget(Target):
    alias = "special_deps_tgt"
    core_fields = (SpecialDepsField,)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[*rules(), QueryRule(DependencyGraph, [DependencyGraphRequest])],
        target_types=[PythonLibrary, PythonRequirementLibrary, SpecialDepsTarget],
    )


def test_depgraph_construction(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file(
        "3rdparty/python",
        dedent(
            """\
            python_requirement_library(
                name='extlib',
                requirements=['extlib==1.2.3'],
            )
            """
        ),
    )
    rule_runner.add_to_build_file(
        "src/python/foo/",
        dedent(
            """\
            python_library(dependencies=['3rdparty/python:extlib'])
            """
        ),
    )
    rule_runner.create_file("src/python/foo/bar.py", "")
    rule_runner.add_to_build_file(
        "src/python/baz/",
        dedent(
            """\
            python_library(name="lib", dependencies=['src/python/foo'])
            """
        ),
    )
    rule_runner.create_file("src/python/baz/qux.py", "")

    dep_graph = rule_runner.request(
        DependencyGraph, [DependencyGraphRequest(granularity=Granularity.FILE)]
    )
    assert dep_graph == DependencyGraph(
        granularity=Granularity.FILE,
        vertices=[
            Vertex(
                "0",
                {
                    "path": None,
                    "target": "3rdparty/python:extlib",
                    "type": "python_requirement_library",
                    "requirements": ["extlib==1.2.3"],
                },
            ),
            Vertex(
                "1",
                {
                    "path": "src/python/baz/qux.py",
                    "target": "src/python/baz:lib",
                    "type": "python_library",
                },
            ),
            Vertex(
                "2",
                {
                    "path": "src/python/foo/bar.py",
                    "target": "src/python/foo",
                    "type": "python_library",
                },
            ),
        ],
        edges=[
            Edge("1", "2", {}),
            Edge("2", "0", {}),
        ],
    )

    assert dep_graph.to_json() == dedent(
        """\
    {
      "granularity": "FILE",
      "vertices": [
        {
          "id": "0",
          "data": {
            "path": null,
            "target": "3rdparty/python:extlib",
            "type": "python_requirement_library",
            "requirements": [
              "extlib==1.2.3"
            ]
          }
        },
        {
          "id": "1",
          "data": {
            "path": "src/python/baz/qux.py",
            "target": "src/python/baz:lib",
            "type": "python_library"
          }
        },
        {
          "id": "2",
          "data": {
            "path": "src/python/foo/bar.py",
            "target": "src/python/foo",
            "type": "python_library"
          }
        }
      ],
      "edges": [
        {
          "src_id": "1",
          "dep_id": "2",
          "data": {}
        },
        {
          "src_id": "2",
          "dep_id": "0",
          "data": {}
        }
      ]
    }"""
    )

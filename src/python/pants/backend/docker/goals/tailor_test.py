# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.docker.goals.tailor import PutativeDockerTargetsRequest
from pants.backend.docker.goals.tailor import rules as docker_tailor_rules
from pants.backend.docker.target_types import DockerImageTarget
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsSearchPaths,
)
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


def test_find_putative_targets() -> None:
    rule_runner = RuleRunner(
        rules=[
            *docker_tailor_rules(),
            QueryRule(PutativeTargets, [PutativeDockerTargetsRequest, AllOwnedSources]),
        ],
        target_types=[DockerImageTarget],
    )
    rule_runner.write_files({"src/docker_ok/Dockerfile": "", "src/docker_orphan/Dockerfile": ""})
    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativeDockerTargetsRequest(PutativeTargetsSearchPaths(("src/",))),
            AllOwnedSources(["src/docker_ok/Dockerfile"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    DockerImageTarget,
                    "src/docker_orphan",
                    "docker",
                    [],
                    kwargs={"name": "docker", "source": "Dockerfile"},
                ),
            ]
        )
        == pts
    )

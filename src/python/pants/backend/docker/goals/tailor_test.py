# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.docker.goals.tailor import PutativeDockerTargetsRequest
from pants.backend.docker.goals.tailor import rules as docker_tailor_rules
from pants.backend.docker.target_types import DockerImageTarget
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
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
    rule_runner.write_files(
        {
            "src/docker_ok/Dockerfile": "",
            "src/docker_orphan/Dockerfile": "",
            "src/docker_orphan/Dockerfile.two": "",
        }
    )
    pts = rule_runner.request(
        PutativeTargets,
        [
            PutativeDockerTargetsRequest(("src/docker_ok", "src/docker_orphan")),
            AllOwnedSources(["src/docker_ok/Dockerfile"]),
        ],
    )
    assert (
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    DockerImageTarget,
                    path="src/docker_orphan",
                    name="docker",
                    triggering_sources=["Dockerfile"],
                ),
                PutativeTarget.for_target_type(
                    DockerImageTarget,
                    path="src/docker_orphan",
                    name="docker",
                    triggering_sources=["Dockerfile.two"],
                    kwargs={"source": "Dockerfile.two"},
                ),
            ]
        )
        == pts
    )

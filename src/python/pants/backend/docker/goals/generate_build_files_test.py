# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.docker.goals import generate_build_files
from pants.backend.docker.goals.generate_build_files import PutativeDockerTargetsRequest
from pants.backend.docker.target_types import DockerImage
from pants.core.goals.generate_build_files import (
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
            *generate_build_files.rules(),
            QueryRule(PutativeTargets, [PutativeDockerTargetsRequest, AllOwnedSources]),
        ],
        target_types=[DockerImage],
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
                    DockerImage,
                    "src/docker_orphan",
                    "docker",
                    ["Dockerfile"],
                    kwargs={"name": "docker"},
                ),
            ]
        )
        == pts
    )

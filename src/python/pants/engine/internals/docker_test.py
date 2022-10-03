# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
import subprocess

import pytest

from pants.engine.internals.docker import DockerResolveImageRequest, DockerResolveImageResult
from pants.engine.platform import Platform
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(rules=[QueryRule(DockerResolveImageResult, (DockerResolveImageRequest,))])


def test_resolve_image_id(rule_runner: RuleRunner) -> None:
    platform = Platform.create_for_localhost()
    image_result = rule_runner.request(
        DockerResolveImageResult,
        [DockerResolveImageRequest(image_name="busybox:1", platform=platform.name)],
    )

    inspect_output = subprocess.check_output(["docker", "image", "inspect", "busybox:1"])
    expected_image_id = json.loads(inspect_output)[0]["Id"]

    assert image_result.image_id == expected_image_id

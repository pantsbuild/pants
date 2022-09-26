# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
import subprocess

import pytest

from pants.engine.internals.docker import DockerResolveImageRequest, DockerResolveImageResult
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(rules=[QueryRule(DockerResolveImageResult, (DockerResolveImageRequest,))])


def test_resolve_image_id(rule_runner: RuleRunner) -> None:
    subprocess.check_call(["docker", "pull", "busybox:1"])
    inspect_output = subprocess.check_output(["docker", "image", "inspect", "busybox:1"])
    image_id = json.loads(inspect_output)[0]["Id"]

    image_result = rule_runner.request(
        DockerResolveImageResult, [DockerResolveImageRequest("busybox:1")]
    )
    assert image_result.image_id == image_id

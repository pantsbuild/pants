# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.docker.docker_binary import DockerBinary, DockerBinaryRequest
from pants.backend.docker.docker_build import DockerFieldSet, build_docker_image
from pants.backend.docker.docker_build_context import DockerBuildContext, DockerBuildContextRequest
from pants.backend.docker.target_types import DockerImage
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, EMPTY_FILE_DIGEST, EMPTY_SNAPSHOT, Digest, Snapshot
from pants.engine.process import Process, ProcessResult
from pants.testutil.rule_runner import MockGet, run_rule_with_mocks


@pytest.mark.parametrize(
    "target_values, expected_features",
    [
        (
            dict(),
            dict(
                context_root="docker/test/.",
            ),
        ),
        (
            dict(
                version="1.2.3",
            ),
            dict(
                version="1.2.3",
            ),
        ),
        (
            dict(
                context_root="/",
            ),
            dict(
                context_root=".",
            ),
        ),
        (
            dict(
                context_root="foo/bar",
            ),
            dict(
                context_root="docker/test/foo/bar",
            ),
        ),
        (
            dict(
                context_root="/foo/bar",
            ),
            dict(
                context_root="foo/bar",
            ),
        ),
    ],
)
def test_build_docker_image_rule(target_values, expected_features):
    address = Address("docker/test", target_name="image")
    image = DockerImage(
        address=address,
        unhydrated_values=target_values,
    )
    field_set = DockerFieldSet.create(image)

    def build_context_mock(request: DockerBuildContextRequest) -> DockerBuildContext:
        if "context_root" in expected_features:
            assert expected_features["context_root"] == request.context_root

        return DockerBuildContext(digest=EMPTY_DIGEST)

    result = run_rule_with_mocks(
        build_docker_image,
        rule_args=[field_set],
        mock_gets=[
            MockGet(
                output_type=DockerBinary,
                input_type=DockerBinaryRequest,
                mock=lambda _: DockerBinary("/dummy/docker"),
            ),
            MockGet(
                output_type=DockerBuildContext,
                input_type=DockerBuildContextRequest,
                mock=build_context_mock,
            ),
            MockGet(
                output_type=Snapshot,
                input_type=Digest,
                mock=lambda _: EMPTY_SNAPSHOT,
            ),
            MockGet(
                output_type=ProcessResult,
                input_type=Process,
                # Process() generation has its own tests in test_docker_binary_build_image
                mock=lambda _: ProcessResult(
                    stdout=b"stdout",
                    stdout_digest=EMPTY_FILE_DIGEST,
                    stderr=b"stderr",
                    stderr_digest=EMPTY_FILE_DIGEST,
                    output_digest=EMPTY_DIGEST,
                ),
            ),
        ],
    )

    assert result.digest == EMPTY_DIGEST
    assert len(result.artifacts) == 1
    assert result.artifacts[0].relpath is None

    version = expected_features.get("version", "latest")
    assert f"Built docker image: image:{version}" in result.artifacts[0].extra_log_lines

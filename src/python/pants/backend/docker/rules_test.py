# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from hashlib import sha256
from os import path

import pytest

from pants.backend.docker.rules import DockerFieldSet, build_docker_image
from pants.backend.docker.rules_binary import DockerBinary, DockerBinaryRequest
from pants.backend.docker.rules_context import (
    DockerBuildContext,
    DockerBuildContextRequest,
    create_docker_build_context,
)
from pants.backend.docker.target_types import DockerImage
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import (
    EMPTY_DIGEST,
    EMPTY_FILE_DIGEST,
    EMPTY_SNAPSHOT,
    AddPrefix,
    Digest,
    MergeDigests,
    Snapshot,
)
from pants.engine.process import Process, ProcessResult
from pants.engine.target import (
    DependenciesRequest,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionMembership
from pants.testutil.rule_runner import MockGet, run_rule_with_mocks
from pants.util.ordered_set import FrozenOrderedSet


def test_docker_binary_build_image():
    source_path = "src/test/repo"
    docker_path = "/bin/docker"
    dockerfile = path.join(source_path, "Dockerfile")
    docker = DockerBinary(docker_path)
    digest = Digest(sha256().hexdigest(), 123)
    tag = "test:latest"
    build_request = docker.build_image(tag, digest, source_path, dockerfile)

    assert build_request == Process(
        argv=(docker_path, "build", "-t", tag, "-f", dockerfile, source_path),
        input_digest=digest,
        description=f"Building docker image {tag}",
    )


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
    targets = {address: TransitiveTargets(roots=(image,), dependencies=FrozenOrderedSet())}
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
                output_type=TransitiveTargets,
                input_type=TransitiveTargetsRequest,
                mock=lambda request: targets[request.roots[0]],
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


def test_create_docker_build_context():
    tgt = DockerImage(address=Address("src/test", target_name="image"), unhydrated_values={})
    request = DockerBuildContextRequest(
        address=Address("src/test", target_name="image"), context_root=".", targets=Targets([tgt])
    )

    result = run_rule_with_mocks(
        create_docker_build_context,
        rule_args=[request],
        mock_gets=[
            MockGet(
                output_type=SourceFiles,
                input_type=SourceFilesRequest,
                mock=lambda _: SourceFiles(
                    snapshot=EMPTY_SNAPSHOT,
                    unrooted_files=tuple(),
                ),
            ),
            MockGet(
                output_type=Targets,
                input_type=DependenciesRequest,
                mock=lambda _: Targets([]),
            ),
            MockGet(
                output_type=FieldSetsPerTarget,
                input_type=FieldSetsPerTargetRequest,
                mock=lambda request: FieldSetsPerTarget([[DockerFieldSet.create(tgt)]]),
            ),
            MockGet(
                output_type=BuiltPackage,
                input_type=PackageFieldSet,
                mock=lambda _: BuiltPackage(EMPTY_DIGEST, []),
            ),
            MockGet(
                output_type=Digest,
                input_type=AddPrefix,
                mock=lambda _: EMPTY_DIGEST,
            ),
            MockGet(
                output_type=Digest,
                input_type=MergeDigests,
                mock=lambda _: EMPTY_DIGEST,
            ),
        ],
        # need AddPrefix here, since UnionMembership.is_member() throws when called with non
        # registered types
        union_membership=UnionMembership({PackageFieldSet: [DockerFieldSet], AddPrefix: []}),
    )

    assert result.digest == EMPTY_DIGEST

# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent

import pytest

from pants.backend.docker.target_types import (
    DockerImageInstructionsField,
    DockerImageRepositoryField,
    DockerImageTagsField,
    DockerMirrorImagesTarget,
)
from pants.backend.docker.util_rules.mirror_images import (
    GenerateTargetsFromDockerMirrorImages,
    rules,
)
from pants.core.util_rules import source_files
from pants.engine.addresses import Address
from pants.engine.target import Dependencies, GeneratedTargets, Tags
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *rules(),
            *source_files.rules(),
            QueryRule(GeneratedTargets, [GenerateTargetsFromDockerMirrorImages]),
        ],
        target_types=[DockerMirrorImagesTarget],
    )


def assert_target(tgt, *field_values) -> None:
    for field, value in field_values:
        assert (
            tgt[field].value == value
        ), f"{tgt.address} {field.alias} expected {value!r} got {tgt[field].value!r}."


def test_generate_mirror_docker_image_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                docker_mirror_images(
                  name="mirror",
                  sources=["*.txt"],
                  overrides={
                    "publish/me": {
                      "tags": ["publish-release"],
                      "image_tags": ["2.3-4"],
                    },
                    "stage-name": {
                      "tags": ["named"],
                    },
                  },
                )
                """
            ),
            "src/images.txt": dedent(
                """\
                repo/name:1.0
                --platform=arch custom.registry:443/lib:v3 as stage-name
                publish/me:2.3
                registry.io/proj/name:tag
                """
            ),
            "src/other.txt": dedent(
                """\
                other/name@sha256:702361c0595019a5a6104d032970d4e3924b2b4498fb91bf56eb4ce34553bc1d
                """
            ),
        }
    )
    addr = Address("src", target_name="mirror")
    tgt = rule_runner.get_target(addr)
    generated = rule_runner.request(
        GeneratedTargets, [GenerateTargetsFromDockerMirrorImages(tgt, addr, dict(), dict())]
    )
    assert {str(addr) for addr in generated.keys()} == {
        "src/images.txt:mirror",
        "src:mirror#repo/name",
        "src:mirror#stage-name",
        "src:mirror#publish/me",
        "src:mirror#registry.io/proj/name",
        "src/other.txt:mirror",
        "src:mirror#other/name",
    }
    assert_target(
        generated[addr.create_generated("repo/name")],
        (DockerImageRepositoryField, "repo/name"),
        (DockerImageTagsField, ("1.0",)),
        (DockerImageInstructionsField, ("FROM repo/name:1.0",)),
        (Dependencies, ("src/images.txt:mirror",)),
        (Tags, ("docker-mirror",)),
    )
    assert_target(
        generated[addr.create_generated("stage-name")],
        (DockerImageRepositoryField, "lib"),
        (DockerImageTagsField, ("v3",)),
        (Dependencies, ("src/images.txt:mirror",)),
        (
            DockerImageInstructionsField,
            ("FROM --platform=arch custom.registry:443/lib:v3 AS stage-name",),
        ),
        (
            Tags,
            (
                "docker-mirror",
                "named",
            ),
        ),
    )
    assert_target(
        generated[addr.create_generated("publish/me")],
        (DockerImageRepositoryField, "publish/me"),
        (DockerImageTagsField, ("2.3-4",)),
        (DockerImageInstructionsField, ("FROM publish/me:2.3",)),
        (Dependencies, ("src/images.txt:mirror",)),
        (
            Tags,
            (
                "docker-mirror",
                "publish-release",
            ),
        ),
    )
    assert_target(
        generated[addr.create_generated("registry.io/proj/name")],
        (DockerImageRepositoryField, "proj/name"),
        (DockerImageTagsField, ("tag",)),
        (DockerImageInstructionsField, ("FROM registry.io/proj/name:tag",)),
        (Dependencies, ("src/images.txt:mirror",)),
        (Tags, ("docker-mirror",)),
    )
    assert_target(
        generated[addr.create_generated("other/name")],
        (DockerImageRepositoryField, "other/name"),
        (
            DockerImageTagsField,
            ("702361c0595019a5a6104d032970d4e3924b2b4498fb91bf56eb4ce34553bc1d",),
        ),
        (
            DockerImageInstructionsField,
            (
                "FROM other/name@sha256:702361c0595019a5a6104d032970d4e3924b2b4498fb91bf56eb4ce34553bc1d",
            ),
        ),
        (Dependencies, ("src/other.txt:mirror",)),
        (Tags, ("docker-mirror",)),
    )


def test_multiple_versions_of_same_image(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/mirror/BUILD": "docker_mirror_images(sources=['*.txt'])",
            "src/mirror/images.txt": dedent(
                """\
                repo/name:1.0
                repo/name:1.1
                repo/name:1.2
                """
            ),
        }
    )
    addr = Address("src/mirror")
    tgt = rule_runner.get_target(addr)
    generated = rule_runner.request(
        GeneratedTargets, [GenerateTargetsFromDockerMirrorImages(tgt, addr, dict(), dict())]
    )
    assert {str(addr) for addr in generated.keys()} == {
        "src/mirror/images.txt",
        "src/mirror#repo/name",
        "src/mirror#repo/name_1",
        "src/mirror#repo/name_2",
    }
    assert_target(
        generated[addr.create_generated("repo/name")],
        (DockerImageRepositoryField, "repo/name"),
        (DockerImageTagsField, ("1.0",)),
        (DockerImageInstructionsField, ("FROM repo/name:1.0",)),
        (Dependencies, ("src/mirror/images.txt",)),
        (Tags, ("docker-mirror",)),
    )
    assert_target(
        generated[addr.create_generated("repo/name_1")],
        (DockerImageRepositoryField, "repo/name"),
        (DockerImageTagsField, ("1.1",)),
        (DockerImageInstructionsField, ("FROM repo/name:1.1",)),
        (Dependencies, ("src/mirror/images.txt",)),
        (Tags, ("docker-mirror",)),
    )
    assert_target(
        generated[addr.create_generated("repo/name_2")],
        (DockerImageRepositoryField, "repo/name"),
        (DockerImageTagsField, ("1.2",)),
        (DockerImageInstructionsField, ("FROM repo/name:1.2",)),
        (Dependencies, ("src/mirror/images.txt",)),
        (Tags, ("docker-mirror",)),
    )


def test_image_with_tag_and_digest(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/mirror/BUILD": "docker_mirror_images(sources=['*.txt'])",
            "src/mirror/images.txt": (
                "gcr.io/tekton-releases/github.com/tektoncd/operator/cmd/kubernetes/operator:"
                "v0.54.0@sha256:d1f0463b35135852308ea815c2ae54c1734b876d90288ce35828aeeff9899f9d"
            ),
        }
    )
    addr = Address("src/mirror")
    tgt = rule_runner.get_target(addr)
    generated = rule_runner.request(
        GeneratedTargets, [GenerateTargetsFromDockerMirrorImages(tgt, addr, dict(), dict())]
    )
    assert {str(addr) for addr in generated.keys()} == {
        "src/mirror/images.txt",
        "src/mirror#gcr.io/tekton-releases/github.com/tektoncd/operator/cmd/kubernetes/operator",
    }
    assert_target(
        generated[
            addr.create_generated(
                "gcr.io/tekton-releases/github.com/tektoncd/operator/cmd/kubernetes/operator"
            )
        ],
        (
            DockerImageRepositoryField,
            "tekton-releases/github.com/tektoncd/operator/cmd/kubernetes/operator",
        ),
        (DockerImageTagsField, ("v0.54.0",)),
        (
            DockerImageInstructionsField,
            (
                "FROM gcr.io/tekton-releases/github.com/tektoncd/operator/cmd/kubernetes/operator:"
                "v0.54.0@sha256:d1f0463b35135852308ea815c2ae54c1734b876d90288ce35828aeeff9899f9d",
            ),
        ),
        (Dependencies, ("src/mirror/images.txt",)),
        (Tags, ("docker-mirror",)),
    )

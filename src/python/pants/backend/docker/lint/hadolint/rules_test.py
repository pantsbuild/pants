# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.docker.lint.hadolint.rules import _group_files_with_config


@pytest.mark.parametrize(
    "source_files, config_files, config_files_discovered, expected",
    [
        (
            {"a/Dockerfile", "b/Dockerfile"},
            ("a/.hadolint.yaml",),
            True,
            [
                (("a/Dockerfile",), ["--config", "a/.hadolint.yaml"]),
                (("b/Dockerfile",), []),
            ],
        ),
        (
            {"a/Dockerfile", "b/Dockerfile"},
            ("hadolint.yaml",),
            False,
            [
                (("a/Dockerfile", "b/Dockerfile"), ["--config", "hadolint.yaml"]),
            ],
        ),
        (
            {"a/Dockerfile", "aa/Dockerfile"},
            ("a/.hadolint.yaml",),
            True,
            [
                (("a/Dockerfile",), ["--config", "a/.hadolint.yaml"]),
                (("aa/Dockerfile",), []),
            ],
        ),
        (
            {"a/Dockerfile", "b/Dockerfile", "c/Dockerfile", "d/Dockerfile", "c/e/Dockerfile"},
            ("a/.hadolint.yaml", "c/.hadolint.yaml"),
            True,
            [
                (("a/Dockerfile",), ["--config", "a/.hadolint.yaml"]),
                (
                    (
                        "c/Dockerfile",
                        "c/e/Dockerfile",
                    ),
                    ["--config", "c/.hadolint.yaml"],
                ),
                (
                    (
                        "b/Dockerfile",
                        "d/Dockerfile",
                    ),
                    [],
                ),
            ],
        ),
    ],
)
def test_group_files_with_config(source_files, config_files, config_files_discovered, expected):
    actual = _group_files_with_config(source_files, config_files, config_files_discovered)
    assert actual == expected

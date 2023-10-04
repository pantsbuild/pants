# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

import pytest

from pants.build_graph.address import Address
from pants.core.util_rules import search_paths
from pants.core.util_rules.asdf import AsdfPathString
from pants.core.util_rules.environments import (
    DockerEnvironmentTarget,
    DockerImageField,
    EnvironmentTarget,
    LocalEnvironmentTarget,
    RemoteEnvironmentTarget,
)
from pants.core.util_rules.search_paths import (
    ValidateSearchPathsRequest,
    VersionManagerSearchPaths,
    VersionManagerSearchPathsRequest,
    validate_search_paths,
)
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner, run_rule_with_mocks
from pants.util.contextutil import temporary_dir
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *search_paths.rules(),
            QueryRule(VersionManagerSearchPaths, (VersionManagerSearchPathsRequest,)),
        ],
    )


@pytest.mark.parametrize(
    ("env_tgt_type", "search_paths", "is_default", "expected"),
    (
        (LocalEnvironmentTarget, ("<PYENV>",), False, ("<PYENV>",)),
        (LocalEnvironmentTarget, ("<ASDF>",), False, ("<ASDF>",)),
        (
            LocalEnvironmentTarget,
            ("<ASDF_LOCAL>", "/home/derryn/pythons"),
            False,
            ("<ASDF_LOCAL>", "/home/derryn/pythons"),
        ),
        (DockerEnvironmentTarget, ("<PYENV>", "<PATH>"), True, ("<PATH>",)),
        (DockerEnvironmentTarget, ("<PYENV>", "<PATH>"), False, ValueError),
        (DockerEnvironmentTarget, ("<PYENV>", "<PATH>"), False, ValueError),
        (
            DockerEnvironmentTarget,
            ("<ASDF>", "/home/derryn/pythons"),
            False,
            ValueError,
        ),  # Contains a banned special-string
        (DockerEnvironmentTarget, ("<ASDF_LOCAL>",), False, ValueError),
        (DockerEnvironmentTarget, ("<PYENV_LOCAL>",), False, ValueError),
        (DockerEnvironmentTarget, ("<PEXRC>",), False, ValueError),
        (DockerEnvironmentTarget, ("<PATH>",), False, ("<PATH>",)),
        (
            DockerEnvironmentTarget,
            ("<PATH>", "/home/derryn/pythons"),
            False,
            ("<PATH>", "/home/derryn/pythons"),
        ),
        (RemoteEnvironmentTarget, ("<PYENV>", "<PATH>"), True, ("<PATH>",)),
        (RemoteEnvironmentTarget, ("<PYENV>", "<PATH>"), False, ValueError),
        (RemoteEnvironmentTarget, ("<PYENV>", "<PATH>"), False, ValueError),
        (
            RemoteEnvironmentTarget,
            ("<ASDF>", "/home/derryn/pythons"),
            False,
            ValueError,
        ),  # Contains a banned special-string
        (RemoteEnvironmentTarget, ("<ASDF_LOCAL>",), False, ValueError),
        (RemoteEnvironmentTarget, ("<PYENV_LOCAL>",), False, ValueError),
        (RemoteEnvironmentTarget, ("<PEXRC>",), False, ValueError),
        (RemoteEnvironmentTarget, ("<PATH>",), False, ("<PATH>",)),
        (
            RemoteEnvironmentTarget,
            ("<PATH>", "/home/derryn/pythons"),
            False,
            ("<PATH>", "/home/derryn/pythons"),
        ),
    ),
)
def test_validated_search_paths(
    env_tgt_type: type[LocalEnvironmentTarget]
    | type[DockerEnvironmentTarget]
    | type[RemoteEnvironmentTarget],
    search_paths: tuple[str],
    is_default: bool,
    expected: tuple[str] | type[ValueError],
):
    extra_kwargs: dict = {}
    if env_tgt_type is DockerEnvironmentTarget:
        extra_kwargs = {
            DockerImageField.alias: "my_img",
        }
    env_name = "name"
    env_tgt = EnvironmentTarget(env_name, env_tgt_type(extra_kwargs, address=Address("flem")))
    local_only = FrozenOrderedSet(
        {
            "<PYENV>",
            "<PYENV_LOCAL>",
            AsdfPathString.STANDARD,
            AsdfPathString.LOCAL,
            "<PEXRC>",
        }
    )

    if expected is not ValueError:
        assert expected == tuple(
            run_rule_with_mocks(
                validate_search_paths,
                rule_args=[
                    ValidateSearchPathsRequest(
                        env_tgt, search_paths, "[mock].opt", "mock_opt", is_default, local_only
                    )
                ],
            )
        )
    else:
        with pytest.raises(ValueError):
            run_rule_with_mocks(
                validate_search_paths,
                rule_args=[
                    ValidateSearchPathsRequest(
                        env_tgt, search_paths, "[mock].opt", "mock_opt", is_default, local_only
                    )
                ],
            )


@contextmanager
def fake_tool_root(
    fake_versions: list[str], fake_local_version: str
) -> Generator[tuple[str, tuple[str, ...], tuple[str]], None, None]:
    with temporary_dir() as tool_root:
        fake_version_dirs = tuple(
            os.path.join(tool_root, "versions", v, "bin") for v in fake_versions
        )
        for d in fake_version_dirs:
            os.makedirs(d)
        fake_local_version_dirs = (os.path.join(tool_root, "versions", fake_local_version, "bin"),)
        yield tool_root, fake_version_dirs, fake_local_version_dirs


def test_get_local_tool_paths(rule_runner: RuleRunner) -> None:
    local_version = "3.5.5"
    all_versions = ["2.7.14", local_version]
    rule_runner.write_files({".version-file": f"{local_version}\n"})
    with fake_tool_root(all_versions, local_version) as (
        tool_root,
        expected_paths,
        expected_local_paths,
    ):
        env_name = "name"
        tgt = EnvironmentTarget(env_name, LocalEnvironmentTarget({}, Address("flem")))
        paths = rule_runner.request(
            VersionManagerSearchPaths,
            [
                VersionManagerSearchPathsRequest(
                    tgt, tool_root, "versions", "[mock].search_path", (".version-file",), None
                )
            ],
        )
        local_paths = rule_runner.request(
            VersionManagerSearchPaths,
            [
                VersionManagerSearchPathsRequest(
                    tgt,
                    tool_root,
                    "versions",
                    "[mock].search_path",
                    (".version-file",),
                    "<TOOL_LOCAL>",
                )
            ],
        )
    assert set(expected_paths) == set(paths)
    assert set(expected_local_paths) == set(local_paths)

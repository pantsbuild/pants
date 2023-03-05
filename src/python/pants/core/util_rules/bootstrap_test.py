# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import pytest

from pants.build_graph.address import Address
from pants.core.util_rules.asdf import AsdfPathString
from pants.core.util_rules.bootstrap import ValidateSearchPathsRequest, validate_search_paths
from pants.core.util_rules.environments import (
    DockerEnvironmentTarget,
    DockerImageField,
    EnvironmentTarget,
    LocalEnvironmentTarget,
    RemoteEnvironmentTarget,
)
from pants.testutil.rule_runner import run_rule_with_mocks
from pants.util.ordered_set import FrozenOrderedSet


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
def test_preprocessed_interpreter_search_paths(
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
    env_tgt = EnvironmentTarget(env_tgt_type(extra_kwargs, address=Address("flem")))
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

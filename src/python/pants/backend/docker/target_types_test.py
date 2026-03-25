# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.target_types import DockerImageBuildSecretsOptionField
from pants.engine.internals.native_engine import Address


@pytest.mark.parametrize(
    "src, expected",
    [
        (
            "/absolute/path",
            "/absolute/path",
        ),
        (
            "./relative/path",
            str(Path.cwd().joinpath("./relative/path")),
        ),
        (
            "~/home/path",
            os.path.expanduser("~/home/path"),
        ),
    ],
    ids=[
        "absolute_path",
        "relative_path",
        "homedir_path",
    ],
)
def test_secret_path_resolvement(src: str, expected: str):
    Path.cwd().joinpath("pants.toml").write_text("")
    secrets_option_field = DockerImageBuildSecretsOptionField(
        {"mysecret": src}, address=Address("")
    )
    values = list(
        secrets_option_field.buildctl_options(
            docker=MagicMock(spec=DockerOptions), value_formatter=lambda x: x
        )
    )

    assert values == ["--secret", f"id=mysecret,src={expected}"]

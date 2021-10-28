# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import pytest

from pants.backend.docker.target_types import DockerImageSourceField
from pants.engine.addresses import Address
from pants.engine.target import InvalidFieldException
from pants.testutil.pytest_util import no_exception


@pytest.mark.parametrize(
    "files, expect",
    [
        (["Dockerfile"], no_exception()),
        (
            [],
            pytest.raises(
                InvalidFieldException,
                match=(
                    r"The 'source' field in target test:test must have 1 file, but it had 0 files\."
                ),
            ),
        ),
        (
            ["a/Dockerfile", "b/Dockerfile"],
            pytest.raises(
                InvalidFieldException,
                match=(
                    r"The 'source' field in target test:test must have 1 file, but it had 2 files\."
                    r"\n\n"
                    r"This may happen if you use a source glob that matches multiple Dockerfiles, "
                    r"and/or depend on one or more `dockerfile` targets."
                ),
            ),
        ),
    ],
)
def test_dockerfile_validation(files, expect) -> None:
    field = DockerImageSourceField(None, Address("test"))

    # Default is to defer validation
    field.validate_resolved_files(files)

    with expect:
        field.validate_resolved_files(files, defer_validation=False)

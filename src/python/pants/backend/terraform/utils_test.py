# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import pytest

from pants.backend.terraform.utils import terraform_relpath


@pytest.mark.parametrize(
    "chdir, target, expected_result",
    [
        pytest.param(
            "path/to/deployment",
            "path/to/deployment/file.txt",
            "file.txt",
            id="file_in_same_directory",
        ),
        pytest.param(
            "path/to/deployment",
            "path/to/other/file.txt",
            "../other/file.txt",
            id="file_in_different_directory",
        ),
        pytest.param(
            "path/to/deployment",
            "path/to/deployment/subdir/file.txt",
            "subdir/file.txt",
            id="file_in_subdirectory",
        ),
        pytest.param(
            "path/to/deployment/subdir",
            "path/to/deployment/file.txt",
            "../file.txt",
            id="file_in_parent_directory",
        ),
    ],
)
def test_terraform_relpath(chdir: str, target: str, expected_result: str):
    result = terraform_relpath(chdir, target)
    assert result == expected_result

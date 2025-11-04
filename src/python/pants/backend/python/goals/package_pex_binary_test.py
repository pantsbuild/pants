# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.goals.package_pex_binary import (
    _scie_output_directories,
    _scie_output_filenames,
)
from pants.backend.python.target_types import (
    PexScieHashAlgField,
    PexScieNameStyleField,
    PexSciePlatformField,
    ScieNameStyle,
)


def test_files_default():
    example = "helloworld/example_pex"
    assert (example,) == _scie_output_filenames(
        example,
        PexScieNameStyleField.default,
        PexSciePlatformField.default,
        PexScieHashAlgField.default,
    )


def test_files_default_with_hash():
    example = "helloworld/example_pex"
    assert (example, example + ".md5") == _scie_output_filenames(
        example, PexScieNameStyleField.default, PexSciePlatformField.default, "md5"
    )


def test_files_parent_dir():
    example = "helloworld/example_pex"
    assert (
        _scie_output_filenames(
            example,
            ScieNameStyle.PLATFORM_PARENT_DIR,
            ["linux-aarch64", "linux-armv7l", "linux-powerpc64"],
            "sha256",
        )
        is None
    )


def test_files_platform_suffix():
    assert ("foo/bar-linux-aarch64", "foo/bar-linux-x86_64") == _scie_output_filenames(
        "foo/bar",
        ScieNameStyle.PLATFORM_FILE_SUFFIX,
        ["linux-aarch64", "linux-x86_64"],
        PexScieHashAlgField.default,
    )


def test_files_platform_suffix_hash():
    assert (
        "foo/bar-linux-aarch64",
        "foo/bar-linux-aarch64.sha256",
        "foo/bar-linux-x86_64",
        "foo/bar-linux-x86_64.sha256",
    ) == _scie_output_filenames(
        "foo/bar", ScieNameStyle.PLATFORM_FILE_SUFFIX, ["linux-aarch64", "linux-x86_64"], "sha256"
    )


def test_dirs_default():
    example = "helloworld/example_pex"
    assert (
        _scie_output_directories(
            example, PexScieNameStyleField.default, PexSciePlatformField.default
        )
        is None
    )


def test_dirs_platform_no_change():
    example = "helloworld/example_pex"
    assert (
        _scie_output_directories(
            example, PexScieNameStyleField.default, ["linux-aarch64", "linux-x86_64"]
        )
        is None
    )


def test_dirs_platform_parent_dir():
    example = "helloworld/example_pex"
    assert ("helloworld/linux-aarch64", "helloworld/linux-x86_64") == _scie_output_directories(
        example, ScieNameStyle.PLATFORM_PARENT_DIR, ["linux-aarch64", "linux-x86_64"]
    )

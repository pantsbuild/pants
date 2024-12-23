# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python.providers.python_build_standalone.rules import (
    _parse_from_five_fields,
    _parse_from_three_fields,
    _parse_pbs_url,
    _parse_py_version_and_pbs_release_tag,
    _ParsedPBSPython,
)
from pants.core.util_rules.external_tool import ExternalToolError
from pants.engine.platform import Platform
from pants.version import Version


def test_parse_py_version_and_pbs_release_tag() -> None:
    result1 = _parse_py_version_and_pbs_release_tag("")
    assert result1 == (None, None)

    result2 = _parse_py_version_and_pbs_release_tag("1.2.3")
    assert result2 == (Version("1.2.3"), None)

    result3 = _parse_py_version_and_pbs_release_tag("1.2.3+20241201")
    assert result3 == (Version("1.2.3"), Version("20241201"))

    with pytest.raises(ValueError):
        _parse_py_version_and_pbs_release_tag("xyzzy+20241201")

    with pytest.raises(ValueError):
        _parse_py_version_and_pbs_release_tag("1.2.3+xyzzy")


def test_parse_pbs_url() -> None:
    result1 = _parse_pbs_url(
        "https://github.com/indygreg/python-build-standalone/releases/download/20240726/cpython-3.12.4%2B20240726-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
    )
    assert result1 == (Version("3.12.4"), Version("20240726"), Platform.linux_x86_64)

    with pytest.raises(ValueError, match="Unable to parse the Python version and PBS release tag"):
        _parse_pbs_url(
            "https://example.com/cpython-3.12.4-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
        )

    with pytest.raises(ValueError, match="Unable to parse the platform"):
        _parse_pbs_url(
            "https://example.com/cpython-3.12.4%2B20240205-s390-unknown-linux-gnu-install_only_stripped.tar.gz"
        )


def test_parse_from_three_fields() -> None:
    def invoke(s: str) -> _ParsedPBSPython:
        parts = s.split("|")
        return _parse_from_three_fields(parts, orig_value=s)

    result1 = invoke(
        "https://github.com/indygreg/python-build-standalone/releases/download/20221220/cpython-3.9.16%2B20221220-x86_64-unknown-linux-gnu-install_only.tar.gz|f885f3d011ab08e4d9521a7ae2662e9e0073acc0305a1178984b5a1cf057309a|26767987"
    )
    assert result1 == _ParsedPBSPython(
        py_version=Version("3.9.16"),
        pbs_release_tag=Version("20221220"),
        platform=Platform.linux_x86_64,
        url="https://github.com/indygreg/python-build-standalone/releases/download/20221220/cpython-3.9.16%2B20221220-x86_64-unknown-linux-gnu-install_only.tar.gz",
        sha256="f885f3d011ab08e4d9521a7ae2662e9e0073acc0305a1178984b5a1cf057309a",
        size=26767987,
    )

    with pytest.raises(ExternalToolError, match="since it does not have a cpython prefix"):
        invoke(
            "https://dl.example.com/cpython.tar.gz|f885f3d011ab08e4d9521a7ae2662e9e0073acc0305a1178984b5a1cf057309a|26767987"
        )


def test_parse_from_five_fields() -> None:
    def invoke(s: str) -> _ParsedPBSPython:
        parts = s.split("|")
        return _parse_from_five_fields(parts, orig_value=s)

    result1 = invoke(
        "3.9.16|linux_x86_64|f885f3d011ab08e4d9521a7ae2662e9e0073acc0305a1178984b5a1cf057309a|26767987|https://github.com/indygreg/python-build-standalone/releases/download/20221220/cpython-3.9.16%2B20221220-x86_64-unknown-linux-gnu-install_only.tar.gz"
    )
    assert result1 == _ParsedPBSPython(
        py_version=Version("3.9.16"),
        pbs_release_tag=Version("20221220"),
        platform=Platform.linux_x86_64,
        url="https://github.com/indygreg/python-build-standalone/releases/download/20221220/cpython-3.9.16%2B20221220-x86_64-unknown-linux-gnu-install_only.tar.gz",
        sha256="f885f3d011ab08e4d9521a7ae2662e9e0073acc0305a1178984b5a1cf057309a",
        size=26767987,
    )

    with pytest.raises(
        ExternalToolError,
        match="does not declare a version in the first field, and no version could be inferred from the URL",
    ):
        invoke(
            "||e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855|123|https://dl.example.com/cpython.tar.gz"
        )

    with pytest.raises(
        ExternalToolError,
        match="does not declare a PBS release tag in the first field, and no PBS release tag could be inferred from the URL",
    ):
        invoke(
            "3.10.1||e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855|123|https://dl.example.com/cpython.tar.gz"
        )

    with pytest.raises(
        ExternalToolError,
        match="does not declare a platform in the second field, and no platform could be inferred from the URL",
    ):
        invoke(
            "3.10.1+20240601||e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855|123|https://dl.example.com/cpython.tar.gz"
        )

    result2 = invoke(
        "3.10.1+20240601|linux_x86_64|e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855|123|https://dl.example.com/cpython.tar.gz"
    )
    assert result2 == _ParsedPBSPython(
        py_version=Version("3.10.1"),
        pbs_release_tag=Version("20240601"),
        platform=Platform.linux_x86_64,
        url="https://dl.example.com/cpython.tar.gz",
        sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        size=123,
    )

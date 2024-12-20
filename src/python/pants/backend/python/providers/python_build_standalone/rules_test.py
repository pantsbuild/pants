# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python.providers.python_build_standalone.rules import (
    _parse_pbs_url,
    _parse_py_version_and_pbs_release_tag,
)
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

    with pytest.raises(ValueError, match="Unable to parse the platfornm"):
        _parse_pbs_url(
            "https://example.com/cpython-3.12.4%2B20240205-s390-unknown-linux-gnu-install_only_stripped.tar.gz"
        )

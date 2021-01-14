# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

import pytest

from pants.core.util_rules.distdir import DistDir, InvalidDistDir, is_child_of, validate_distdir


def test_distdir() -> None:
    buildroot = Path("/buildroot")
    assert DistDir(relpath=Path("dist")) == validate_distdir(Path("dist"), buildroot)
    assert DistDir(relpath=Path("dist")) == validate_distdir(Path("/buildroot/dist"), buildroot)
    with pytest.raises(InvalidDistDir):
        validate_distdir(Path("/other/dist"), buildroot)


def test_is_child_of() -> None:
    mock_build_root = Path("/mock/build/root")

    assert is_child_of(Path("/mock/build/root/dist/dir"), mock_build_root)
    assert is_child_of(Path("dist/dir"), mock_build_root)
    assert is_child_of(Path("./dist/dir"), mock_build_root)
    assert is_child_of(Path("../root/dist/dir"), mock_build_root)
    assert is_child_of(Path(""), mock_build_root)
    assert is_child_of(Path("./"), mock_build_root)

    assert not is_child_of(Path("/other/random/directory/root/dist/dir"), mock_build_root)
    assert not is_child_of(Path("../not_root/dist/dir"), mock_build_root)

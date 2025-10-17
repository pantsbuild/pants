# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

from pants.core.util_rules.distdir import DistDir, is_child_of, normalize_distdir


def test_distdir() -> None:
    buildroot = Path("/buildroot")
    assert DistDir(relpath=Path("/buildroot/dist")) == normalize_distdir(Path("dist"), buildroot)
    assert DistDir(relpath=Path("/buildroot/dist")) == normalize_distdir(
        Path("/buildroot/dist"), buildroot
    )
    assert DistDir(relpath=Path("/other/dist")) == normalize_distdir(Path("/other/dist"), buildroot)


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

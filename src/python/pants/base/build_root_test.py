# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from collections.abc import Generator

import pytest

from pants.base.build_root import BuildRoot
from pants.util.contextutil import environment_as, pushd, temporary_dir
from pants.util.dirutil import safe_mkdir, safe_mkdtemp, safe_rmtree, touch


@pytest.fixture
def tmp_build_root() -> Generator[tuple[BuildRoot, str, str]]:
    build_root = BuildRoot()
    original_path = build_root.path
    new_path = os.path.realpath(safe_mkdtemp())
    build_root.reset()
    yield (build_root, original_path, new_path)
    build_root.reset()
    safe_rmtree(new_path)


def test_via_set(tmp_build_root) -> None:
    build_root, _, new_path = tmp_build_root
    build_root.path = new_path
    assert new_path == build_root.path


def test_reset(tmp_build_root) -> None:
    build_root, original_path, new_path = tmp_build_root
    build_root.path = new_path
    build_root.reset()
    assert original_path == build_root.path


def test_via_pants_runner(tmp_build_root) -> None:
    build_root, _, _ = tmp_build_root
    with temporary_dir() as root:
        root = os.path.realpath(root)
        touch(os.path.join(root, "BUILD_ROOT"))
        with pushd(root):
            assert root == build_root.path

        build_root.reset()
        child = os.path.join(root, "one", "two")
        safe_mkdir(child)
        with pushd(child):
            assert root == build_root.path


def test_temporary(tmp_build_root) -> None:
    build_root, original_path, new_path = tmp_build_root
    with build_root.temporary(new_path):
        assert new_path == build_root.path
    assert original_path == build_root.path


def test_singleton(tmp_build_root) -> None:
    _, _, new_path = tmp_build_root
    assert BuildRoot().path == BuildRoot().path
    BuildRoot().path = new_path
    assert BuildRoot().path == BuildRoot().path


def test_not_found(tmp_build_root) -> None:
    build_root, _, _ = tmp_build_root
    with temporary_dir() as root:
        root = os.path.realpath(root)
        with pushd(root):
            with pytest.raises(BuildRoot.NotFoundError):
                build_root.path


def test_buildroot_override(tmp_build_root) -> None:
    build_root, _, _ = tmp_build_root
    with temporary_dir() as root:
        with environment_as(PANTS_BUILDROOT_OVERRIDE=root):
            assert build_root.path == root

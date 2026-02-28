# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import packaging.version

from pants.backend.python.typecheck.mypy.rules import _get_cache_args, determine_python_files
from pants.backend.python.typecheck.mypy.subsystem import MyPyCacheMode


def test_get_cache_args() -> None:
    modern_mypy = packaging.version.Version("1.0")
    old_mypy = packaging.version.Version("0.600")

    args = _get_cache_args(modern_mypy, "3.12", MyPyCacheMode.sqlite, "/cache")
    assert "--sqlite-cache" in args
    assert "--skip-cache-mtime-check" in args
    assert "--cache-dir" in args
    assert "/cache" in args

    args = _get_cache_args(modern_mypy, "3.12", MyPyCacheMode.none, "/cache")
    assert args == ("--cache-dir=/dev/null",)

    args = _get_cache_args(old_mypy, "3.12", MyPyCacheMode.sqlite, "/cache")
    assert args == ("--cache-dir=/dev/null",)

    args = _get_cache_args(modern_mypy, None, MyPyCacheMode.sqlite, "/cache")
    assert args == ("--cache-dir=/dev/null",)


def test_determine_python_files() -> None:
    assert determine_python_files([]) == ()
    assert determine_python_files(["f.py"]) == ("f.py",)
    assert determine_python_files(["f.pyi"]) == ("f.pyi",)
    assert determine_python_files(["f.py", "f.pyi"]) == ("f.pyi",)
    assert determine_python_files(["f.pyi", "f.py"]) == ("f.pyi",)
    assert determine_python_files(["script-without-extension"]) == ("script-without-extension",)

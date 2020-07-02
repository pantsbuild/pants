# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.python.pex_build_util import identify_missing_init_files


def test_identify_missing_init_files() -> None:
    assert {"a/__init__.py", "a/b/__init__.py", "a/b/c/d/__init__.py"} == set(
        identify_missing_init_files(
            ["a/b/foo.py", "a/b/c/__init__.py", "a/b/c/d/bar.py", "a/e/__init__.py"]
        )
    )

    assert {
        "src/__init__.py",
        "src/python/__init__.py",
        "src/python/a/__init__.py",
        "src/python/a/b/__init__.py",
        "src/python/a/b/c/d/__init__.py",
    } == set(
        identify_missing_init_files(
            [
                "src/python/a/b/foo.py",
                "src/python/a/b/c/__init__.py",
                "src/python/a/b/c/d/bar.py",
                "src/python/a/e/__init__.py",
            ]
        )
    )

# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
import os
import platform
from collections.abc import Mapping, MutableMapping
from textwrap import dedent

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir

SOURCES = {
    "src/python/foo.py": "import cowsay",
    "src/python/BUILD": dedent(
        """\
        python_sources(resolve="test-resolve")
        python_requirement(name="req", requirements=["cowsay==6.0"], resolve="test-resolve")
        """
    ),
}


def build_config(tmpdir: str) -> Mapping:
    cfg: MutableMapping = {
        "GLOBAL": {
            "backend_packages": ["pants.backend.python"],
        },
        "python": {
            "enable_resolves": True,
            "interpreter_constraints": [f"=={platform.python_version()}"],
            "resolves": {"test-resolve": f"{tmpdir}/test.lock"},
            "resolves_to_sources": {
                "test-resolve": ["test_pypi=cowsay; sys_platform != 'darwin'"],
            },
        },
        "python-repos": {
            "indexes": [
                "https://pypi.org/simple/",
                "test_pypi=https://test.pypi.org/simple/",
            ]
        },
        "generate-lockfiles": {
            "diff": True,
            "diff_include_unchanged": True,
        },
    }

    return cfg


def test_lock_with_different_indexes() -> None:
    """Test locking using a different index for macos and linux."""
    with setup_tmpdir(SOURCES) as tmpdir:
        pants_run = run_pants(
            [
                "generate-lockfiles",
                "--resolve=test-resolve",
            ],
            config=build_config(tmpdir),
        )

        pants_run.assert_success()

        lockfile_path = os.path.join(tmpdir, "test.lock")
        with open(lockfile_path) as f:
            lockfile = f.read()

        # Remove header
        lockfile_lines = lockfile.splitlines()
        while lockfile_lines and lockfile_lines[0].startswith("//"):
            lockfile_lines.pop(0)
        lockfile_json = json.loads("\n".join(lockfile_lines))

        macos_marker_prefix = (
            'platform_system == "Darwin" and platform_python_implementation == "CPython"'
        )
        linux_marker_prefix = (
            'platform_system == "Linux" and platform_python_implementation == "CPython"'
        )

        macos_resolve = lockfile_json["locked_resolves"][0]
        linux_resolve = lockfile_json["locked_resolves"][1]

        assert (
            "https://files.pythonhosted.org"  # From PyPI
            in macos_resolve["locked_requirements"][0]["artifacts"][0]["url"]
        )
        assert macos_marker_prefix in macos_resolve["marker"]
        assert linux_marker_prefix not in macos_resolve["marker"]

        assert (
            "https://test-files.pythonhosted.org"  # From TestPyPI
            in linux_resolve["locked_requirements"][0]["artifacts"][0]["url"]
        )
        assert linux_marker_prefix in linux_resolve["marker"]
        assert macos_marker_prefix not in linux_resolve["marker"]

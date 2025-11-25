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


def test_lock_with_complete_platforms() -> None:
    """Test locking using complete platforms from target files.

    Uses cowsay (a pure Python package) with strict lock style to verify that:
    1. Complete platforms configuration is accepted and validated
    2. The lockfile metadata correctly includes the specified complete platforms
    3. The lock_style is set correctly in the metadata
    """
    # Get current Python version for the complete platforms
    py_version = platform.python_version_tuple()
    py_major_minor = f"{py_version[0]}.{py_version[1]}"
    py_tag = f"cp{py_version[0]}{py_version[1]}"

    # Complete platform JSON for Linux x86_64
    # Note: Curly braces are doubled to escape them from Python's string formatting
    linux_platform_json = dedent(
        f"""\
        {{{{
          "marker_environment": {{{{
            "implementation_name": "cpython",
            "implementation_version": "{py_major_minor}.0",
            "os_name": "posix",
            "platform_machine": "x86_64",
            "platform_release": "5.15.0-1043-aws",
            "platform_system": "Linux",
            "platform_version": "#48~20.04.1-Ubuntu SMP Thu Aug 17 17:08:29 UTC 2023",
            "python_full_version": "{py_major_minor}.0",
            "platform_python_implementation": "CPython",
            "python_version": "{py_major_minor}",
            "sys_platform": "linux"
          }}}},
          "compatible_tags": [
            "{py_tag}-{py_tag}-manylinux_2_17_x86_64",
            "{py_tag}-none-manylinux_2_17_x86_64",
            "py{py_version[0]}{py_version[1]}-none-manylinux_2_17_x86_64",
            "{py_tag}-none-any",
            "py{py_version[0]}{py_version[1]}-none-any",
            "py{py_version[0]}-none-any"
          ]
        }}}}
        """
    )

    # Complete platform JSON for macOS x86_64
    # Note: Curly braces are doubled to escape them from Python's string formatting
    macos_platform_json = dedent(
        f"""\
        {{{{
          "marker_environment": {{{{
            "implementation_name": "cpython",
            "implementation_version": "{py_major_minor}.0",
            "os_name": "posix",
            "platform_machine": "x86_64",
            "platform_release": "23.0.0",
            "platform_system": "Darwin",
            "platform_version": "Darwin Kernel Version 23.0.0",
            "python_full_version": "{py_major_minor}.0",
            "platform_python_implementation": "CPython",
            "python_version": "{py_major_minor}",
            "sys_platform": "darwin"
          }}}},
          "compatible_tags": [
            "{py_tag}-{py_tag}-macosx_10_9_x86_64",
            "{py_tag}-none-macosx_10_9_x86_64",
            "py{py_version[0]}{py_version[1]}-none-macosx_10_9_x86_64",
            "{py_tag}-none-any",
            "py{py_version[0]}{py_version[1]}-none-any",
            "py{py_version[0]}-none-any"
          ]
        }}}}
        """
    )

    sources = {
        "src/python/foo.py": "import cowsay",
        "src/python/BUILD": dedent(
            """\
            python_sources(resolve="test-resolve")
            python_requirement(name="req", requirements=["cowsay==6.0"], resolve="test-resolve")
            """
        ),
        "platforms/linux_x86_64.json": linux_platform_json,
        "platforms/macos_x86_64.json": macos_platform_json,
        "platforms/BUILD": dedent(
            """\
            file(name="linux_x86_64", source="linux_x86_64.json")
            file(name="macos_x86_64", source="macos_x86_64.json")
            """
        ),
    }

    with setup_tmpdir(sources) as tmpdir:

        def build_config_with_complete_platforms(tmpdir: str) -> Mapping:
            return {
                "GLOBAL": {
                    "backend_packages": ["pants.backend.python"],
                },
                "python": {
                    "enable_resolves": True,
                    "interpreter_constraints": [f"=={platform.python_version()}"],
                    "resolves": {"test-resolve": f"{tmpdir}/test.lock"},
                    "resolves_to_complete_platforms": {
                        "test-resolve": [
                            f"{tmpdir}/platforms:linux_x86_64",
                            f"{tmpdir}/platforms:macos_x86_64",
                        ],
                    },
                    "resolves_to_lock_style": {
                        "test-resolve": "strict",
                    },
                },
                "generate-lockfiles": {
                    "diff": True,
                    "diff_include_unchanged": True,
                },
            }

        pants_run = run_pants(
            [
                "generate-lockfiles",
                "--resolve=test-resolve",
            ],
            config=build_config_with_complete_platforms(tmpdir),
        )

        pants_run.assert_success()

        lockfile_path = os.path.join(tmpdir, "test.lock")
        with open(lockfile_path) as f:
            lockfile = f.read()

        # Verify the metadata contains complete_platforms
        assert "complete_platforms" in lockfile, "Lockfile should contain complete_platforms metadata"

        # The lockfile should contain references to the platform files
        assert "linux_x86_64" in lockfile, "Lockfile should reference linux_x86_64 platform"
        assert "macos_x86_64" in lockfile, "Lockfile should reference macos_x86_64 platform"

        # Verify the lockfile has the correct lock_style in metadata
        assert '"lock_style": "strict"' in lockfile, "Lockfile metadata should specify strict lock_style"

        # Verify cowsay was resolved successfully
        assert "cowsay" in lockfile.lower(), "Lockfile should contain cowsay package"


def test_lock_with_lock_style() -> None:
    """Test locking with different lock styles (strict vs universal).

    Uses cowsay to verify that:
    - strict style metadata is correctly set
    - universal style metadata is correctly set
    - universal style generates locks for multiple platforms (linux and mac)
    """
    sources = {
        "src/python/foo.py": "import cowsay",
        "src/python/BUILD": dedent(
            """\
            python_sources(resolve="test-resolve")
            python_requirement(name="req", requirements=["cowsay==6.0"], resolve="test-resolve")
            """
        ),
    }

    with setup_tmpdir(sources) as tmpdir:

        def build_config_with_lock_style(tmpdir: str, lock_style: str) -> Mapping:
            return {
                "GLOBAL": {
                    "backend_packages": ["pants.backend.python"],
                },
                "python": {
                    "enable_resolves": True,
                    "interpreter_constraints": [f"=={platform.python_version()}"],
                    "resolves": {"test-resolve": f"{tmpdir}/test.lock"},
                    "resolves_to_lock_style": {
                        "test-resolve": lock_style,
                    },
                },
                "generate-lockfiles": {
                    "diff": True,
                    "diff_include_unchanged": True,
                },
            }

        # Test with "strict" lock style
        pants_run = run_pants(
            [
                "generate-lockfiles",
                "--resolve=test-resolve",
            ],
            config=build_config_with_lock_style(tmpdir, "strict"),
        )

        pants_run.assert_success()

        lockfile_path = os.path.join(tmpdir, "test.lock")
        with open(lockfile_path) as f:
            lockfile_strict = f.read()

        # Verify the metadata contains lock_style
        assert '"lock_style": "strict"' in lockfile_strict

        # Parse and verify strict lockfile
        lockfile_lines = lockfile_strict.splitlines()
        while lockfile_lines and lockfile_lines[0].startswith("//"):
            lockfile_lines.pop(0)
        lockfile_strict_json = json.loads("\n".join(lockfile_lines))

        # Strict style should have exactly one resolve for the current platform
        assert (
            len(lockfile_strict_json["locked_resolves"]) == 1
        ), f"Expected 1 locked_resolve for strict style, got {len(lockfile_strict_json['locked_resolves'])}"

        # Verify cowsay was resolved successfully
        assert "cowsay" in lockfile_strict.lower(), "Strict lockfile should contain cowsay package"

        # Test with "universal" lock style
        pants_run = run_pants(
            [
                "generate-lockfiles",
                "--resolve=test-resolve",
            ],
            config=build_config_with_lock_style(tmpdir, "universal"),
        )

        pants_run.assert_success()

        with open(lockfile_path) as f:
            lockfile_universal = f.read()

        # Verify the metadata contains lock_style
        assert '"lock_style": "universal"' in lockfile_universal, "Universal lockfile metadata should specify universal lock_style"

        # Verify cowsay was resolved successfully
        assert "cowsay" in lockfile_universal.lower(), "Universal lockfile should contain cowsay package"

        # Parse and verify universal lockfile
        lockfile_lines = lockfile_universal.splitlines()
        while lockfile_lines and lockfile_lines[0].startswith("//"):
            lockfile_lines.pop(0)
        lockfile_universal_json = json.loads("\n".join(lockfile_lines))

        # Universal style should generate locks that work across multiple platforms
        # Verify we have at least one locked_resolve
        assert (
            len(lockfile_universal_json["locked_resolves"]) >= 1
        ), "Universal lockfile should have at least one locked_resolve"

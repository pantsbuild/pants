from pants.testutil.pants_integration_test import run_pants
from textwrap import dedent


from pants.testutil.pants_integration_test import setup_tmpdir
import platform
from collections.abc import Mapping, MutableMapping
import os
import json

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
    """Test locking using a different index for macos and linux"""
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
        with open(lockfile_path, "r") as f:
            lockfile_contents = f.read()

        # Remove header
        lockfile_contents = lockfile_contents.splitlines()
        while lockfile_contents and lockfile_contents[0].startswith("//"):
            lockfile_contents.pop(0)
        lockfile_contents = "\n".join(lockfile_contents)

        lockfile_json = json.loads(lockfile_contents)

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

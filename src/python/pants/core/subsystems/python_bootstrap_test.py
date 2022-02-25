# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager
from pathlib import Path, PurePath
from typing import Iterable, List, Sequence, TypeVar

from pants.base.build_environment import get_pants_cachedir
from pants.core.subsystems.python_bootstrap import (
    PythonBootstrap,
    get_asdf_data_dir,
    get_pyenv_root,
)
from pants.engine.environment import Environment
from pants.testutil.rule_runner import RuleRunner
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import safe_mkdir_for

_T = TypeVar("_T")


@contextmanager
def setup_pexrc_with_pex_python_path(interpreter_paths):
    """A helper function for writing interpreter paths to a PEX_PYTHON_PATH variable in a .pexrc
    file.

    NB: Mutates HOME and XDG_CACHE_HOME to ensure a `~/.pexrc` that won't trample any existing file
    and will also be found.

    :param list interpreter_paths: a list of paths to interpreter binaries to include on
                                   PEX_PYTHON_PATH.
    """
    cache_dir = get_pants_cachedir()
    with temporary_dir() as home:
        xdg_cache_home = os.path.join(home, ".cache")
        with environment_as(HOME=home, XDG_CACHE_HOME=xdg_cache_home):
            target = os.path.join(xdg_cache_home, os.path.basename(cache_dir))
            safe_mkdir_for(target)
            os.symlink(cache_dir, target)

            with open(os.path.join(home, ".pexrc"), "w") as pexrc:
                pexrc.write(f"PEX_PYTHON_PATH={':'.join(interpreter_paths)}")

            yield


@contextmanager
def fake_pyenv_root(fake_versions, fake_local_version):
    with temporary_dir() as pyenv_root:
        fake_version_dirs = [os.path.join(pyenv_root, "versions", v, "bin") for v in fake_versions]
        for d in fake_version_dirs:
            os.makedirs(d)
        fake_local_version_dirs = [os.path.join(pyenv_root, "versions", fake_local_version, "bin")]
        yield pyenv_root, fake_version_dirs, fake_local_version_dirs


def materialize_indices(sequence: Sequence[_T], indices: Iterable[int]) -> List[_T]:
    return [sequence[i] for i in indices]


@contextmanager
def fake_asdf_root(
    fake_versions: List[str], fake_home_versions: List[int], fake_local_versions: List[int]
):
    with temporary_dir() as home_dir, temporary_dir() as asdf_dir:

        fake_dirs: List[Path] = []
        fake_version_dirs: List[str] = []

        fake_home_dir = Path(home_dir)
        fake_tool_versions = fake_home_dir / ".tool-versions"
        fake_home_versions_str = " ".join(materialize_indices(fake_versions, fake_home_versions))
        fake_tool_versions.write_text(f"nodejs lts\njava 8\npython {fake_home_versions_str}\n")

        fake_asdf_dir = Path(asdf_dir)
        fake_asdf_plugin_dir = fake_asdf_dir / "plugins" / "python"
        fake_asdf_installs_dir = fake_asdf_dir / "installs" / "python"

        fake_dirs.extend(
            [fake_home_dir, fake_asdf_dir, fake_asdf_plugin_dir, fake_asdf_installs_dir]
        )

        for version in fake_versions:
            fake_version_path = fake_asdf_installs_dir / version / "bin"
            fake_version_dirs.append(f"{fake_version_path}")
            fake_dirs.append(fake_version_path)

        for fake_dir in fake_dirs:
            fake_dir.mkdir(parents=True, exist_ok=True)

        yield (
            home_dir,
            asdf_dir,
            fake_version_dirs,
            # fake_home_version_dirs
            materialize_indices(fake_version_dirs, fake_home_versions),
            # fake_local_version_dirs
            materialize_indices(fake_version_dirs, fake_local_versions),
        )


def test_get_environment_paths() -> None:
    paths = PythonBootstrap.get_environment_paths(Environment({"PATH": "foo/bar:baz:/qux/quux"}))
    assert ["foo/bar", "baz", "/qux/quux"] == paths


def test_get_pex_python_paths() -> None:
    with setup_pexrc_with_pex_python_path(["foo/bar", "baz", "/qux/quux"]):
        paths = PythonBootstrap.get_pex_python_paths()
    assert ["foo/bar", "baz", "/qux/quux"] == paths


def test_get_pyenv_root() -> None:
    home = "/♡"
    default_root = f"{home}/.pyenv"
    explicit_root = f"{home}/explicit"

    assert explicit_root == get_pyenv_root(Environment({"PYENV_ROOT": explicit_root}))
    assert default_root == get_pyenv_root(Environment({"HOME": home}))
    assert get_pyenv_root(Environment({})) is None


def test_get_pyenv_paths() -> None:
    local_pyenv_version = "3.5.5"
    all_pyenv_versions = ["2.7.14", local_pyenv_version]
    RuleRunner().write_files({".python-version": f"{local_pyenv_version}\n"})
    with fake_pyenv_root(all_pyenv_versions, local_pyenv_version) as (
        pyenv_root,
        expected_paths,
        expected_local_paths,
    ):
        paths = PythonBootstrap.get_pyenv_paths(Environment({"PYENV_ROOT": pyenv_root}))
        local_paths = PythonBootstrap.get_pyenv_paths(
            Environment({"PYENV_ROOT": pyenv_root}), pyenv_local=True
        )
    assert expected_paths == paths
    assert expected_local_paths == local_paths


def test_get_asdf_dir() -> None:
    home = PurePath("♡")
    default_root = home / ".asdf"
    explicit_root = home / "explicit"

    assert explicit_root == get_asdf_data_dir(Environment({"ASDF_DATA_DIR": f"{explicit_root}"}))
    assert default_root == get_asdf_data_dir(Environment({"HOME": f"{home}"}))
    assert get_asdf_data_dir(Environment({})) is None


def test_get_asdf_paths() -> None:
    # 3.9.4 is intentionally "left out" so that it's only found if the "all installs" fallback is
    # used
    all_python_versions = ["2.7.14", "3.5.5", "3.7.10", "3.9.4", "3.9.5"]
    asdf_home_versions = [0, 1, 2]
    asdf_local_versions = [2, 1, 4]
    asdf_local_versions_str = " ".join(
        materialize_indices(all_python_versions, asdf_local_versions)
    )
    RuleRunner().write_files(
        {
            ".tool-versions": (
                "nodejs 16.0.1\n"
                "java current\n"
                f"python {asdf_local_versions_str}\n"
                "rust 1.52.0\n"
            )
        }
    )
    with fake_asdf_root(all_python_versions, asdf_home_versions, asdf_local_versions) as (
        home_dir,
        asdf_dir,
        expected_asdf_paths,
        expected_asdf_home_paths,
        expected_asdf_local_paths,
    ):
        # Check the "all installed" fallback
        all_paths = PythonBootstrap.get_asdf_paths(Environment({"ASDF_DATA_DIR": asdf_dir}))

        home_paths = PythonBootstrap.get_asdf_paths(
            Environment({"HOME": home_dir, "ASDF_DATA_DIR": asdf_dir})
        )
        local_paths = PythonBootstrap.get_asdf_paths(
            Environment({"HOME": home_dir, "ASDF_DATA_DIR": asdf_dir}), asdf_local=True
        )

        # The order the filesystem returns the "installed" folders is arbitrary
        assert set(expected_asdf_paths) == set(all_paths)

        # These have a fixed order defined by the `.tool-versions` file
        assert expected_asdf_home_paths == home_paths
        assert expected_asdf_local_paths == local_paths


def test_expand_interpreter_search_paths() -> None:
    local_pyenv_version = "3.5.5"
    all_python_versions = ["2.7.14", local_pyenv_version, "3.7.10", "3.9.4", "3.9.5"]
    asdf_home_versions = [0, 1, 2]
    asdf_local_versions = [2, 1, 4]
    asdf_local_versions_str = " ".join(
        materialize_indices(all_python_versions, asdf_local_versions)
    )
    RuleRunner().write_files(
        {
            ".python-version": f"{local_pyenv_version}\n",
            ".tool-versions": (
                "nodejs 16.0.1\n"
                "java current\n"
                f"python {asdf_local_versions_str}\n"
                "rust 1.52.0\n"
            ),
        }
    )
    with setup_pexrc_with_pex_python_path(["/pexrc/path1:/pexrc/path2"]):
        with fake_asdf_root(all_python_versions, asdf_home_versions, asdf_local_versions) as (
            home_dir,
            asdf_dir,
            expected_asdf_paths,
            expected_asdf_home_paths,
            expected_asdf_local_paths,
        ), fake_pyenv_root(all_python_versions, local_pyenv_version) as (
            pyenv_root,
            expected_pyenv_paths,
            expected_pyenv_local_paths,
        ):
            paths = [
                "/foo",
                "<PATH>",
                "/bar",
                "<PEXRC>",
                "/baz",
                "<ASDF>",
                "<ASDF_LOCAL>",
                "<PYENV>",
                "<PYENV_LOCAL>",
                "/qux",
            ]
            env = Environment(
                {
                    "HOME": home_dir,
                    "PATH": "/env/path1:/env/path2",
                    "PYENV_ROOT": pyenv_root,
                    "ASDF_DATA_DIR": asdf_dir,
                }
            )
            expanded_paths = PythonBootstrap._expand_interpreter_search_paths(
                paths,
                env,
            )

    expected = [
        "/foo",
        "/env/path1",
        "/env/path2",
        "/bar",
        "/pexrc/path1",
        "/pexrc/path2",
        "/baz",
        *expected_asdf_home_paths,
        *expected_asdf_local_paths,
        *expected_pyenv_paths,
        *expected_pyenv_local_paths,
        "/qux",
    ]
    assert expected == expanded_paths

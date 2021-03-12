# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager

import pytest

from pants.base.build_environment import get_pants_cachedir
from pants.engine.environment import Environment
from pants.python.python_setup import PythonSetup, get_pyenv_root
from pants.testutil.rule_runner import RuleRunner
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import safe_mkdir_for


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


def test_get_environment_paths() -> None:
    paths = PythonSetup.get_environment_paths(Environment({"PATH": "foo/bar:baz:/qux/quux"}))
    assert ["foo/bar", "baz", "/qux/quux"] == paths


def test_get_pex_python_paths() -> None:
    with setup_pexrc_with_pex_python_path(["foo/bar", "baz", "/qux/quux"]):
        paths = PythonSetup.get_pex_python_paths()
    assert ["foo/bar", "baz", "/qux/quux"] == paths


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner()


def test_get_pyenv_root() -> None:
    home = "/♡"
    default_root = f"{home}/.cache"
    explicit_root = f"{home}/explicit"

    assert explicit_root == get_pyenv_root(Environment({"PYENV_ROOT": explicit_root}))
    assert default_root == get_pyenv_root(Environment({"HOME": home}))
    assert get_pyenv_root(Environment({})) is None


def test_get_pyenv_paths(rule_runner: RuleRunner) -> None:
    local_pyenv_version = "3.5.5"
    all_pyenv_versions = ["2.7.14", local_pyenv_version]
    rule_runner.create_file(".python-version", local_pyenv_version + "\n")
    with fake_pyenv_root(all_pyenv_versions, local_pyenv_version) as (
        pyenv_root,
        expected_paths,
        expected_local_paths,
    ):
        paths = PythonSetup.get_pyenv_paths(Environment({"PYENV_ROOT": pyenv_root}))
        local_paths = PythonSetup.get_pyenv_paths(
            Environment({"PYENV_ROOT": pyenv_root}), pyenv_local=True
        )
    assert expected_paths == paths
    assert expected_local_paths == local_paths


def test_expand_interpreter_search_paths(rule_runner: RuleRunner) -> None:
    local_pyenv_version = "3.5.5"
    all_pyenv_versions = ["2.7.14", local_pyenv_version]
    rule_runner.create_file(".python-version", local_pyenv_version + "\n")
    with setup_pexrc_with_pex_python_path(["/pexrc/path1:/pexrc/path2"]):
        with fake_pyenv_root(all_pyenv_versions, local_pyenv_version) as (
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
                "<PYENV>",
                "<PYENV_LOCAL>",
                "/qux",
            ]
            env = Environment({"PATH": "/env/path1:/env/path2", "PYENV_ROOT": pyenv_root})
            expanded_paths = PythonSetup.expand_interpreter_search_paths(
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
        *expected_pyenv_paths,
        *expected_pyenv_local_paths,
        "/qux",
    ]
    assert expected == expanded_paths

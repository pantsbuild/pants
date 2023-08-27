# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterable, List, Sequence, TypeVar

import pytest

from pants.base.build_environment import get_pants_cachedir
from pants.core.subsystems.python_bootstrap import (
    _ExpandInterpreterSearchPathsRequest,
    _get_pex_python_paths,
    _get_pyenv_root,
    _SearchPaths,
)
from pants.core.subsystems.python_bootstrap import rules as python_bootstrap_rules
from pants.core.util_rules import asdf
from pants.core.util_rules.asdf import AsdfToolPathsRequest, AsdfToolPathsResult
from pants.core.util_rules.environments import EnvironmentTarget, LocalEnvironmentTarget
from pants.core.util_rules.search_paths import (
    VersionManagerSearchPaths,
    VersionManagerSearchPathsRequest,
)
from pants.core.util_rules.testutil import fake_asdf_root
from pants.engine.addresses import Address
from pants.engine.env_vars import CompleteEnvironmentVars, EnvironmentVars
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import safe_mkdir_for

_T = TypeVar("_T")


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *python_bootstrap_rules(),
            *asdf.rules(),
            QueryRule(AsdfToolPathsResult, (AsdfToolPathsRequest,)),
            QueryRule(_SearchPaths, [_ExpandInterpreterSearchPathsRequest]),
            QueryRule(VersionManagerSearchPaths, (VersionManagerSearchPathsRequest,)),
        ],
        target_types=[],
    )


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
        fake_version_dirs = tuple(
            os.path.join(pyenv_root, "versions", v, "bin") for v in fake_versions
        )
        for d in fake_version_dirs:
            os.makedirs(d)
        fake_local_version_dirs = (os.path.join(pyenv_root, "versions", fake_local_version, "bin"),)
        yield pyenv_root, fake_version_dirs, fake_local_version_dirs


def materialize_indices(sequence: Sequence[_T], indices: Iterable[int]) -> List[_T]:
    return [sequence[i] for i in indices]


def test_get_pex_python_paths() -> None:
    with setup_pexrc_with_pex_python_path(["foo/bar", "baz", "/qux/quux"]):
        paths = _get_pex_python_paths()
    assert ["foo/bar", "baz", "/qux/quux"] == paths


_HOME = "/♡"


@pytest.mark.parametrize(
    "env, expected",
    [
        pytest.param({"PYENV_ROOT": f"{_HOME}/explicit"}, f"{_HOME}/explicit", id="explicit_root"),
        pytest.param({"HOME": _HOME}, f"{_HOME}/.pyenv", id="default_root"),
        pytest.param({}, None, id="no_env"),
    ],
)
def test_get_pyenv_root(env: dict[str, str], expected: str | None) -> None:
    result = _get_pyenv_root(EnvironmentVars(env))
    assert result == expected


def test_expand_interpreter_search_paths(rule_runner: RuleRunner) -> None:
    local_pyenv_version = "3.5.5"
    all_python_versions = ["2.7.14", local_pyenv_version, "3.7.10", "3.9.4", "3.9.5"]
    asdf_home_versions = [0, 1, 2]
    asdf_local_versions = [2, 1, 4]
    asdf_local_versions_str = " ".join(
        materialize_indices(all_python_versions, asdf_local_versions)
    )
    rule_runner.write_files(
        {
            ".python-version": f"{local_pyenv_version}\n",
            ".tool-versions": "\n".join(
                [
                    "nodejs 16.0.1",
                    "java current",
                    f"python {asdf_local_versions_str}",
                    "rust 1.52.0",
                ]
            ),
        }
    )
    env_name = "name"
    with setup_pexrc_with_pex_python_path(["/pexrc/path1:/pexrc/path2"]):
        with fake_asdf_root(
            all_python_versions, asdf_home_versions, asdf_local_versions, tool_name="python"
        ) as (
            home_dir,
            asdf_dir,
            expected_asdf_paths,
            expected_asdf_home_paths,
            expected_asdf_local_paths,
        ), fake_pyenv_root(
            all_python_versions, local_pyenv_version
        ) as (
            pyenv_root,
            expected_pyenv_paths,
            expected_pyenv_local_paths,
        ):
            rule_runner.set_session_values(
                {
                    CompleteEnvironmentVars: CompleteEnvironmentVars(
                        {
                            "HOME": home_dir,
                            "PATH": "/env/path1:/env/path2",
                            "PYENV_ROOT": pyenv_root,
                            "ASDF_DATA_DIR": asdf_dir,
                        },
                    )
                }
            )

            paths = (
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
            )
            expanded_paths = rule_runner.request(
                _SearchPaths,
                [
                    _ExpandInterpreterSearchPathsRequest(
                        paths,
                        EnvironmentTarget(env_name, LocalEnvironmentTarget({}, Address("flem"))),
                    )
                ],
            )

    expected = (
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
    )
    assert set(expected) == set(expanded_paths.paths)
